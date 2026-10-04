"""Settings and sync control. The write side of the API."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from sqlalchemy import func, select

from app import audit
from app.auth.deps import AdminUser
from app.db import session_scope
from app.geo.lookup import ensure_databases
from app.models import History
from app.services import sync as sync_service
from app.settings_store import (
    current,
    describe,
    is_configured,
    locked_keys,
    missing_required,
    save,
)
from app.tautulli.client import TautulliClient
from app.redact import redact

router = APIRouter(prefix="/api")

_sync_lock = asyncio.Lock()

SECRET_HINT = ("key", "token", "secret", "password")


def _redact(key: str, value: Any) -> Any:
    if key in audit.SECRET_URLS and value:
        # Shape kept, secrets masked, so one URL can be edited without
        # retyping the rest. Put back on save (see put_settings).
        from app.url_mask import mask

        return mask(str(value))
    if audit.is_secret(key) and value:
        return "********"
    return value


@router.get("/setup")
def setup_status() -> dict:
    """First-run state. The UI shows the setup wizard while `configured` is
    false, and the settings page afterwards."""
    settings = current()
    with session_scope() as session:
        rows = session.execute(select(func.count()).select_from(History)).scalar_one()
    return {
        "configured": is_configured(),
        "missing": missing_required(),
        # Env-supplied values are already filled in and locked, so the wizard
        # should render them read-only rather than asking again.
        "locked": sorted(locked_keys() - {"data_dir"}),
        "geoip_ready": (settings.geoip_dir / "city.mmdb").exists(),
        "history_rows": rows,
        # Setup asks for Tautulli and for MaxMind, and never mentions the one
        # thing it cannot test for you: TZ decides what every time of day rule
        # will mean, and a wrong one is silent for ever. Showing the clock is
        # the whole fix. Not a secret, so it is here rather than behind the
        # sign-in that does not exist yet.
        "clock": _clock(),
    }


def _clock() -> dict:
    import os
    import time
    from datetime import datetime

    now = datetime.now()
    return {
        "now": now.isoformat(timespec="seconds"),
        "zone": os.environ.get("TZ") or (time.tzname[time.daylight and time.localtime().tm_isdst > 0] or "unset"),
    }


@router.post("/setup/test-tautulli")
async def test_tautulli(
    tautulli_url: str = Body(...),
    tautulli_api_key: str = Body(...),
    tautulli_local_url: str = Body(""),
) -> dict:
    """Check credentials without saving them.

    Both URLs are reported separately: a LAN address that fails here is fine
    (it just won't be preferred), but a remote URL that fails is fatal.
    """

    async def probe(url: str) -> dict:
        if not url:
            return {"tried": False}
        probe_settings = current().model_copy(
            update={
                "tautulli_url": url,
                "tautulli_local_url": "",
                "tautulli_api_key": tautulli_api_key,
            }
        )
        client = TautulliClient(probe_settings)
        try:
            info = await client.call("get_server_info") or {}
            return {
                "tried": True,
                "ok": True,
                "server_name": info.get("pms_name"),
                "version": info.get("pms_version"),
            }
        except Exception as exc:  # noqa: BLE001 - the failure IS the answer here
            return {"tried": True, "ok": False, "error": redact(exc)}
        finally:
            await client.aclose()

    remote = await probe(tautulli_url)
    local = await probe(tautulli_local_url)
    return {"ok": bool(remote.get("ok")), "remote": remote, "local": local}


@router.post("/setup/test-maxmind")
def test_maxmind(
    maxmind_account_id: str = Body(...), maxmind_license_key: str = Body(...)
) -> dict:
    """Verify MaxMind credentials by actually fetching the databases.

    A freshly issued licence key can take a few minutes to become valid, so a
    failure here is worth retrying before assuming the key is wrong.
    """
    settings = current()
    try:
        ensure_databases(
            settings.geoip_dir, maxmind_account_id, maxmind_license_key, max_age_days=0
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": redact(exc)}

    ready = (settings.geoip_dir / "city.mmdb").exists()
    return {
        "ok": ready,
        "error": None if ready else "Download failed. Check the key, or retry in a few minutes",
    }


@router.get("/server-time")
def server_time(_: AdminUser) -> dict:
    """What the server believes the time is, and what it calls that.

    Every time-of-day rule, and the hour a backup is taken, read the
    container's clock, which is whatever TZ says. Set it wrong and "no
    transcodes after ten" fires six hours out, silently and for ever. Nothing
    anywhere showed this, so there was no way to notice.
    """
    import os
    import time
    from datetime import datetime

    now = datetime.now()
    return {
        "now": now.isoformat(timespec="seconds"),
        "hour": now.hour,
        "zone": os.environ.get("TZ") or (time.tzname[time.daylight and time.localtime().tm_isdst > 0] or "unset"),
    }


@router.get("/settings")
def get_settings() -> list[dict]:
    """Every setting, its value, and whether the environment owns it.

    `source: environment` means an env var (Unraid docker config) supplied it,
    so the UI must render it read-only, same as Radarr.
    """
    return [{**row, "value": _redact(row["key"], row["value"])} for row in describe()]


@router.put("/settings")
def put_settings(admin: AdminUser, values: dict[str, Any] = Body(...)) -> list[dict]:
    before = {row["key"]: row["value"] for row in describe()}
    from app.url_mask import restore

    values = dict(values)
    try:
        for key in audit.SECRET_URLS & set(values):
            values[key] = restore(str(values[key] or ""), str(before.get(key) or ""))
        save(values)
    except ValueError as exc:
        raise HTTPException(400, redact(exc)) from exc

    if {"media_roots", "media_path_map"} & set(values):
        # Which disk a library is on was worked out from the old paths.
        from app.services import space

        space.forget_mounts()

    changes = {
        key: (
            {"changed": True}
            if audit.is_secret(key)
            else {"before": before.get(key), "after": value}
        )
        for key, value in values.items()
    }
    audit.record(
        admin,
        "settings.save",
        f"Changed {len(values)} setting{'s' if len(values) != 1 else ''}: {', '.join(sorted(values))}",
        detail=changes,
    )
    return get_settings()


@router.post("/sync/run")
async def sync_run(admin: AdminUser, full: bool = False) -> dict:
    if not is_configured():
        raise HTTPException(409, f"Not configured yet. Missing: {', '.join(missing_required())}")
    if _sync_lock.locked():
        raise HTTPException(409, "A sync is already running")
    audit.record(admin, "sync.run", "Started a full resync" if full else "Started a sync")

    async with _sync_lock:
        settings = current()
        ensure_databases(
            settings.geoip_dir,
            settings.maxmind_account_id,
            settings.maxmind_license_key,
            settings.geoip_update_interval_days,
        )
        client = TautulliClient(settings)
        try:
            slow = await sync_service.run_slow_sync(client)
            main = await sync_service.run_sync(client, settings, full=full)
        finally:
            await client.aclose()
    return {**slow, **main}


# ---- about and updates ----------------------------------------------------------------------

@router.get("/about")
async def about() -> dict:
    from app.services import updates
    from app.version import VERSION, changelog, commit

    settings = current()
    return {
        "version": VERSION,
        "commit": commit(),
        "changelog": changelog(),
        "check_enabled": settings.update_check_enabled,
        "repository": settings.update_repository,
        "update": await asyncio.to_thread(updates.stored),
    }


@router.get("/about/status")
async def about_status() -> dict:
    """Just enough for the flag on Settings."""
    from app.services import updates
    from app.version import VERSION

    found = await asyncio.to_thread(updates.stored)
    return {"version": VERSION, "status": (found or {}).get("status")}


@router.post("/about/check")
async def check_updates(admin: AdminUser) -> dict:
    from app import tasks
    from app.services import updates

    if tasks.TASKS["update_check"].running:
        raise HTTPException(409, "Already checking")
    await tasks.run("update_check", trigger="manual")
    return await asyncio.to_thread(updates.stored) or {}


# ---- background tasks ----------------------------------------------------------------------

@router.get("/tasks")
def list_tasks() -> list[dict]:
    from app import tasks

    return tasks.describe()


@router.get("/tasks/{key}/runs")
def task_runs(key: str, limit: int = 50) -> list[dict]:
    from app import tasks
    from app.models import TaskRun

    if key not in tasks.TASKS:
        raise HTTPException(404, "No such task")
    with session_scope() as db:
        rows = db.execute(
            select(TaskRun).where(TaskRun.task == key).order_by(TaskRun.id.desc()).limit(min(limit, 100))
        ).scalars().all()
        return [
            {"id": r.id, "started_at": r.started_at.isoformat() if r.started_at else None, "duration_ms": r.duration_ms,
             "status": r.status, "message": r.message, "trigger": r.trigger}
            for r in rows
        ]


@router.post("/tasks/{key}/run")
async def run_task(key: str, admin: AdminUser) -> dict:
    """Start a task now, in the background. The page follows its status."""
    from app import tasks

    if key not in tasks.TASKS:
        raise HTTPException(404, "No such task")
    if tasks.TASKS[key].running:
        raise HTTPException(409, "It is running already")
    asyncio.get_running_loop().create_task(tasks.run(key, trigger="manual"))
    audit.record(admin, "task.run", f"Ran {tasks.TASKS[key].name} by hand", target=key)
    return {"started": True}

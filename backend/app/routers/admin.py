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
    plex_configured,
    save,
    tautulli_configured,
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
        # Which connections already work, so setup can skip a question the
        # environment has answered, and say what an install has without one.
        "plex": plex_configured(),
        "tautulli": tautulli_configured(),
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

    # A field the environment set is shown locked and sent empty, so the
    # value already held is the one to test.
    tautulli_url = tautulli_url or current().tautulli_url
    tautulli_api_key = tautulli_api_key or current().tautulli_api_key

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


def _save_unlocked(values: dict[str, Any]) -> dict[str, Any]:
    """Save what the environment has not already decided, and say what it has.

    Setup must never fail on a key the container's own variables set: those
    are the operator's word, and refusing the whole step over one of them
    would leave somebody unable to finish."""
    locked = locked_keys()
    free = {k: v for k, v in values.items() if k not in locked}
    if free:
        save(free)
    return {k: getattr(current(), k) for k in values if k in locked}


@router.post("/setup/plex/link")
async def plex_link_start(_: AdminUser) -> dict:
    """A code to type at plex.tv/link, in place of a password."""
    from app.plex import link

    try:
        return await asyncio.to_thread(link.start)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"plex.tv did not answer: {redact(exc)}") from exc


@router.post("/setup/plex/link/{link_id}")
async def plex_link_check(link_id: str, admin: AdminUser) -> dict:
    """Whether the code has been entered yet. The token goes straight into
    the settings store and is never sent back to the page."""
    from app.plex import link
    from app.plex import server as plex_server

    if "plex_token" in locked_keys():
        raise HTTPException(409, "The Plex token is set by the environment, so there is nothing to link")
    try:
        token = await asyncio.to_thread(link.check, link_id)
    except link.Expired as exc:
        raise HTTPException(410, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"plex.tv did not answer: {redact(exc)}") from exc
    if token is None:
        return {"linked": False}
    save({"plex_token": token})
    plex_server.forget()
    audit.record(admin, "settings.save", "Linked this install to a Plex account", detail={"plex_token": {"changed": True}})
    return {"linked": True}


@router.post("/setup/plex/token")
async def plex_token_paste(admin: AdminUser, plex_token: str = Body(..., embed=True)) -> dict:
    """For somebody who already has a token. Checked against plex.tv before it
    is kept, so a mistyped one fails here rather than as an empty server list."""
    from plexapi.myplex import MyPlexAccount

    from app.plex import server as plex_server

    token = plex_token.strip()
    if not token:
        raise HTTPException(400, "Paste the token first")
    if "plex_token" in locked_keys():
        raise HTTPException(409, "The Plex token is set by the environment")
    try:
        await asyncio.to_thread(MyPlexAccount, token=token)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"plex.tv did not accept that token: {redact(exc)}") from exc
    save({"plex_token": token})
    plex_server.forget()
    audit.record(admin, "settings.save", "Set the Plex token by hand", detail={"plex_token": {"changed": True}})
    return {"linked": True}


@router.post("/setup/plex/use")
async def plex_use(admin: AdminUser, plex_url: str = Body(..., embed=True)) -> dict:
    """Keep this address and read from Plex directly.

    The address is tried first and kept only if it answers, since everything
    live depends on it. Both sources move to Plex together: that is what the
    choice at the top of setup means.
    """
    from app.plex import server as plex_server

    url = plex_url.strip().rstrip("/")
    if not url:
        raise HTTPException(400, "Choose an address first")
    answer = await asyncio.to_thread(plex_server.reachable, url)
    if not answer.get("ok"):
        raise HTTPException(502, f"That address did not answer: {answer.get('error')}")
    values: dict[str, Any] = {"plex_url": url, "activity_source": "plex", "library_source": "plex"}
    if answer.get("machine_identifier"):
        values["plex_machine_identifier"] = answer["machine_identifier"]
    kept = _save_unlocked(values)
    plex_server.forget()
    audit.record(admin, "settings.save", f"Set up to read from Plex directly at {url}", detail={"plex_url": {"after": url}})
    return {"ok": True, "name": answer.get("name"), "ms": answer.get("ms"), "kept_by_environment": kept}


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


@router.get("/plex/servers")
async def plex_servers(_: AdminUser) -> dict:
    """Every server this token can reach, with an address for each.

    The one slow call, which is the reason the address is stored afterwards:
    letting the library find it costs twenty seconds every time, because Plex
    advertises addresses that are unreachable from outside the house and each
    one has to be waited out.
    """
    import asyncio

    from app.plex import server as plex_server

    try:
        found = await asyncio.to_thread(plex_server.discover)
    except plex_server.NotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Plex said: {redact(exc)}") from exc
    return {"servers": found}


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
    if not tautulli_configured():
        # Nothing to read, but the plays recorded from Plex still have devices,
        # places and sharing signals to be built from them.
        async with _sync_lock:
            return await sync_service.run_sync(None, current(), full=full)

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


@router.get("/handover/check")
async def history_check(_: AdminUser) -> dict:
    """Day by day, what Tautulli recorded against what is here.

    Answered now rather than started in the background, because it is one
    request to Tautulli and a count, under a second on a four year library,
    and a question somebody asked deserves an answer rather than a spinner.
    """
    from app.services import handover
    from app.settings_store import tautulli_configured

    if not tautulli_configured():
        return {"asked": False, "reason": "Tautulli is not connected, so there is nothing to compare against"}
    client = TautulliClient(current())
    try:
        return await handover.compare(client)
    finally:
        await client.aclose()


@router.get("/handover/agreement")
async def handover_agreement(_: AdminUser) -> dict:
    """Ask both sources about the same things and compare them field by field.

    Counting is not enough. A total agreeing says nothing about whether the
    right value reached the right column, which is how the transcode decision
    nearly went wrong: both sources reported the stream and they called it
    different things.
    """
    from app.plex.server import configured as plex_configured
    from app.services import agreement
    from app.settings_store import tautulli_configured

    if not tautulli_configured() or not plex_configured():
        return {"asked": False, "reason": "Both Plex and Tautulli have to be connected to compare them"}
    client = TautulliClient(current())
    try:
        return {"asked": True, "files": await agreement.files(client), "streams": await agreement.streams(client)}
    finally:
        await client.aclose()


@router.post("/handover/fill")
async def history_fill(admin: AdminUser) -> dict:
    """Fetch the days that are short, and nothing else."""
    from app.services import handover
    from app.settings_store import tautulli_configured

    if not tautulli_configured():
        raise HTTPException(400, "Tautulli is not connected")
    client = TautulliClient(current())
    try:
        found = await handover.compare(client)
        if not found.get("asked"):
            raise HTTPException(502, found.get("reason") or "Tautulli did not answer")
        filled = await handover.fill(client, found)
    finally:
        await client.aclose()
    if filled["filled"]:
        audit.record(
            admin, "history.fill",
            f"Fetched {filled['filled']} plays across {filled['days']} days Tautulli had and this did not",
            detail=filled,
        )
    return {**filled, "missing_before": found["missing"]}

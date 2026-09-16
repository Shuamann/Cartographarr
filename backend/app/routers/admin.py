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
from app.models import History, IpLocation, MediaItem, SyncState
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

router = APIRouter(prefix="/api")

_sync_lock = asyncio.Lock()

SECRET_HINT = ("key", "token", "secret", "password")


def _redact(key: str, value: Any) -> Any:
    if any(hint in key for hint in SECRET_HINT) and value:
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
            return {"tried": True, "ok": False, "error": str(exc)}
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
        return {"ok": False, "error": str(exc)}

    ready = (settings.geoip_dir / "city.mmdb").exists()
    return {
        "ok": ready,
        "error": None if ready else "Download failed. Check the key, or retry in a few minutes",
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
    try:
        save(values)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

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


@router.get("/sync/status")
def sync_status() -> dict:
    with session_scope() as session:
        counts = session.execute(
            select(
                select(func.count()).select_from(History).scalar_subquery(),
                select(func.count()).select_from(IpLocation).scalar_subquery(),
                select(func.count()).select_from(MediaItem).scalar_subquery(),
            )
        ).one()
        state = {row.key: row.value for row in session.execute(select(SyncState)).scalars()}

    return {
        "running": _sync_lock.locked(),
        "history_rows": counts[0],
        "ip_locations": counts[1],
        "media_items": counts[2],
        "state": state,
    }


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

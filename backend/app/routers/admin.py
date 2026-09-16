"""Settings and sync control. The write side of the API."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from sqlalchemy import func, select

from app.db import session_scope
from app.geo.lookup import ensure_databases
from app.models import History, IpLocation, MediaItem, SyncState
from app.services import sync as sync_service
from app.settings_store import current, describe, save
from app.tautulli.client import TautulliClient

router = APIRouter(prefix="/api")

_sync_lock = asyncio.Lock()

SECRET_HINT = ("key", "token", "secret", "password")


def _redact(key: str, value: Any) -> Any:
    if any(hint in key for hint in SECRET_HINT) and value:
        return "********"
    return value


@router.get("/settings")
def get_settings() -> list[dict]:
    """Every setting, its value, and whether the environment owns it.

    `source: environment` means an env var (Unraid docker config) supplied it,
    so the UI must render it read-only — same as Radarr.
    """
    return [{**row, "value": _redact(row["key"], row["value"])} for row in describe()]


@router.put("/settings")
def put_settings(values: dict[str, Any] = Body(...)) -> list[dict]:
    try:
        save(values)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
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
async def sync_run(full: bool = False) -> dict:
    if _sync_lock.locked():
        raise HTTPException(409, "A sync is already running")

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

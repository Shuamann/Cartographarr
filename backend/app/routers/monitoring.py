"""Numbers for monitoring tools.

`/metrics` in Prometheus text format, and `/api/summary` as JSON for
dashboard tiles like Homepage and Homarr. Both are off until a metrics token
is set in Settings, and both require it, as a bearer token or a `token`
query parameter (Homepage's custom API widget can send either).

Counts only. Nothing here names a person, an address, a device or a title,
since these are meant to be scraped by other tools.
"""

from __future__ import annotations

import hmac
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AppUser, BannedDevice, Device, EnforcementLog, History, Rule, SyncState, TravelFlag, User
from app.plays import plays
from app.settings_store import current, is_configured
from app.tautulli.client import TautulliClient

router = APIRouter()

_live_cache: dict[str, Any] = {"at": 0.0, "value": None}
LIVE_SECONDS = 10


def _authorise(request: Request) -> None:
    token = current().metrics_token
    if not token:
        # Off, and indistinguishable from not existing.
        raise HTTPException(404, "Not found")
    header = request.headers.get("authorization", "")
    given = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("token", "")
    if not hmac.compare_digest(given.encode(), token.encode()):
        raise HTTPException(401, "Metrics token missing or wrong")


async def _live() -> dict[str, Any]:
    """Current streams, cached briefly so a fast scrape does not hammer Tautulli."""
    now = time.monotonic()
    if _live_cache["value"] is not None and now - _live_cache["at"] < LIVE_SECONDS:
        return _live_cache["value"]
    value = {"streams": 0, "transcodes": 0, "bandwidth_kbps": 0, "reachable": False}
    if is_configured():
        client = TautulliClient(current())
        try:
            data = await client.call("get_activity") or {}
            value = {
                "streams": int(data.get("stream_count") or 0),
                "transcodes": int(data.get("stream_count_transcode") or 0),
                "bandwidth_kbps": int(data.get("total_bandwidth") or 0),
                "reachable": True,
            }
        except Exception:  # noqa: BLE001 - an unreachable Tautulli is itself a reading
            pass
        finally:
            await client.aclose()
    _live_cache.update(at=now, value=value)
    return value


def _counts() -> dict[str, Any]:
    day_start = int(time.time()) - 86400
    with session_scope() as db:

        def count(stmt) -> int:
            return db.execute(stmt).scalar_one()

        state = {row.key: row.value for row in db.execute(select(SyncState)).scalars()}
        return {
            "plays": count(select(plays(History)).select_from(History)),
            "plays_24h": count(select(plays(History)).select_from(History).where(History.started >= day_start)),
            "sessions": count(select(func.count()).select_from(History)),
            "sessions_24h": count(select(func.count()).select_from(History).where(History.started >= day_start)),
            "users": count(select(func.count()).select_from(User)),
            "devices": count(select(func.count(func.distinct(Device.machine_id)))),
            "devices_unreviewed": count(
                select(func.count(func.distinct(Device.machine_id))).where(Device.is_new_unreviewed.is_(True))
            ),
            "signals_open": count(select(func.count()).select_from(TravelFlag).where(TravelFlag.status == "new")),
            "banned_devices": count(select(func.count()).select_from(BannedDevice)),
            "rules_enabled": count(select(func.count()).select_from(Rule).where(Rule.enabled.is_(True))),
            "streams_stopped": count(
                select(func.count()).select_from(EnforcementLog).where(EnforcementLog.dry_run.is_(False))
            ),
            "streams_recorded_only": count(
                select(func.count()).select_from(EnforcementLog).where(EnforcementLog.dry_run.is_(True))
            ),
            "accounts": count(select(func.count()).select_from(AppUser)),
            "last_sync_at": int(state["last_sync_at"]) if state.get("last_sync_at") else None,
        }


@router.get("/api/summary")
async def summary(request: Request) -> dict:
    """One small JSON object for a dashboard tile."""
    _authorise(request)
    live = await _live()
    counts = _counts()
    last = counts["last_sync_at"]
    return {
        **live,
        **counts,
        "last_sync_age_seconds": int(time.time()) - last if last else None,
    }


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request) -> str:
    """Prometheus text exposition format."""
    _authorise(request)
    live = await _live()
    counts = _counts()

    rows = [
        ("cartographarr_streams", "gauge", "Streams playing now", live["streams"]),
        ("cartographarr_transcodes", "gauge", "Streams transcoding now", live["transcodes"]),
        ("cartographarr_bandwidth_kbps", "gauge", "Total streaming bandwidth now, in kbps", live["bandwidth_kbps"]),
        ("cartographarr_tautulli_up", "gauge", "Whether Tautulli answered", int(live["reachable"])),
        ("cartographarr_plays_total", "counter", "Plays in history", counts["plays"]),
        ("cartographarr_plays_last_24h", "gauge", "Plays started in the last 24 hours", counts["plays_24h"]),
        ("cartographarr_users", "gauge", "Plex users known", counts["users"]),
        ("cartographarr_devices", "gauge", "Devices known", counts["devices"]),
        ("cartographarr_devices_unreviewed", "gauge", "Devices new and not yet reviewed", counts["devices_unreviewed"]),
        ("cartographarr_signals_open", "gauge", "Sharing signals not yet reviewed", counts["signals_open"]),
        ("cartographarr_banned_devices", "gauge", "Devices on the ban list", counts["banned_devices"]),
        ("cartographarr_rules_enabled", "gauge", "Rules switched on", counts["rules_enabled"]),
        ("cartographarr_streams_stopped_total", "counter", "Streams stopped by rules or by hand", counts["streams_stopped"]),
        (
            "cartographarr_streams_recorded_only_total",
            "counter",
            "Matches recorded by rules set to record only",
            counts["streams_recorded_only"],
        ),
    ]
    if counts["last_sync_at"]:
        rows.append(
            (
                "cartographarr_last_sync_timestamp_seconds",
                "gauge",
                "When the last sync finished, as a Unix time",
                counts["last_sync_at"],
            )
        )

    lines: list[str] = []
    for name, kind, help_text, value in rows:
        lines += [f"# HELP {name} {help_text}", f"# TYPE {name} {kind}", f"{name} {value}"]
    return "\n".join(lines) + "\n"

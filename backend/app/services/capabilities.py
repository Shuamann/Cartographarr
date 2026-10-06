"""What this install can actually do.

One map, two sources: the Plex server (via Tautulli) and, later, configured
integrations. The UI reads it to disable controls with a reason rather than
hiding them, and the API enforces it independently. UI gating is a courtesy,
not a control.

Plex Pass comes from Tautulli's get_server_info (`pms_plexpass`) when Tautulli
is connected, and from Plex itself when it is not. Stream termination depends
on it, so an install with no Tautulli has to be able to answer it too.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.db import session_scope
from app.models import SyncState
from app.settings_store import current, is_configured, plex_configured, tautulli_configured
from app.tautulli.client import TautulliClient
from app.redact import redact

log = logging.getLogger(__name__)

STATE_KEY = "server_capabilities"
TTL_SECONDS = 3600

_cache: dict[str, Any] | None = None


def _load_persisted() -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.get(SyncState, STATE_KEY)
        if row is None:
            return None
    try:
        return json.loads(row.value)
    except ValueError:
        return None


def _persist(value: dict[str, Any]) -> None:
    with session_scope() as session:
        session.merge(SyncState(key=STATE_KEY, value=json.dumps(value)))


async def refresh() -> dict[str, Any]:
    """Ask Tautulli what the server supports. Never raises."""
    global _cache

    result: dict[str, Any] = {
        "probed_at": time.time(),
        "plex_pass": None,  # None = unknown, not False
        "server_name": None,
        "server_version": None,
        "machine_identifier": None,
        "error": None,
    }

    if not is_configured():
        result["error"] = "Not set up yet"
    elif not tautulli_configured() and plex_configured():
        import asyncio

        from app.plex import control

        try:
            result.update(await asyncio.to_thread(control.describe))
        except Exception as exc:  # noqa: BLE001 - unknown is a valid answer
            result["error"] = redact(exc)
            log.warning("capability probe failed: %s", redact(exc))
    else:
        client = TautulliClient(current())
        try:
            info = await client.call("get_server_info") or {}
            result.update(
                plex_pass=str(info.get("pms_plexpass")) == "1",
                server_name=info.get("pms_name"),
                server_version=info.get("pms_version"),
                machine_identifier=info.get("pms_identifier"),
            )
        except Exception as exc:  # noqa: BLE001 - unknown is a valid answer
            result["error"] = redact(exc)
            log.warning("capability probe failed: %s", exc)
        finally:
            await client.aclose()

    # Unknown must not overwrite a previously known answer: a Tautulli restart
    # shouldn't make Kill Stream disappear from the UI.
    if result["plex_pass"] is None:
        previous = _cache or _load_persisted()
        if previous and previous.get("plex_pass") is not None:
            result["plex_pass"] = previous["plex_pass"]
            result["machine_identifier"] = previous.get("machine_identifier")
            result["stale"] = True

    _cache = result
    _persist(result)
    return result


def get() -> dict[str, Any]:
    """Cached capabilities. Falls back to whatever was last persisted."""
    global _cache
    if _cache is None:
        _cache = _load_persisted() or {"plex_pass": None, "probed_at": 0, "error": "not probed yet"}
    return _cache


def is_stale() -> bool:
    return time.time() - float(get().get("probed_at") or 0) > TTL_SECONDS


def plex_pass_active() -> bool:
    """False when unknown. Callers use this to refuse an action, and refusing
    on unknown is the safe direction, because the alternative is a confusing failure
    from Plex itself."""
    return get().get("plex_pass") is True


def as_map() -> dict[str, Any]:
    """The shape the frontend consumes."""
    caps = get()
    return {
        "plex_pass": {
            "active": caps.get("plex_pass"),
            "reason": _plex_pass_reason(caps),
        },
        "server": {
            "name": caps.get("server_name"),
            "version": caps.get("server_version"),
            "machine_identifier": caps.get("machine_identifier"),
        },
        "probed_at": caps.get("probed_at"),
        "stale": caps.get("stale", False),
        "integrations": _integration_states(),
    }


def _integration_states() -> dict[str, str]:
    """Just configured or not. A reachability check would mean network calls on
    every page load, and the Settings page tests properly on demand."""
    from app.integrations import arr, notify, seerr, tmdb

    return {
        i.name: ("ok" if i.configured() else "unconfigured")
        for i in (
            arr.radarr,
            arr.sonarr,
            seerr.seerr,
            tmdb.tmdb,
            notify.apprise_notifier,
            notify.webhook_notifier,
        )
    }


def _plex_pass_reason(caps: dict[str, Any]) -> str | None:
    if caps.get("plex_pass") is True:
        return None
    if caps.get("plex_pass") is False:
        return "Requires Plex Pass. Stream termination is unavailable"
    return caps.get("error") or "Plex Pass status unknown, not probed yet"

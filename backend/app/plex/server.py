"""Talking to Plex itself, rather than through something that talks to Plex.

Tautulli is a recorder: it watches Plex and writes down what it sees, which is
why it is the only thing that has an IP address against a play from 2022. For
anything happening now, it is a second hop to ask about a thing we could ask
directly.

Measured against a real server:

    plexapi discovering the server      20,000 ms
    connecting to a known URL              209 ms
    the live sessions                        9 ms
    the libraries                           11 ms
    two hundred films, with file paths,
    sizes, codecs and external ids           91 ms

The twenty seconds is the whole reason this holds the URL rather than looking
it up. Discovery tries every address Plex advertises, including a docker bridge
and a LAN address that are unreachable from outside the house, and waits out
each one. It is worth doing once, at setup, and never again.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from app.settings_store import current

log = logging.getLogger(__name__)

CONNECT_SECONDS = 20.0
"""How long to wait for Plex. Generous: a server waking a sleeping array can
take a while, and the alternative is reporting it as down."""

REUSE_SECONDS = 300.0
"""How long a connection is kept before it is made again. Long enough that a
five second poll never reconnects, short enough that a server which moved is
picked up without a restart."""


class NotConfigured(RuntimeError):
    """No token, or no address to use it against."""


_held: dict[str, Any] = {"key": None, "server": None, "at": 0.0}
_lock = threading.Lock()


def configured() -> bool:
    settings = current()
    return bool(settings.plex_token and settings.plex_url)


def _key(settings) -> str:
    return f"{settings.plex_url}|{settings.plex_token[:8]}"


def server(fresh: bool = False):
    """The Plex server, connected and held.

    plexapi blocks, so everything here runs in a worker thread, never on the
    event loop. One connection is shared: making a new one per poll would be
    the handshake problem that made the posters slow, in a different coat.
    """
    settings = current()
    if not configured():
        raise NotConfigured("Add a Plex token and address in Settings")

    from plexapi.server import PlexServer

    key = _key(settings)
    with _lock:
        held = _held["server"]
        if (
            not fresh
            and held is not None
            and _held["key"] == key
            and time.monotonic() - float(_held["at"]) < REUSE_SECONDS
        ):
            return held
        made = PlexServer(settings.plex_url, settings.plex_token, timeout=CONNECT_SECONDS)
        _held["key"], _held["server"], _held["at"] = key, made, time.monotonic()
        return made


def forget() -> None:
    """After the address or the token changes."""
    with _lock:
        _held["key"], _held["server"], _held["at"] = None, None, 0.0


def discover() -> list[dict[str, Any]]:
    """Every server this token can reach, with an address for each.

    The one slow call, and the reason the address is stored afterwards. Local
    addresses are offered first because they are the quick ones from inside
    the house, and a relay last because it is the slow one.
    """
    settings = current()
    if not settings.plex_token:
        raise NotConfigured("Add a Plex token in Settings")

    from plexapi.myplex import MyPlexAccount

    account = MyPlexAccount(token=settings.plex_token)
    out: list[dict[str, Any]] = []
    for res in account.resources():
        if "server" not in (res.provides or ""):
            continue
        addresses = sorted(
            res.connections or [],
            key=lambda c: (bool(getattr(c, "relay", False)), not c.local),
        )
        out.append({
            "name": res.name,
            "machine_identifier": res.clientIdentifier,
            "owned": bool(res.owned),
            "addresses": [
                {"uri": c.uri, "local": bool(c.local), "relay": bool(getattr(c, "relay", False))}
                for c in addresses
            ],
        })
    return out


def reachable(url: str | None = None) -> dict[str, Any]:
    """Whether an address answers, and what is behind it.

    Used by Settings to check an address before it is saved, so somebody is
    told now rather than finding out when the next sweep fails.
    """
    settings = current()
    if not settings.plex_token:
        return {"ok": False, "error": "No Plex token"}

    from plexapi.server import PlexServer

    where = url or settings.plex_url
    if not where:
        return {"ok": False, "error": "No address"}
    started = time.monotonic()
    try:
        plex = PlexServer(where, settings.plex_token, timeout=CONNECT_SECONDS)
        return {
            "ok": True,
            "name": plex.friendlyName,
            "version": plex.version,
            "machine_identifier": plex.machineIdentifier,
            "ms": int((time.monotonic() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001 - the failure is the answer
        from app.redact import redact

        return {"ok": False, "error": redact(exc), "ms": int((time.monotonic() - started) * 1000)}

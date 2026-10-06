"""Acting on Plex itself: stopping a stream, and what the server is.

With Plex chosen as the source and no Tautulli, these are the only way a ban
or a rule can stop anything. A ban list that looks armed and stops nothing is
worse than no ban list, so they are not left on Tautulli alone.

Blocking, because plexapi is. Call them in a worker thread.
"""

from __future__ import annotations

from typing import Any


def stop(session_key: str | None, session_id: str | None, message: str) -> None:
    """End one stream with a message to the viewer.

    Plex stops a stream by its session id, which is not the session key
    everything else here uses. The id comes with the session when Plex was
    asked for it; when only the key is known it is looked up.
    """
    from app.plex.server import server

    plex = server()
    if not session_id:
        for video in plex.sessions():
            if str(getattr(video, "sessionKey", "")) == str(session_key):
                held = getattr(video, "session", None)
                held = held[0] if isinstance(held, list) and held else held
                session_id = getattr(held, "id", None)
                break
    if not session_id:
        raise RuntimeError("Plex is not playing that stream any more")
    plex.query("/status/sessions/terminate", params={"sessionId": session_id, "reason": message})


def describe() -> dict[str, Any]:
    """The server's name, version, id, and whether it has Plex Pass, which
    stopping a stream needs."""
    from app.plex.server import server

    plex = server()
    return {
        "plex_pass": bool(getattr(plex, "myPlexSubscription", False)),
        "server_name": getattr(plex, "friendlyName", None),
        "server_version": getattr(plex, "version", None),
        "machine_identifier": getattr(plex, "machineIdentifier", None),
    }

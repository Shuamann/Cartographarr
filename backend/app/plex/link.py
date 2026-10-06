"""Getting a Plex token without asking for a password.

Plex's own way of linking a device: this app asks plex.tv for a short code,
the person types it at plex.tv/link while signed in there, and plex.tv hands
this app a token for their account. The password never passes through here,
and the token never goes back to the browser: it is written straight into the
settings store, which lives in the data directory.

plexapi's MyPlexPinLogin does the talking. It blocks, so every call into it
runs in a worker thread, and the page polls rather than this holding a
request open while somebody goes to find their phone.

One link at a time is plenty. Setup is done by one admin, once.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any

LINK_URL = "https://plex.tv/link"
LINK_SECONDS = 15 * 60
"""How long a code is good for. plex.tv lets a PIN lapse after about this
long, and asking again after that is cheaper than explaining an expiry."""


@dataclass
class _Link:
    id: str
    login: Any
    code: str
    started: float


_held: dict[str, _Link] = {}
_lock = threading.Lock()


class Expired(LookupError):
    """The code lapsed, or this server restarted since it was shown."""


def _headers() -> dict[str, str]:
    from app.auth.plex_signin import PRODUCT, client_identifier

    # The same identity as signing in with Plex, so the person's list of
    # authorised devices at plex.tv shows this install once, by its name.
    return {
        "X-Plex-Product": PRODUCT,
        "X-Plex-Device-Name": PRODUCT,
        "X-Plex-Client-Identifier": client_identifier(),
    }


def start() -> dict[str, Any]:
    """A new code to type at plex.tv/link. Blocking."""
    from plexapi.myplex import MyPlexPinLogin

    login = MyPlexPinLogin(headers=_headers())
    code = login.pin
    link = _Link(id=secrets.token_urlsafe(16), login=login, code=str(code), started=time.time())
    with _lock:
        _held.clear()
        _held[link.id] = link
    return {"id": link.id, "code": link.code, "url": LINK_URL, "expires_in": LINK_SECONDS}


def check(link_id: str) -> str | None:
    """The token once the code has been entered, None until then. Blocking.

    Raises Expired when the code has lapsed or is not one this server gave
    out, so the page can offer a fresh one rather than waiting for ever.
    """
    with _lock:
        link = _held.get(link_id)
    if link is None or time.time() - link.started > LINK_SECONDS:
        forget(link_id)
        raise Expired("That code has expired. Ask for a new one.")
    if link.login.checkLogin():
        forget(link_id)
        return link.login.token
    if link.login.expired:
        forget(link_id)
        raise Expired("Plex says that code has expired. Ask for a new one.")
    return None


def forget(link_id: str) -> None:
    with _lock:
        _held.pop(link_id, None)

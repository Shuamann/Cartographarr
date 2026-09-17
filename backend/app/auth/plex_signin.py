"""Sign in with Plex.

Plex's PIN flow, the way Overseerr and Tautulli do it:

1. The server asks plex.tv for a PIN and sends the browser to app.plex.tv
   with that PIN's code. The PIN is remembered here against a random state
   value that only this browser holds, in a short-lived cookie.
2. The person signs in at Plex, which sends them back to this app.
3. The server asks plex.tv whether the PIN was claimed. If so it has a Plex
   token for that person, uses it once to read who they are, and forgets it.

Who that Plex account may be here is decided by Cartographarr's own accounts:
the account linked to that Plex user, or a viewer account with the same
email. Usernames are never matched, and an admin must be linked explicitly. With
new accounts allowed, someone the server is shared with (per Tautulli) gets a
viewer account the first time. Nobody becomes an admin through Plex.
"""

from __future__ import annotations

import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AppUser, SyncState, User

PLEX_API = "https://plex.tv/api/v2"
PRODUCT = "Cartographarr"
PIN_SECONDS = 600
STATE_COOKIE = "cartographarr_plex_state"


@dataclass
class Pending:
    pin_id: int
    code: str
    created: float


_pending: dict[str, Pending] = {}


def client_identifier() -> str:
    """A stable id for this install, which Plex shows on the sign-in page and
    lists under the person's authorised devices."""
    key = "plex_client_identifier"
    with session_scope() as db:
        row = db.get(SyncState, key)
        if row is not None and row.value:
            return row.value
        value = f"cartographarr-{uuid.uuid4()}"
        db.merge(SyncState(key=key, value=value))
        return value


def _headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "X-Plex-Product": PRODUCT,
        "X-Plex-Client-Identifier": client_identifier(),
    }
    if token:
        headers["X-Plex-Token"] = token
    return headers


async def plex_request(method: str, path: str, token: str | None = None, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.request(method, f"{PLEX_API}{path}", headers=_headers(token), params=params)
        response.raise_for_status()
        return response.json()


def _prune(now: float) -> None:
    for state in [s for s, p in _pending.items() if now - p.created > PIN_SECONDS]:
        _pending.pop(state, None)


def safe_origin(origin: str) -> str | None:
    """The app's own address to come back to, or None if it is not one."""
    parsed = urlparse(origin or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path not in ("", "/"):
        return None
    if parsed.query or parsed.fragment or "@" in parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


async def start(origin: str) -> tuple[str, str]:
    """Create a PIN. Returns (state for the cookie, URL to send the browser to)."""
    now = time.time()
    _prune(now)
    pin = await plex_request("POST", "/pins", params={"strong": "true"})
    state = secrets.token_urlsafe(32)
    _pending[state] = Pending(pin_id=int(pin["id"]), code=str(pin["code"]), created=now)
    query = urlencode({
        "clientID": client_identifier(),
        "code": pin["code"],
        "context[device][product]": PRODUCT,
        "forwardUrl": f"{origin}/?plex_login=1",
    })
    return state, f"https://app.plex.tv/auth#?{query}"


class NotYet(Exception):
    pass


async def finish(state: str | None) -> dict[str, Any]:
    """The Plex account behind a claimed PIN. Raises NotYet if the person has
    not finished at Plex, LookupError if the state is unknown or expired."""
    now = time.time()
    _prune(now)
    pending = _pending.get(state or "")
    if pending is None:
        raise LookupError("That Plex sign-in has expired. Start again.")
    pin = await plex_request("GET", f"/pins/{pending.pin_id}")
    token = pin.get("authToken")
    if not token:
        raise NotYet("Plex has not confirmed the sign-in yet")
    _pending.pop(state, None)
    account = await plex_request("GET", "/user", token=token)
    # The token is not kept: it was only needed to learn who this is.
    return {
        "id": int(account["id"]) if account.get("id") is not None else None,
        "username": account.get("username") or account.get("title"),
        "email": account.get("email"),
    }


def account_for(plex: dict[str, Any], allow_new_viewers: bool) -> tuple[AppUser | None, str]:
    """The Cartographarr account a Plex account signs in as, and why not if
    none."""
    plex_id = plex.get("id")
    email = str(plex.get("email") or "").strip().lower()
    with session_scope() as db:
        user = None
        if plex_id is not None:
            user = db.execute(select(AppUser).where(AppUser.plex_user_id == plex_id)).scalars().first()
        # Never by username: anyone can register a Plex account called "admin".
        # By email only for viewers, since Plex vouches for the email; an admin
        # signs in with Plex only once explicitly linked to that Plex account.
        if user is None and email:
            user = db.execute(
                select(AppUser).where(func.lower(AppUser.email) == email, AppUser.role != "admin")
            ).scalars().first()
        if user is not None:
            if not user.is_active:
                return None, "That account is disabled"
            if user.plex_user_id is None and plex_id is not None:
                user.plex_user_id = plex_id
            db.flush()
            db.expunge(user)
            return user, ""

        if not allow_new_viewers or plex_id is None:
            return None, "There is no Cartographarr account for this Plex account"
        shared = db.get(User, plex_id)
        if shared is None or shared.deleted_in_tautulli:
            return None, "This Plex account does not have access to this server"
        base = (plex.get("username") or f"plex{plex_id}")[:56]
        username, n = base, 1
        while db.execute(select(AppUser.id).where(func.lower(AppUser.username) == username.lower())).first():
            n += 1
            username = f"{base}{n}"
        from datetime import UTC, datetime

        user = AppUser(
            username=username, email=plex.get("email"), role="viewer", password_hash=None,
            auth_source="plex", is_active=True, created_at=datetime.now(UTC), plex_user_id=plex_id,
            # Someone who let themselves in sees the server with other people
            # anonymised, whatever the server-wide setting; an admin can widen it.
            privacy="anonymised",
        )
        db.add(user)
        db.flush()
        db.expunge(user)
        return user, "created"

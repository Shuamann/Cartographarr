"""Who is making this request, and are they allowed to.

Two ways in: a session cookie from a local login, or a header from a reverse
proxy that has already authenticated the person. The proxy path is only
consulted when the request actually came from an address you listed, because
otherwise anyone who can reach the app can claim to be anyone.
"""

from __future__ import annotations

import ipaddress
import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select

from app.auth.security import hash_token
from app.db import session_scope
from app.models import AppSession, AppUser
from app.settings_store import current

log = logging.getLogger(__name__)


def has_any_user() -> bool:
    with session_scope() as db:
        return db.execute(select(AppUser.id).limit(1)).first() is not None


def _is_trusted_proxy(client: str | None) -> bool:
    """Whether this address is one of the proxies we believe."""
    settings = current()
    if not client or not settings.trusted_proxy_ips:
        return False
    try:
        address = ipaddress.ip_address(client)
    except ValueError:
        return False

    for entry in settings.trusted_proxy_ips:
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            log.warning("Ignoring unparseable trusted proxy entry: %s", entry)
    return False


def client_address(request: Request) -> str:
    """Who is actually calling, through any proxy we trust.

    Behind a reverse proxy every request arrives from the proxy, so counting
    failed sign-ins per address counted the whole internet as one caller and
    the limit protected nobody. Where the immediate caller is a proxy on the
    trusted list, the forwarded chain is read from the right, past any other
    trusted proxy, to the first address we did not put there ourselves. An
    untrusted caller's header is ignored entirely, because anyone can write
    one.
    """
    peer = request.client.host if request.client else "unknown"
    if not _is_trusted_proxy(peer):
        return peer
    chain = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    for candidate in reversed(chain):
        if not _is_trusted_proxy(candidate):
            return candidate
    return peer


def _client_is_trusted(request: Request) -> bool:
    settings = current()
    if not settings.auth_proxy_enabled:
        return False
    return _is_trusted_proxy(request.client.host if request.client else None)


def _user_from_proxy(request: Request) -> AppUser | None:
    settings = current()
    if not _client_is_trusted(request):
        return None

    name = request.headers.get(settings.proxy_user_header)
    if not name:
        return None
    email = request.headers.get(settings.proxy_email_header)

    with session_scope() as db:
        user = db.execute(select(AppUser).where(AppUser.username == name)).scalar_one_or_none()
        if user is None:
            # First time the proxy vouches for this person. Provisioning them
            # at the default role beats a 403 they cannot act on.
            user = AppUser(
                username=name,
                email=email,
                role=settings.proxy_default_role,
                auth_source="proxy",
                created_at=datetime.now(UTC),
            )
            db.add(user)
            db.flush()
        if not user.is_active:
            return None
        user.last_login = datetime.now(UTC)
        db.expunge(user)
        return user


def _user_from_cookie(request: Request) -> AppUser | None:
    settings = current()
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None

    now = datetime.now(UTC)
    with session_scope() as db:
        session = db.get(AppSession, hash_token(token))
        if session is None:
            return None
        expires = session.expires_at
        if expires is not None and expires.replace(tzinfo=expires.tzinfo or UTC) < now:
            db.delete(session)
            return None

        user = db.get(AppUser, session.app_user_id)
        if user is None or not user.is_active:
            return None
        db.expunge(user)
        return user


def optional_user(request: Request) -> AppUser | None:
    return _user_from_cookie(request) or _user_from_proxy(request)


def require_user(request: Request) -> AppUser:
    user = optional_user(request)
    if user is None:
        raise HTTPException(401, "Sign in to continue")
    return user


def require_admin(request: Request) -> AppUser:
    user = require_user(request)
    if user.role != "admin":
        raise HTTPException(403, "This needs an admin account")
    return user


def purge_expired_sessions() -> int:
    with session_scope() as db:
        result = db.execute(
            delete(AppSession).where(AppSession.expires_at < datetime.now(UTC))
        )
        return result.rowcount or 0


CurrentUser = Annotated[AppUser, Depends(require_user)]
AdminUser = Annotated[AppUser, Depends(require_admin)]

"""Sign in, sign out, and account management."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request, Response
from sqlalchemy import delete, func, select

from app import audit
from app.auth.deps import AdminUser, CurrentUser, has_any_user, optional_user
from app.auth.security import (
    expiry,
    hash_password,
    new_session_token,
    hash_token,
    password_problem,
    verify_password,
)
from app.db import session_scope
from app.models import AppSession, AppUser
from app.settings_store import current

router = APIRouter(prefix="/api/auth")

ROLES = {"admin", "viewer"}


def _public(user: AppUser) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "auth_source": user.auth_source,
        "is_active": user.is_active,
        "last_login": user.last_login,
    }


def _start_session(response: Response, user: AppUser) -> None:
    settings = current()
    token, digest = new_session_token()
    with session_scope() as db:
        db.add(
            AppSession(
                token_hash=digest,
                app_user_id=user.id,
                created_at=datetime.now(UTC),
                expires_at=expiry(settings.session_ttl_hours),
            )
        )
        stored = db.get(AppUser, user.id)
        if stored:
            stored.last_login = datetime.now(UTC)

    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )


@router.get("/state")
def state(request: Request) -> dict:
    """What the login screen needs before anyone has signed in.

    Deliberately says whether any account exists, because the UI has to know
    whether to show "create the first admin" or "sign in". It does not reveal
    usernames.
    """
    user = optional_user(request)
    settings = current()
    return {
        "needs_claim": not has_any_user(),
        "authenticated": user is not None,
        "user": _public(user) if user else None,
        "proxy_enabled": settings.auth_proxy_enabled,
    }


@router.get("/backdrops")
async def backdrops() -> dict:
    """Artwork for the sign-in page.

    Public on purpose, because the sign-in page is. It returns only this
    week's trending films from TMDB, which is global and says nothing about
    this server. Library artwork must never be served here: it would tell
    anyone who loads the page what is in the library.
    """
    from app.integrations.tmdb import tmdb

    return {"images": await tmdb.trending_backdrops()}


@router.post("/claim")
def claim(
    response: Response,
    username: str = Body(...),
    password: str = Body(...),
    email: str = Body(""),
) -> dict:
    """Create the first admin account.

    Open only while no account exists, the way Radarr and Seerr do it. Once
    one is claimed this is closed for good.
    """
    if has_any_user():
        raise HTTPException(409, "An account already exists. Sign in instead.")

    username = username.strip()
    if not username:
        raise HTTPException(400, "Pick a username")
    if problem := password_problem(password):
        raise HTTPException(400, problem)

    with session_scope() as db:
        user = AppUser(
            username=username,
            email=email.strip() or None,
            role="admin",
            password_hash=hash_password(password),
            auth_source="local",
            created_at=datetime.now(UTC),
        )
        db.add(user)
        db.flush()
        db.expunge(user)

    audit.record(user, "account.claim", f"Created the first admin account, {user.username}")
    _start_session(response, user)
    return {"user": _public(user)}


@router.post("/login")
def login(
    response: Response, username: str = Body(...), password: str = Body(...)
) -> dict:
    with session_scope() as db:
        user = db.execute(
            select(AppUser).where(AppUser.username == username.strip())
        ).scalar_one_or_none()
        if user is not None:
            db.expunge(user)

    # Same answer either way, so this cannot be used to enumerate accounts.
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        # The typed name is recorded, not the password, so repeated guessing
        # against one account is visible.
        audit.record(
            None, "auth.failed", f"Failed sign in as {username.strip()[:64]!r}",
            actor=username.strip()[:64] or None, result="failed",
        )
        raise HTTPException(401, "That username and password do not match")

    audit.record(user, "auth.login", f"{user.username} signed in")
    _start_session(response, user)
    return {"user": _public(user)}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    settings = current()
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        with session_scope() as db:
            session = db.get(AppSession, hash_token(token))
            if session:
                db.delete(session)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser) -> dict:
    return _public(user)


@router.post("/me/password")
def change_password(
    user: CurrentUser,
    current_password: str = Body(...),
    new_password: str = Body(...),
) -> dict:
    if user.auth_source != "local":
        raise HTTPException(400, "This account signs in through the reverse proxy")
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(401, "Current password is wrong")
    if problem := password_problem(new_password):
        raise HTTPException(400, problem)

    with session_scope() as db:
        stored = db.get(AppUser, user.id)
        stored.password_hash = hash_password(new_password)
        # Changing a password should end sessions elsewhere.
        db.execute(delete(AppSession).where(AppSession.app_user_id == user.id))
    audit.record(user, "account.password", f"{user.username} changed their password")
    return {"ok": True, "signed_out_everywhere": True}


# ---- user management, admin only ------------------------------------------

@router.get("/users")
def list_users(_: AdminUser) -> list[dict]:
    with session_scope() as db:
        return [_public(u) for u in db.execute(select(AppUser).order_by(AppUser.id)).scalars()]


@router.post("/users")
def create_user(
    admin: AdminUser,
    username: str = Body(...),
    password: str = Body(...),
    role: str = Body("viewer"),
    email: str = Body(""),
) -> dict:
    if role not in ROLES:
        raise HTTPException(400, f"Role must be one of: {', '.join(sorted(ROLES))}")
    if problem := password_problem(password):
        raise HTTPException(400, problem)

    with session_scope() as db:
        if db.execute(select(AppUser).where(AppUser.username == username.strip())).first():
            raise HTTPException(409, "That username is taken")
        user = AppUser(
            username=username.strip(),
            email=email.strip() or None,
            role=role,
            password_hash=hash_password(password),
            auth_source="local",
            created_at=datetime.now(UTC),
        )
        db.add(user)
        db.flush()
        db.expunge(user)
    audit.record(
        admin, "account.create", f"Added account {user.username} as {user.role}",
        target=str(user.id),
    )
    return _public(user)


@router.put("/users/{user_id}")
def update_user(user_id: int, admin: AdminUser, values: dict[str, Any] = Body(...)) -> dict:
    allowed = {"role", "email", "is_active", "password"}
    unknown = set(values) - allowed
    if unknown:
        raise HTTPException(400, f"Cannot change: {', '.join(sorted(unknown))}")
    if "role" in values and values["role"] not in ROLES:
        raise HTTPException(400, f"Role must be one of: {', '.join(sorted(ROLES))}")

    with session_scope() as db:
        user = db.get(AppUser, user_id)
        if user is None:
            raise HTTPException(404, "No such account")

        # Locking yourself out is the one mistake with no way back through the
        # UI, so it is refused rather than confirmed.
        losing_admin = (values.get("role") and values["role"] != "admin") or (
            values.get("is_active") is False
        )
        if user.id == admin.id and losing_admin:
            raise HTTPException(400, "You cannot remove your own admin access")
        if losing_admin and user.role == "admin":
            remaining = db.execute(
                select(func.count())
                .select_from(AppUser)
                .where(AppUser.role == "admin", AppUser.is_active.is_(True), AppUser.id != user.id)
            ).scalar_one()
            if remaining == 0:
                raise HTTPException(400, "That is the last admin account")

        if "password" in values:
            if problem := password_problem(values["password"]):
                raise HTTPException(400, problem)
            user.password_hash = hash_password(values["password"])
            db.execute(delete(AppSession).where(AppSession.app_user_id == user.id))
        before = {f: getattr(user, f) for f in ("role", "email", "is_active")}
        for field in ("role", "email", "is_active"):
            if field in values:
                setattr(user, field, values[field])
        db.flush()
        db.expunge(user)

    parts = []
    if "role" in values and values["role"] != before["role"]:
        parts.append(f"role {before['role']} to {values['role']}")
    if "is_active" in values and values["is_active"] != before["is_active"]:
        parts.append("enabled" if values["is_active"] else "disabled")
    if "email" in values and values["email"] != before["email"]:
        parts.append("email")
    if "password" in values:
        parts.append("reset password")
    audit.record(
        admin, "account.update",
        f"Changed account {user.username}: {', '.join(parts) or 'no changes'}",
        target=str(user_id),
        detail={k: {"before": before[k], "after": values[k]} for k in before if k in values},
    )
    return _public(user)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin: AdminUser) -> dict:
    if user_id == admin.id:
        raise HTTPException(400, "You cannot delete the account you are signed in with")

    with session_scope() as db:
        user = db.get(AppUser, user_id)
        if user is None:
            raise HTTPException(404, "No such account")
        if user.role == "admin":
            remaining = db.execute(
                select(func.count())
                .select_from(AppUser)
                .where(AppUser.role == "admin", AppUser.is_active.is_(True), AppUser.id != user_id)
            ).scalar_one()
            if remaining == 0:
                raise HTTPException(400, "That is the last admin account")
        name = user.username
        db.execute(delete(AppSession).where(AppSession.app_user_id == user_id))
        db.delete(user)
    audit.record(admin, "account.delete", f"Deleted account {name}", target=str(user_id))
    return {"deleted": user_id}

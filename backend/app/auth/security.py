"""Password hashing and session tokens.

Argon2 for passwords, because hand-rolled hashing is the one place where being
clever is always wrong. Session tokens are random and stored as a SHA-256
digest, so a leaked database does not hand over live sessions.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_problem(password: str) -> str | None:
    """Return why a password is unacceptable, or None if it is fine.

    Length only. Composition rules push people towards "Password1!" and this
    is a self-hosted app behind a LAN or a proxy, not a public signup form.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    return None


def new_session_token() -> tuple[str, str]:
    """Return (token to send to the browser, digest to store)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def expiry(hours: int) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)

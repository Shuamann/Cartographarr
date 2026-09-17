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


# Checked against when the username does not exist, so a wrong username
# takes as long to refuse as a wrong password and replies cannot be timed to
# find real accounts.
_DUMMY_HASH = _hasher.hash("not a real password, only for timing")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        try:
            _hasher.verify(_DUMMY_HASH, password)
        except (VerifyMismatchError, InvalidHashError):
            pass
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


# ---- repeated failures ----------------------------------------------------------

class LoginThrottle:
    """Failed sign-ins, per username and per address, in memory.

    Five failures for one username, or thirty from one address, within fifteen
    minutes locks further attempts until the window moves on. Per address is
    loose on purpose: behind a reverse proxy everyone can share one.
    """

    WINDOW = 15 * 60
    PER_USER = 5
    PER_ADDRESS = 30

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str, now: float) -> list[float]:
        kept = [t for t in self._failures.get(key, []) if now - t < self.WINDOW]
        if kept:
            self._failures[key] = kept
        else:
            self._failures.pop(key, None)
        return kept

    def blocked(self, username: str, address: str, now: float) -> int:
        """Seconds until another try is allowed, or 0."""
        waits = []
        for key, limit in ((f"user:{username.lower()}", self.PER_USER), (f"addr:{address}", self.PER_ADDRESS)):
            recent = self._recent(key, now)
            if len(recent) >= limit:
                waits.append(int(self.WINDOW - (now - recent[-limit])) + 1)
        return max(waits, default=0)

    def failed(self, username: str, address: str, now: float) -> None:
        for key in (f"user:{username.lower()}", f"addr:{address}"):
            self._failures.setdefault(key, []).append(now)

    def succeeded(self, username: str) -> None:
        self._failures.pop(f"user:{username.lower()}", None)


login_throttle = LoginThrottle()

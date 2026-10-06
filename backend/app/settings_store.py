"""Effective settings: environment first, UI-saved values second.

The *arr / Unraid pattern. Set something as a docker env var and it wins and
shows up read-only in the UI ("set by environment"); leave it unset and the UI
owns it and persists to the database.

Resolution leans on pydantic rather than a hand-rolled layer:
`Settings().model_fields_set` is exactly the set of fields an env var or .env
supplied, which is exactly the set the UI must not touch.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from app.config import Settings
from app.db import init_db, session_scope
from app.models import Setting

FROZEN = {"data_dir"}
"""Not editable at runtime at any price: the DB we'd save into lives there."""

_cache: tuple[Settings, frozenset[str]] | None = None


def load() -> tuple[Settings, frozenset[str]]:
    """Return (effective settings, keys locked by the environment)."""
    from_env = Settings()
    locked = frozenset(from_env.model_fields_set) | FROZEN

    init_db()  # idempotent; load() is the first thing to touch the DB
    with session_scope() as session:
        saved = {
            row.key: row.value
            for row in session.query(Setting).all()
            if row.key not in locked
        }

    # Init kwargs outrank env in pydantic-settings, which is why locked keys
    # are filtered out above rather than merged and hoped over.
    return Settings(**saved), locked


_trial: ContextVar[Settings | None] = ContextVar("settings_trial", default=None)


@contextmanager
def trial(values: dict[str, Any]) -> Iterator[Settings]:
    """Settings as they would be with these values, for this task only.

    Lets Test check what is typed on the page before it is saved. Scoped to the
    current task through a ContextVar, so nothing else running at the same
    time sees the unsaved values, and it carries into asyncio.to_thread.
    Environment-locked keys are ignored, as they would be on save.
    """
    locked = locked_keys()
    wanted = {k: v for k, v in values.items() if k in Settings.model_fields and k not in locked}
    merged = Settings(**{**current().model_dump(), **wanted})
    token = _trial.set(merged)
    try:
        yield merged
    finally:
        _trial.reset(token)


def current() -> Settings:
    global _cache
    tried = _trial.get()
    if tried is not None:
        return tried
    if _cache is None:
        _cache = load()
    return _cache[0]


def locked_keys() -> frozenset[str]:
    global _cache
    if _cache is None:
        _cache = load()
    return _cache[1]


def save(values: dict[str, Any]) -> Settings:
    """Persist UI-supplied settings. Environment-locked keys are refused."""
    locked = locked_keys()
    unknown = set(values) - set(Settings.model_fields)
    if unknown:
        raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}")
    refused = set(values) & locked
    if refused:
        raise ValueError(f"Set by environment, not editable here: {', '.join(sorted(refused))}")

    Settings(**values)  # validate before writing

    with session_scope() as session:
        for key, value in values.items():
            session.merge(Setting(key=key, value=str(value)))

    invalidate()
    return current()


def invalidate() -> None:
    global _cache
    _cache = None


TAUTULLI = ("tautulli_url", "tautulli_api_key")
PLEX = ("plex_token", "plex_url")


def tautulli_configured() -> bool:
    """Whether Tautulli can be asked anything. Only what Tautulli alone can
    answer should check this: plays from before this app was watching, and the
    users and libraries that are not read from Plex yet."""
    settings = current()
    return all(getattr(settings, name) for name in TAUTULLI)


def plex_configured() -> bool:
    settings = current()
    return all(getattr(settings, name) for name in PLEX)


def wants_plex() -> bool:
    """Whether either source has been set to Plex, which setup does when Plex
    is the answer to its first question."""
    settings = current()
    return settings.activity_source == "plex" or settings.library_source == "plex"


def missing_required() -> list[str]:
    """Settings with no value yet. Non-empty means the app is unconfigured and
    should show first-run setup rather than an empty dashboard.

    One working connection is enough, either one. An install that already
    reads from Tautulli is never sent back to setup for choosing Plex as a
    source and not finishing it: that is a gap to show in Settings, not a
    reason to lock somebody out of their own install.
    """
    if tautulli_configured() or plex_configured():
        return []
    settings = current()
    wanted = PLEX if wants_plex() else TAUTULLI
    return [name for name in wanted if not getattr(settings, name)]


def is_configured() -> bool:
    return not missing_required()


def describe() -> list[dict[str, Any]]:
    """Every setting with its value and where it came from. Powers the UI."""
    settings, locked = current(), locked_keys()
    return [
        {
            "key": name,
            "value": getattr(settings, name),
            "source": "environment" if name in locked else "ui",
            "editable": name not in locked,
        }
        for name in Settings.model_fields
    ]

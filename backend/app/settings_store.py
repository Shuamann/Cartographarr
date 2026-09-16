"""Effective settings: environment first, UI-saved values second.

The *arr / Unraid pattern. Set something as a docker env var and it wins and
shows up read-only in the UI ("set by environment"); leave it unset and the UI
owns it and persists to the database.

Resolution leans on pydantic rather than a hand-rolled layer:
`Settings().model_fields_set` is exactly the set of fields an env var or .env
supplied, which is exactly the set the UI must not touch.
"""

from __future__ import annotations

from typing import Any

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


def current() -> Settings:
    global _cache
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


REQUIRED = ("tautulli_url", "tautulli_api_key")


def missing_required() -> list[str]:
    """Settings with no value yet. Non-empty means the app is unconfigured and
    should show first-run setup rather than an empty dashboard."""
    settings = current()
    return [name for name in REQUIRED if not getattr(settings, name)]


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

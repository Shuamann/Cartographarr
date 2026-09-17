"""One way to write to the audit log.

A plain sentence is stored alongside the structured detail, so the log reads
the same even after the code that wrote an entry has changed shape.

Secret values never go in. Changed settings record which keys changed, and
for anything that looks like a credential, only that it changed.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.db import session_scope
from app.redact import redact
from app.models import AppUser, AuditLog

log = logging.getLogger(__name__)

SECRET_HINT = ("key", "token", "secret", "password")

# Settings whose value is a URL that usually carries a credential: a Discord
# webhook id and token, an SMTP password, a push token.
SECRET_URLS = frozenset({"apprise_urls", "webhook_url", "uptime_kuma_push_url", "viewer_message_url"})


def is_secret(key: str) -> bool:
    return key in SECRET_URLS or any(hint in key for hint in SECRET_HINT)


def record(
    who: AppUser | None,
    action: str,
    summary: str,
    *,
    target: str | None = None,
    detail: dict[str, Any] | None = None,
    result: str = "ok",
    actor: str | None = None,
) -> None:
    """Write one entry. Never raises: a failed audit write must not undo the
    change it describes, so it is logged and swallowed."""
    try:
        with session_scope() as db:
            db.add(
                AuditLog(
                    app_user_id=who.id if who else None,
                    actor=actor or (who.username if who else None),
                    action=action,
                    target=target,
                    summary=redact(summary),
                    payload=json.dumps(detail, default=str) if detail else None,
                    result=redact(result),
                    created_at=datetime.now(UTC),
                )
            )
    except Exception:  # noqa: BLE001
        log.exception("could not write audit entry for %s", action)

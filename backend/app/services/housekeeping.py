"""Throwing away what is old enough to throw away.

Four tables grew forever: the streams live activity recorded, the buffering
events during them, the audit log and the enforcement log. Two others already
had this, bandwidth samples for a year and task runs capped per task, so the
pattern existed and these were simply never given it.

Nothing here is urgent at the volumes this app sees. It is written down now
because the kind of thing that is noticed two years late is the kind of thing
to do while it is still cheap, and because the alternative, a database that
quietly becomes slow, gives no warning at all.

How long to keep is a setting rather than a number in the code, because the
reports can be asked for any window up to ten years and somebody who throws
away two year old streams should have said so rather than found out.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

log = logging.getLogger(__name__)


def _older_than(db, model, column, cutoff: datetime) -> int:
    result = db.execute(delete(model).where(column < cutoff))
    return result.rowcount or 0


def prune() -> dict[str, int]:
    """Drop what is past its keeping. Returns what went, by table."""
    from app.db import session_scope
    from app.models import AuditLog, EnforcementLog, StreamEvent, StreamSession
    from app.services import streams
    from app.settings_store import current

    settings = current()
    now = datetime.now(UTC)
    gone: dict[str, int] = {}

    # A stream and the buffering during it are one record in two tables, so
    # they keep and go together. Dropping the events alone would leave streams
    # that look as though they played cleanly.
    if settings.keep_streams_days:
        cutoff = now - timedelta(days=settings.keep_streams_days)
        with session_scope() as db:
            gone["stream_sessions"] = _older_than(db, StreamSession, StreamSession.started_at, cutoff)
            gone["stream_events"] = _older_than(db, StreamEvent, StreamEvent.started_at, cutoff)

    # The two logs are a different kind of thing: a record of what was done
    # rather than of what was watched, and worth keeping longer than it is
    # worth reporting on.
    if settings.keep_logs_days:
        cutoff = now - timedelta(days=settings.keep_logs_days)
        with session_scope() as db:
            gone["audit_log"] = _older_than(db, AuditLog, AuditLog.created_at, cutoff)
            gone["enforcement_log"] = _older_than(db, EnforcementLog, EnforcementLog.acted_at, cutoff)

    gone["bandwidth_samples"] = streams.prune()
    dropped = {table: n for table, n in gone.items() if n}
    if dropped:
        log.info("pruned %s", ", ".join(f"{n} from {table}" for table, n in dropped.items()))
    return gone

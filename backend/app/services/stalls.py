"""Is it me or them? A likely cause for each buffering stall.

One stall on its own says little. Set against every other stall it says a
lot:

- **upload**: the server's upload was nearly full at the time (needs the
  upload capacity setting)
- **server**: someone else stalled at the same moment, so the problem was on
  the server's side or its connection, not one viewer's
- **file**: several people have stalled on this same title, so the file is
  the common factor
- **viewer**: this viewer stalls across many different titles while others
  watching at the time do not, so their device or connection is the common
  factor
- **one_off**: none of the above, yet

Causes are worked out again for recent stalls on every sync, since a stall
that looked like a one-off can turn into a pattern a week later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

CAUSES: dict[str, str] = {
    "upload": "Server upload nearly full",
    "server": "Server side, others stalled too",
    "file": "This file, others stall on it",
    "viewer": "Viewer's device or connection",
    "one_off": "One-off so far",
}

OVERLAP = timedelta(seconds=90)
FILE_WINDOW = timedelta(days=60)
VIEWER_WINDOW = timedelta(days=14)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def classify(db: Session, event: Any, capacity_mbps: float = 0, upload_percent: int = 90) -> tuple[str, str]:
    """The likely cause of one stall, and a sentence saying why."""
    from app.models import BandwidthSample, StreamEvent

    start = _aware(event.started_at) or datetime.now(UTC)
    end = _aware(event.ended_at) or start

    if capacity_mbps > 0:
        lo, hi = int((start - OVERLAP).timestamp()), int((end + OVERLAP).timestamp())
        peak = db.execute(
            select(func.max(BandwidthSample.wan_kbps)).where(BandwidthSample.minute.between(lo // 60 * 60, hi))
        ).scalar()
        if peak and peak / 1000 >= capacity_mbps * upload_percent / 100:
            return "upload", f"Upload peaked at {peak / 1000:.1f} of {capacity_mbps:g} Mbps around then."

    others_at_once = db.execute(
        select(func.count(func.distinct(StreamEvent.user_id))).where(
            StreamEvent.id != event.id,
            StreamEvent.user_id != event.user_id,
            StreamEvent.started_at <= end + OVERLAP,
            StreamEvent.ended_at >= start - OVERLAP,
        )
    ).scalar() or 0
    if others_at_once:
        people = "person" if others_at_once == 1 else "people"
        return "server", f"{others_at_once} other {people} stalled within 90 seconds."

    if event.rating_key is not None:
        others_on_file = db.execute(
            select(func.count(func.distinct(StreamEvent.user_id))).where(
                StreamEvent.rating_key == event.rating_key,
                StreamEvent.user_id != event.user_id,
                StreamEvent.started_at >= start - FILE_WINDOW,
            )
        ).scalar() or 0
        if others_on_file >= 1:
            people = "person has" if others_on_file == 1 else "people have"
            return "file", f"{others_on_file} other {people} stalled on this title in the last 60 days."

    if event.user_id is not None:
        titles = db.execute(
            select(func.count(func.distinct(StreamEvent.rating_key))).where(
                StreamEvent.user_id == event.user_id,
                StreamEvent.started_at >= start - VIEWER_WINDOW,
                StreamEvent.started_at <= end + VIEWER_WINDOW,
            )
        ).scalar() or 0
        if titles >= 3:
            return "viewer", f"Stalled on {titles} different titles within two weeks, with nobody else stalling alongside."

    return "one_off", "No pattern yet."


def reclassify(days: int = 14) -> int:
    """Work causes out again for recent stalls. Returns how many changed."""
    from app.db import session_scope
    from app.models import StreamEvent
    from app.settings_store import current

    settings = current()
    capacity = float(getattr(settings, "upload_capacity_mbps", 0) or 0)
    percent = int(getattr(settings, "upload_alert_percent", 90) or 90)
    since = datetime.now(UTC) - timedelta(days=days)
    changed = 0
    with session_scope() as db:
        for event in db.execute(select(StreamEvent).where(StreamEvent.started_at >= since)).scalars():
            cause, detail = classify(db, event, capacity, percent)
            if (event.cause, event.cause_detail) != (cause, detail):
                event.cause, event.cause_detail = cause, detail
                changed += 1
    return changed

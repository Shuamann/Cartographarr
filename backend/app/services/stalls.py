"""Is it me or them? A likely cause for each buffering stall.

One stall on its own says little. Set against every other stall it says a
lot:

- **upload**: the server's upload was nearly full at the time (needs the
  upload capacity setting)
- **server**: someone else stalled at the same moment, so the problem was on
  the server's side or its connection, not one viewer's
- **file**: several people have stalled on this same title, so the file is
  the common factor
- **stream**: this one stream stalled again and again in a single sitting,
  which is a stream that could not be kept going rather than a coincidence
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
    "stream": "One stream that kept stalling",
    "viewer": "Viewer's device or connection",
    "one_off": "One-off so far",
}

SAME_STREAM = 3
"""Stalls in one sitting before it stops being bad luck. Two can be a pair of
skips either side of an advert break; three and up is a stream that is not
being kept going."""

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

    # One stream stalling over and over is the commonest shape of all, and
    # calling each of those a one-off says the opposite of what happened.
    if event.session_key:
        same_stream = db.execute(
            select(func.count()).select_from(StreamEvent).where(
                StreamEvent.session_key == event.session_key,
                StreamEvent.kind == event.kind,
                StreamEvent.user_id == event.user_id,
            )
        ).scalar() or 0
        if same_stream >= SAME_STREAM:
            return "stream", f"This one stream stalled {same_stream} times in a sitting."

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
    from app.services.streams import upload_capacity

    capacity, _ = upload_capacity()
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


# ---- stalls from before seeks were excluded --------------------------------

SEEK_FILTERING_SINCE = datetime(2026, 9, 17, tzinfo=UTC)
"""When this app started telling a stall from a skip.

Before that, jumping forward in a film and reaching the end of an episode both
looked like buffering, so anything recorded earlier is a mix of real stalls and
neither of those. The poll by poll positions that would tell them apart were
never kept, so they cannot be sorted out now: they can only be kept, knowing
they flatter nobody, or forgotten in one go.
"""


def unfiltered(db) -> tuple[int, datetime | None]:
    """How many stalls predate the filtering, and the newest of them."""
    from sqlalchemy import func, select

    from app.models import StreamEvent

    cutoff = SEEK_FILTERING_SINCE.replace(tzinfo=None)
    count, newest = db.execute(
        select(func.count(), func.max(StreamEvent.started_at)).where(
            StreamEvent.kind == "buffering", StreamEvent.started_at < cutoff
        )
    ).one()
    return int(count or 0), newest


def forget_unfiltered(db) -> int:
    """Drop them. Nothing else refers to a stall, so this leaves no gaps."""
    from sqlalchemy import delete

    from app.models import StreamEvent

    cutoff = SEEK_FILTERING_SINCE.replace(tzinfo=None)
    result = db.execute(
        delete(StreamEvent).where(StreamEvent.kind == "buffering", StreamEvent.started_at < cutoff)
    )
    return int(result.rowcount or 0)

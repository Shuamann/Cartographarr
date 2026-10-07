"""What somebody has started and not finished.

Not a Plex question, which was worth checking before building anything: the
history already carries how far into a thing each play got. Twenty nine people
on the server this was written against have something between five and eighty
five per cent finished in the last ninety days, and there was no way to see
any of it.

Two uses, and the second is the one that matters for a tool about managing a
server. The obvious one is a list of what a person has not finished. The other
is not offering to delete it, which the cleanup list now handles separately.

An episode is shown under its show, because that is how somebody thinks about
it: the answer to "what am I partway through" is "Stranger Things", not "an
episode called Chapter Three".
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

log = logging.getLogger(__name__)

STARTED = 5
"""Below this nothing was really watched. A play that got two per cent in is
somebody opening the wrong thing and closing it."""

FINISHED = 85
"""At or above this it is finished, whatever the number says. Credits, a
stinger and a few seconds of black are the difference between 85 and 100, and
calling those unfinished would put every watched episode on the list."""

WINDOW_DAYS = 180
"""How far back to look. Something started a year ago and never returned to
was not left half watched, it was abandoned."""


def for_user(db, user_id: int, days: int = WINDOW_DAYS, limit: int = 12) -> list[dict[str, Any]]:
    """Titles this person started and has not finished, most recent first."""
    from app.models import History

    since = int(datetime.now(UTC).timestamp()) - days * 86400
    # The furthest they ever got into each thing, and when they last touched
    # it. Furthest rather than latest, because starting something again from
    # the beginning does not unwatch the first three quarters.
    best = (
        select(
            History.rating_key.label("rating_key"),
            func.max(History.percent_complete).label("done"),
            func.max(History.started).label("last"),
            func.max(History.grandparent_rating_key).label("show"),
            func.max(History.grandparent_title).label("show_title"),
            func.max(History.full_title).label("what"),
            func.max(History.media_type).label("media_type"),
        )
        .where(
            History.user_id == user_id,
            History.rating_key.is_not(None),
            History.started >= since,
        )
        .group_by(History.rating_key)
        .subquery()
    )
    # More than asked for, because the dedupe below is what decides how many
    # there really are.
    rows = db.execute(
        select(best)
        .where(best.c.done >= STARTED, best.c.done < FINISHED)
        .order_by(best.c.last.desc())
        .limit(limit * 10)
    ).all()

    # One row per show, not one per episode. Somebody four episodes into a
    # season is partway through one programme, and listing House of the Dragon
    # four times is a list about the data rather than about them. The most
    # recent episode wins, which is the one they are actually on.
    seen: set[int] = set()
    kept = []
    for row in rows:
        group = row.show or row.rating_key
        if group in seen:
            continue
        seen.add(group)
        kept.append(row)
        if len(kept) >= limit:
            break
    rows = kept

    return [
        {
            "rating_key": row.rating_key,
            "show_rating_key": row.show,
            # The show for an episode, the film for a film: what somebody would
            # say they are partway through.
            "title": row.show_title or row.what,
            "what": row.what,
            "media_type": row.media_type,
            "percent": int(row.done or 0),
            "last_play": row.last,
        }
        for row in rows
    ]

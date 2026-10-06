"""Is anything missing, and if so what.

Switching where the data comes from is the one change in this app where
everything can look normal and be wrong. Rows keep arriving, pages keep
drawing, and a day nobody noticed was never fetched looks exactly like a day
nobody watched anything.

So the useful half of bringing in Tautulli's history is a question rather than
a copy: day by day, across the whole of Tautulli's history, how many plays it
recorded against how many are here. A day that matches is done. A day short by
three is the thing to go and fetch.

Importing what is already here is not a risk worth guarding against twice over:
history is keyed on Tautulli's own row id and written with an upsert, so the
same play arriving again changes nothing. This checks rather than trusts that,
by counting both sides.

One request answers the Tautulli side for two thousand days, so asking is
cheap enough to do whenever somebody wants to know.
"""

from __future__ import annotations

import collections
import logging
from datetime import datetime

from sqlalchemy import select

from app.db import session_scope

log = logging.getLogger(__name__)

SPAN_DAYS = 2000
"""How far back to ask. Longer than any install has been running, and the
answer is one request whatever the number, so there is no saving in guessing
smaller."""

SHOW_DAYS = 30
"""How many offending days to name. A missing week in 2022 and a missing hour
last Tuesday are different problems and both are visible in a handful of rows;
a list of six hundred is not a report, it is the raw data again."""


def _ours() -> collections.Counter:
    """Plays here, by the day they started.

    By the container's clock, because that is the clock Tautulli's own daily
    figures use when the two run side by side. Where they disagree it shows up
    as adjacent days being short and over by the same amount, rather than as a
    silent miscount, which is the reason this reports both directions.
    """
    from app.models import History

    counted: collections.Counter = collections.Counter()
    with session_scope() as db:
        for (started,) in db.execute(select(History.started).where(History.started.is_not(None))).all():
            counted[datetime.fromtimestamp(started).strftime("%Y-%m-%d")] += 1
    return counted


async def compare(client, span: int = SPAN_DAYS) -> dict:
    """Day by day, what Tautulli has against what is here."""
    data = await client.call("get_plays_by_date", time_range=span, y_axis="plays", grouping=0) or {}
    days = data.get("categories") or []
    series = {s.get("name"): s.get("data") or [] for s in data.get("series") or []}
    # Total is TV, Movies and Music added up, which is the figure to compare
    # against a count of our rows rather than any one kind.
    totals = series.get("Total") or []
    if not days or len(totals) != len(days):
        return {"asked": False, "reason": "Tautulli did not return daily totals"}

    ours = _ours()
    short = []
    over = []
    for day, theirs in zip(days, totals):
        here = ours.get(day, 0)
        if theirs > here:
            short.append({"day": day, "tautulli": theirs, "here": here, "difference": theirs - here})
        elif here > theirs:
            over.append({"day": day, "tautulli": theirs, "here": here, "difference": here - theirs})

    return {
        "asked": True,
        "days": len(days),
        "from": days[0],
        "to": days[-1],
        "tautulli": sum(totals),
        "here": sum(ours.get(day, 0) for day in days),
        "missing": sum(d["difference"] for d in short),
        "missing_days": short[:SHOW_DAYS],
        "missing_day_count": len(short),
        # Not a fault on its own: this app records plays from Plex directly
        # when Tautulli is not connected, so days it watched and Tautulli did
        # not are expected. Reported because a lot of them, on days Tautulli
        # was running, is the sign of something counted twice.
        "extra": sum(d["difference"] for d in over),
        "extra_days": over[:SHOW_DAYS],
        "extra_day_count": len(over),
    }


async def fill(client, result: dict | None = None) -> dict:
    """Fetch the days that are short, and nothing else.

    Each day is one request for that day alone, so a single missing evening
    costs one request rather than a walk through four years. A play already
    here arrives with the row id it already has and the upsert leaves it
    alone, so running this twice is safe and boring.
    """
    from app.services import recorded
    from app.services.sync import _map_history, _upsert

    from app.models import History

    if result is None:
        result = await compare(client)
    if not result.get("asked"):
        return {"filled": 0, "days": 0, "reason": result.get("reason")}

    days = [d["day"] for d in result["missing_days"]]
    written = 0
    for day in days:
        data = await client.call(
            "get_history", start=0, length=1000, after=day, before=day, order_column="date", order_dir="asc",
            # One row per session, the same as the sync, or a paused and
            # resumed play would be counted and stored differently here.
            grouping=0,
        )
        rows = [m for m in map(_map_history, (data or {}).get("data") or []) if m["row_id"] is not None]
        if not rows:
            continue
        with session_scope() as db:
            _upsert(db, History, rows)
            # The same thing the history sync does after writing, and for the
            # same reason: an install that ran on Plex alone recorded these
            # plays itself, under a negative id, and Tautulli has now
            # delivered its own copy of them. Without this the day fills up
            # with both and is counted twice, which this whole feature exists
            # to notice.
            recorded.drop_duplicates(db, rows)
        written += len(rows)
    log.info("handover fill: %d rows across %d days", written, len(days))
    return {"filled": written, "days": len(days)}

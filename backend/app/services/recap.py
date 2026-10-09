"""A person's month or year, in a screenful.

Everything here was already in the history: how long they watched, what, when,
on what, and what they started. Other media apps lead with this page and this
one had every number for it and no page.

A viewer sees their own, under the same rule as the rest of their profile, so
nothing here is new exposure: it is the history they can already read, added
up.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.plays import plays

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _hours(seconds: float | None) -> float:
    return round((seconds or 0) / 3600, 1)


def for_user(db, user_id: int, days: int, now: int | None = None) -> dict[str, Any]:
    from app.models import History, MediaItem, MediaTag

    now = now or int(datetime.now().timestamp())
    since = now - days * 86400
    before = since - days * 86400
    mine = [History.user_id == user_id, History.started >= since, History.started < now]

    total = db.execute(
        select(plays(History), func.sum(History.play_duration), func.count(func.distinct(History.player))).where(*mine)
    ).one()
    earlier = db.execute(
        select(func.sum(History.play_duration)).where(
            History.user_id == user_id, History.started >= before, History.started < since
        )
    ).scalar()

    # When, from the rows themselves: a weekday and an hour in the server's
    # own time, which is the time rules already go by.
    weekday: Counter[int] = Counter()
    hour: Counter[int] = Counter()
    day: Counter[str] = Counter()
    for started, seconds in db.execute(select(History.started, History.play_duration).where(*mine)):
        when = datetime.fromtimestamp(started)
        weight = seconds or 0
        weekday[when.weekday()] += weight
        hour[when.hour] += weight
        day[when.date().isoformat()] += weight

    # What, a show as one title rather than one row per episode.
    title_key = func.coalesce(History.grandparent_rating_key, History.rating_key)
    top = db.execute(
        select(
            title_key.label("key"),
            func.max(func.coalesce(History.grandparent_title, History.full_title)).label("title"),
            func.max(History.media_type).label("media_type"),
            func.max(func.coalesce(History.grandparent_rating_key, 0)).label("is_show"),
            func.sum(History.play_duration).label("seconds"),
            plays(History).label("plays"),
        )
        .where(*mine)
        .group_by(title_key)
        .order_by(func.sum(History.play_duration).desc())
        .limit(6)
    ).all()
    years = dict(
        db.execute(
            select(MediaItem.rating_key, MediaItem.year).where(MediaItem.rating_key.in_([t.key for t in top if t.key]))
        ).all()
    )

    # Genres by time spent, through the show for an episode, which has none
    # of its own. A film in three genres counts in each, which is right for
    # "what do they watch" and is why these are not shares of a whole.
    genre_seconds: Counter[str] = Counter()
    for genre, seconds in db.execute(
        select(MediaTag.value, func.sum(History.play_duration))
        .join(MediaTag, (MediaTag.rating_key == title_key) & (MediaTag.kind == "genre"))
        .where(*mine)
        .group_by(MediaTag.value)
    ):
        genre_seconds[genre] += seconds or 0

    # Shows started: their first play of any episode, ever, falls inside the
    # window. A show they came back to is not one they started.
    first = (
        select(History.grandparent_rating_key.label("show"), func.min(History.started).label("first"))
        .where(History.user_id == user_id, History.grandparent_rating_key.is_not(None))
        .group_by(History.grandparent_rating_key)
        .subquery()
    )
    started_shows = db.execute(select(func.count()).select_from(first).where(first.c.first >= since)).scalar()

    seconds = total[1] or 0
    busiest = day.most_common(1)[0] if day else None
    return {
        "days": days,
        "plays": total[0],
        "hours": _hours(seconds),
        # Against the window before this one, so "40 hours" has something to
        # be more or less than. None when there was nothing then to compare.
        "hours_before": _hours(earlier) if earlier else None,
        "days_watched": len(day),
        "devices": total[2],
        "shows_started": started_shows or 0,
        "busiest_weekday": WEEKDAYS[weekday.most_common(1)[0][0]] if weekday else None,
        "busiest_hour": hour.most_common(1)[0][0] if hour else None,
        "biggest_day": {"date": busiest[0], "hours": _hours(busiest[1])} if busiest else None,
        "top": [
            {
                "rating_key": t.key,
                "title": (t.title or "").split(" - ")[0] if t.is_show else t.title,
                "media_type": "show" if t.is_show else t.media_type,
                "year": years.get(t.key),
                "hours": _hours(t.seconds),
                "plays": t.plays,
            }
            for t in top
        ],
        "genres": [{"genre": g, "hours": _hours(s)} for g, s in genre_seconds.most_common(5)],
    }

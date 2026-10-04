"""One message a week with the week in it.

Every number this app works out sits on a page waiting to be visited, and the
evidence from a real install is that the pages are not visited: devices
unreviewed for years, signals nobody opened, an update check that had been
failing for the life of the install. None of that is a missing feature, it is
a missing nudge.

So this is the dashboard's week, pushed instead of pulled, through the Apprise
setup that is already there. It adds no data and no analysis: every figure in
it is one the app already answers somewhere.

Plain text with no markup, because it has to read the same in Discord, in
ntfy, in a push notification and in an email.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Device, History, Issue, Library, MediaItem, StreamSession, TravelFlag
from app.plays import plays

WEEK = 7 * 86400


def _hours(seconds: Any) -> str:
    h = (seconds or 0) / 3600.0
    return f"{h:,.0f} hours" if h >= 10 else f"{h:,.1f} hours"


def _size(by: int | None) -> str:
    gb = (by or 0) / 1e9
    return f"{gb / 1000:,.1f} TB" if gb >= 1000 else f"{gb:,.0f} GB"


def _change(now: float, before: float) -> str:
    """How this week compares, in words, and nothing at all when there is no
    week before to compare with."""
    if not before:
        return ""
    share = (now - before) / before * 100
    if abs(share) < 5:
        return " (about the same as the week before)"
    return f" ({'up' if share > 0 else 'down'} {abs(share):.0f}% on the week before)"


def _watching(db: Session, since: int, before: int) -> list[str]:
    row = db.execute(
        select(
            plays(History).label("plays"),
            func.coalesce(func.sum(History.play_duration), 0).label("seconds"),
            func.count(func.distinct(History.user_id)).label("people"),
        ).where(History.started >= since)
    ).one()
    if not row.plays:
        return ["Nobody watched anything this week."]

    last = db.execute(
        select(plays(History)).where(History.started >= before, History.started < since)
    ).scalar() or 0
    lines = [
        f"{row.plays:,} plays, {_hours(row.seconds)}, {row.people} "
        f"{'person' if row.people == 1 else 'people'}{_change(row.plays, last)}"
    ]

    name = func.coalesce(History.grandparent_title, History.title)
    top = db.execute(
        select(name.label("name"), func.coalesce(func.sum(History.play_duration), 0).label("seconds"))
        .where(History.started >= since)
        .group_by(name)
        .order_by(func.sum(History.play_duration).desc())
        .limit(3)
    ).all()
    watched = ", ".join(f"{t.name} ({_hours(t.seconds)})" for t in top if t.name)
    if watched:
        lines.append(f"Most watched: {watched}")
    return lines


def _people(db: Session, since: int) -> list[str]:
    lines = []
    new = db.execute(
        select(Device.player, Device.platform)
        .where(Device.first_seen >= since)
        .order_by(Device.first_seen.desc())
        .limit(5)
    ).all()
    count = db.execute(select(func.count()).select_from(Device).where(Device.first_seen >= since)).scalar() or 0
    if count:
        named = ", ".join(f"{d.player or 'unnamed'}{f' ({d.platform})' if d.platform else ''}" for d in new)
        lines.append(f"{count} new device{'' if count == 1 else 's'}: {named}{', and more' if count > len(new) else ''}")

    fresh = db.execute(
        select(func.count()).select_from(TravelFlag)
        .where(TravelFlag.created_at >= datetime.fromtimestamp(since, UTC))
    ).scalar() or 0
    waiting = db.execute(select(func.count()).select_from(TravelFlag).where(TravelFlag.status == "new")).scalar() or 0
    if fresh or waiting:
        lines.append(
            f"{fresh} new signal{'' if fresh == 1 else 's'}, {waiting} waiting to be looked at"
            if fresh
            else f"{waiting} signal{'' if waiting == 1 else 's'} still waiting to be looked at"
        )
    return lines


def _problems(db: Session, since: int) -> list[str]:
    lines = []
    raised = db.execute(
        select(func.count()).select_from(Issue).where(Issue.created_at >= datetime.fromtimestamp(since, UTC))
    ).scalar() or 0
    open_now = db.execute(select(func.count()).select_from(Issue).where(Issue.status == "open")).scalar() or 0
    if raised or open_now:
        lines.append(f"{raised} problem{'' if raised == 1 else 's'} reported this week, {open_now} still open")

    streams = db.execute(
        select(
            func.count().label("all"),
            func.sum(case((StreamSession.buffer_count > 0, 1), else_=0)).label("stalled"),
        ).where(StreamSession.started_at >= datetime.fromtimestamp(since, UTC))
    ).one()
    if streams.all and streams.stalled:
        lines.append(f"{streams.stalled} of {streams.all} streams stalled")
    return lines


def _library(db: Session) -> list[str]:
    """Where it stands, not how it changed: nothing records when a file was
    added, so a week-on-week figure would be made up."""
    row = db.execute(
        select(func.count().label("files"), func.coalesce(func.sum(MediaItem.file_size), 0).label("size"))
        .where(MediaItem.media_type.in_(("movie", "episode")))
    ).one()
    if not row.files:
        return []
    never = db.execute(
        select(func.count())
        .select_from(MediaItem)
        .where(
            MediaItem.media_type.in_(("movie", "episode")),
            ~select(1).where(History.rating_key == MediaItem.rating_key).correlate(MediaItem).exists(),
        )
    ).scalar() or 0
    libraries = db.execute(select(func.count()).select_from(Library)).scalar() or 0
    return [
        f"{row.files:,} files, {_size(row.size)}, across {libraries} "
        f"{'library' if libraries == 1 else 'libraries'}",
        f"{never:,} of them have never been played",
    ]


def _jobs() -> list[str]:
    from app import tasks

    broken = [t for t in tasks.TASKS.values() if t.consecutive >= 3]
    if not broken:
        return []
    return [
        f"{t.name} has failed {t.consecutive} times in a row: {t.last.get('message') or 'no message'}"
        for t in broken
    ]


def compose(db: Session, now: datetime | None = None) -> tuple[str, str]:
    """The title and body. Sections with nothing in them are left out, so a
    quiet week is a short message rather than a page of zeroes."""
    at = now or datetime.now(UTC)
    since = int(at.timestamp()) - WEEK
    before = since - WEEK

    parts: list[tuple[str, list[str]]] = [
        ("Watching", _watching(db, since, before)),
        ("People and devices", _people(db, since)),
        ("Problems", _problems(db, since)),
        ("Library", _library(db)),
        ("Jobs that need a look", _jobs()),
    ]
    body = "\n\n".join(
        f"{head}\n" + "\n".join(f"  {line}" for line in lines) for head, lines in parts if lines
    )
    # %-d is not portable, and "week to 04 October" reads like a form.
    return f"Cartographarr, week to {at.day} {at:%B}", body


async def send() -> str:
    from app.db import session_scope
    from app.integrations.notify import apprise_notifier

    if not apprise_notifier.configured():
        raise RuntimeError("No notification targets configured")
    with session_scope() as db:
        title, body = compose(db)
    await apprise_notifier.send(title, body)
    return f"sent, {len(body.splitlines())} lines"

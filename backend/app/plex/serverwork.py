"""What the Plex server is doing of its own accord.

Not the same question as plex/activity.py, which is what people are watching.
This is the server's own work: the jobs it runs for itself.

Scanning a library, analysing media, generating chapter thumbnails or credits
markers: work nobody asked for at that moment, which reads every file it
touches off the same disks a stream is being read from. This app has recorded
stalls since it existed and has never had anything to blame one on except the
stream itself, which is why "it buffered and nothing was wrong" has been an
answer it could give.

Plex lists what is running at `/activities`, and nothing else. There is no
history and no finished event: a job that ends simply stops being listed. So
what is kept here is a spell, one row per job, with when it was first and last
seen running. "Was the server busy while this stalled" is then a range rather
than a trawl through a sample a minute.

The shape was measured rather than assumed, by asking for a library scan and
watching what came back:

    type       library.update.section
    title      Scanning Anime Movies
    subtitle   the item it is on at that moment
    progress   99
    uuid       lasts as long as the job
    Context    librarySectionID

Reading it costs about six milliseconds and the answer is usually empty, which
is why it rides on the stream poll rather than having a timer of its own.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)

def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def now() -> list[dict[str, Any]]:
    """What Plex says it is doing this second.

    Blocking, because plexapi is. An empty list is the normal answer.
    """
    from app.plex.server import server

    found = []
    for item in server().query("/activities"):
        section = None
        for child in item:
            section = section or _int(child.attrib.get("librarySectionID"))
        found.append({
            "uuid": item.attrib.get("uuid") or "",
            "kind": item.attrib.get("type") or None,
            "title": item.attrib.get("title") or None,
            "subtitle": item.attrib.get("subtitle") or None,
            "progress": _int(item.attrib.get("progress")),
            "section_id": section,
        })
    return [row for row in found if row["uuid"]]


def record(db, rows: list[dict[str, Any]], at: datetime | None = None) -> int:
    """Write down that these were running. Returns how many were new.

    A spell already open is touched rather than written again, which is the
    whole point of keying on Plex's uuid: a scan seen on forty polls is one
    row that lasted, not forty rows a few seconds apart.
    """
    from sqlalchemy import select

    from app.models import ServerJob

    when = at or datetime.now(UTC).replace(tzinfo=None)
    if not rows:
        return 0
    seen = {row["uuid"]: row for row in rows}
    open_now = {
        job.uuid: job
        for job in db.execute(select(ServerJob).where(ServerJob.uuid.in_(seen))).scalars()
    }
    new = 0
    for uuid, row in seen.items():
        job = open_now.get(uuid)
        if job is None:
            db.add(ServerJob(uuid=uuid, started_at=when, last_seen=when, **{
                k: row[k] for k in ("kind", "title", "subtitle", "progress", "section_id")
            }))
            new += 1
            continue
        job.last_seen = when
        job.progress = row["progress"]
        job.subtitle = row["subtitle"]
    return new


def busy_at(db, when: datetime, slack: timedelta = timedelta(minutes=1)) -> list[dict[str, Any]]:
    """What the server was doing at that moment.

    With a minute of slack either side, because a stall is recorded when the
    stream ends and the poll that saw the job is not the same second. Without
    it a job that started one poll after the stall began would never line up
    with it, which is the case most worth catching.

    A spell has a real end rather than an open one, so the app being stopped
    mid scan leaves a spell that stops at its last sighting and cannot go on
    being blamed for everything after it.
    """
    from sqlalchemy import select

    from app.models import ServerJob

    rows = db.execute(
        select(ServerJob)
        .where(ServerJob.started_at <= when + slack, ServerJob.last_seen >= when - slack)
        .order_by(ServerJob.started_at)
    ).scalars()
    return [
        {
            "kind": job.kind,
            "title": job.title,
            "section_id": job.section_id,
            "started_at": job.started_at,
            "last_seen": job.last_seen,
            "minutes": round((job.last_seen - job.started_at).total_seconds() / 60, 1)
            if job.started_at and job.last_seen
            else None,
        }
        for job in rows
    ]


def recent(db, hours: int = 48, limit: int = 50) -> list[dict[str, Any]]:
    """The spells that have run lately, newest first."""
    from sqlalchemy import select

    from app.models import ServerJob

    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)
    rows = db.execute(
        select(ServerJob).where(ServerJob.last_seen >= since).order_by(ServerJob.started_at.desc()).limit(limit)
    ).scalars()
    return [
        {
            "kind": job.kind,
            "title": job.title,
            "subtitle": job.subtitle,
            "section_id": job.section_id,
            "progress": job.progress,
            "started_at": job.started_at,
            "last_seen": job.last_seen,
            "minutes": round((job.last_seen - job.started_at).total_seconds() / 60, 1)
            if job.started_at and job.last_seen
            else None,
        }
        for job in rows
    ]


def sample() -> int:
    """Read what is running and write it down. Never raises.

    Rides on the stream poll, so a Plex that will not answer must not stop the
    poll that enforces the rules.
    """
    from app.db import session_scope

    try:
        rows = now()
    except Exception as exc:  # noqa: BLE001 - the rules matter more than this
        log.debug("could not read what Plex is doing: %s", exc)
        return 0
    if not rows:
        return 0
    with session_scope() as db:
        return record(db, rows)

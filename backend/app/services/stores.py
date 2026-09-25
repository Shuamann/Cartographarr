"""Which storage each file sits on, and how each one behaves.

A Plex library can point at more than one place: an array share and a network
SSD, say. Plex reports the path it sees, so the top of that path is the mount,
and the mount is the storage. Nothing else in the app knew this, which meant a
file that stalls could never be traced to the box it lives on.

Roots are discovered from the paths themselves, so this works on any server
without anyone filling in a form. Giving two roots the same name puts them
together: four mounts off one NAS become one store called what you call it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.db import session_scope
from app.plays import plays, plays_when
from app.settings_store import current

UNKNOWN = "Not known"


def root_of(path: str | None, depth: int = 1) -> str | None:
    """The mount a path sits under: its first `depth` parts."""
    if not path:
        return None
    text = path.replace("\\", "/")
    parts = [part for part in text.split("/") if part]
    if not parts:
        return None
    return "/" + "/".join(parts[:depth])


def labels() -> dict[str, str]:
    from app.models import LibraryStore

    with session_scope() as db:
        return {row.prefix: row.label for row in db.execute(select(LibraryStore)).scalars() if row.label}


def name_for(path: str | None, named: dict[str, str] | None = None, depth: int | None = None) -> str:
    """What to call the storage a file is on."""
    depth = depth or current().library_store_depth
    root = root_of(path, depth)
    if root is None:
        return UNKNOWN
    return (named or labels()).get(root) or root


def summary(days: int = 30) -> dict[str, Any]:
    """Every store: what it holds, how much is watched from it, and what goes
    wrong there."""
    from app.models import History, MediaItem, StreamEvent
    from app.services.library import _since
    from app.services.library_scan import in_library

    since, cutoff = _since(days)
    depth = current().library_store_depth
    named = labels()

    with session_scope() as db:
        files = db.execute(
            select(MediaItem.rating_key, MediaItem.file_path, MediaItem.file_size, MediaItem.file_bitrate)
            .where(MediaItem.file_path.is_not(None), in_library())
        ).all()
        remote = History.location == "wan"
        watched = {
            row[0]: row
            for row in db.execute(
                select(
                    History.rating_key,
                    plays(History),
                    plays_when(History, remote),
                    plays_when(History, History.transcode_decision == "transcode"),
                )
                .where(History.started >= since, History.rating_key.is_not(None))
                .group_by(History.rating_key)
            ).all()
        }
        stalls = dict(
            db.execute(
                select(StreamEvent.rating_key, func.count())
                .where(StreamEvent.started_at >= cutoff, StreamEvent.rating_key.is_not(None))
                .group_by(StreamEvent.rating_key)
            ).all()
        )
    stores: dict[str, dict[str, Any]] = {}
    for rating_key, path, size, bitrate in files:
        root = root_of(path, depth) or UNKNOWN
        label = named.get(root) or root
        store = stores.setdefault(label, {
            "store": label, "roots": set(), "files": 0, "size": 0, "bitrate_total": 0, "bitrate_files": 0,
            "plays": 0, "remote_plays": 0, "transcodes": 0, "stalls": 0,
        })
        store["roots"].add(root)
        store["files"] += 1
        store["size"] += int(size or 0)
        if bitrate:
            store["bitrate_total"] += int(bitrate)
            store["bitrate_files"] += 1
        play = watched.get(rating_key)
        if play:
            store["plays"] += int(play[1] or 0)
            store["remote_plays"] += int(play[2] or 0)
            store["transcodes"] += int(play[3] or 0)
        store["stalls"] += int(stalls.get(rating_key) or 0)

    out = []
    for store in stores.values():
        files_with_bitrate = store.pop("bitrate_files")
        total = store.pop("bitrate_total")
        out.append({
            **store,
            "roots": sorted(store["roots"]),
            "average_bitrate": round(total / files_with_bitrate) if files_with_bitrate else None,
            # What a store is judged on: how often watching from it goes wrong.
            "stalls_per_100": round(store["stalls"] / store["plays"] * 100, 1) if store["plays"] else None,
            "transcode_percent": round(store["transcodes"] / store["plays"] * 100) if store["plays"] else None,
        })
    out.sort(key=lambda s: -s["size"])
    return {"stores": out, "days": days, "depth": depth}


WEEKS = 12
"""How many weeks of history the trend covers. Long enough to tell a bad week
from a store going downhill, short enough that a disk replaced in the spring
is not still being held against it."""


def trend(weeks: int = WEEKS) -> dict[str, Any]:
    """How often watching from each store went wrong, week by week.

    The summary says which store is worst now. This says whether it always was.
    A mount that has crept up over six weeks is a disk going bad; one that had
    a single terrible week was a night when something else was wrong, and the
    two want different things done about them.

    Counted as the share of plays that stalled at all, rather than how many
    stalls there were: one bad stream that rebuffers forty times is one bad
    stream, and a rate that can pass 100 per 100 plays is a rate nobody can
    read.
    """
    from app.models import History, MediaItem, StreamEvent
    from app.services.library_scan import in_library

    now = datetime.now(UTC)
    start = now - timedelta(weeks=weeks)
    depth = current().library_store_depth
    named = labels()

    def week_of(moment: datetime) -> str:
        """Monday of that week, as a date, which is what the axis is labelled with."""
        day = moment.date() - timedelta(days=moment.weekday())
        return day.isoformat()

    with session_scope() as db:
        where = [MediaItem.file_path.is_not(None), in_library()]
        store_of = {
            key: (named.get(root_of(path, depth) or UNKNOWN) or root_of(path, depth) or UNKNOWN)
            for key, path in db.execute(select(MediaItem.rating_key, MediaItem.file_path).where(*where)).all()
        }
        played = db.execute(
            select(History.rating_key, History.started)
            .where(History.started >= int(start.timestamp()), History.rating_key.is_not(None))
        ).all()
        stalled = db.execute(
            select(StreamEvent.rating_key, StreamEvent.started_at, StreamEvent.session_key)
            .where(StreamEvent.started_at >= start.replace(tzinfo=None), StreamEvent.rating_key.is_not(None))
        ).all()
        # Stalls are only known from the day this app started watching live
        # streams. Before that a week with no stalls in it is a week nobody
        # was counting, which is not the same thing and must not be drawn as
        # a good week.
        first = db.execute(select(func.min(StreamEvent.started_at))).scalar()

    recording_from = week_of(first.replace(tzinfo=UTC)) if first else None
    this_week = week_of(now)
    weeks_wanted = [week_of(start + timedelta(weeks=n)) for n in range(weeks + 1)]
    counts: dict[str, dict[str, dict[str, Any]]] = {}

    def bucket(store: str, week: str) -> dict[str, Any]:
        return counts.setdefault(store, {}).setdefault(week, {"plays": 0, "streams": set(), "stalls": 0})

    for key, started in played:
        store = store_of.get(key)
        if store:
            bucket(store, week_of(datetime.fromtimestamp(started, UTC)))["plays"] += 1
    for key, at, session_key in stalled:
        store = store_of.get(key)
        if store:
            week = bucket(store, week_of(at.replace(tzinfo=UTC)))
            week["stalls"] += 1
            # One stream that rebuffers all evening is one stream that went badly.
            week["streams"].add(session_key or f"event-{key}-{at}")

    out = []
    for store, by_week in counts.items():
        points = []
        for week in weeks_wanted:
            here = by_week.get(week) or {"plays": 0, "streams": set(), "stalls": 0}
            counted = recording_from is not None and week >= recording_from
            bad = len(here["streams"])
            points.append({
                "week": week,
                "plays": here["plays"],
                "stalls": here["stalls"] if counted else None,
                "stalled_streams": bad if counted else None,
                # Weeks with barely anything watched say nothing, and drawn as
                # zero they say something untrue, so they have no rate at all.
                # Nor do weeks from before anything was being counted.
                "stalled_percent": round(min(bad, here["plays"]) / here["plays"] * 100, 1)
                if counted and here["plays"] >= 10 else None,
                # The week in progress is short, so its rate is thin evidence.
                "partial": week == this_week,
            })
        rated = [p["stalled_percent"] for p in points if p["stalled_percent"] is not None]
        out.append({
            "store": store,
            "points": points,
            "worst": max(rated) if rated else None,
            "direction": _direction(rated),
        })
    out.sort(key=lambda s: -(s["worst"] or 0))
    return {"stores": out, "weeks": weeks, "recording_from": recording_from}


def _direction(rated: list[float]) -> str | None:
    """Which way a store is heading: the recent half against the earlier half.

    Deliberately blunt. With one number a week there is no trend worth fitting
    a line to, and the question being asked is only whether to go and look.
    """
    if len(rated) < 4:
        return None
    half = len(rated) // 2
    before = sum(rated[:half]) / half
    after = sum(rated[half:]) / (len(rated) - half)
    if before < 0.5 and after < 0.5:
        return "steady"
    if after > before * 1.5 and after - before >= 0.5:
        return "worse"
    if before > after * 1.5 and before - after >= 0.5:
        return "better"
    return "steady"


TOP = 4
"""How many viewers, devices or titles are worth naming. Past four it is a list
rather than an answer."""


def trouble(store: str, days: int = 30) -> dict[str, Any]:
    """What the stalling at one store is actually made of.

    A store with a bad number next to it is not necessarily bad storage. The
    same number comes from a disk that cannot keep up, from one household on a
    poor connection, and from one enormous new film nobody can stream. They
    want different things done about them, and only the breakdown tells them
    apart: stalls on your own network point at the storage, stalls from remote
    viewers point at the line out of the house or at the file's bitrate.
    """
    from app.models import MediaItem, StreamEvent
    from app.services.library import _since
    from app.services.library_scan import in_library

    since, cutoff = _since(days)
    depth = current().library_store_depth
    named = labels()

    with session_scope() as db:
        keys = [
            key
            for key, path in db.execute(
                select(MediaItem.rating_key, MediaItem.file_path)
                .where(MediaItem.file_path.is_not(None), in_library())
            ).all()
            if (named.get(root_of(path, depth) or UNKNOWN) or root_of(path, depth) or UNKNOWN) == store
        ]
        events = []
        if keys:
            events = db.execute(
                select(StreamEvent)
                .where(StreamEvent.started_at >= cutoff, StreamEvent.rating_key.in_(keys),
                       StreamEvent.kind == "buffering")
            ).scalars().all()
            events = [{
                "session_key": e.session_key,
                "username": e.username,
                "player": e.player,
                "platform": e.platform,
                "rating_key": e.rating_key,
                "full_title": e.full_title,
                "location": e.location,
                "transcode_decision": e.transcode_decision,
                "cause": e.cause,
                "seconds": e.seconds,
            } for e in events]

    def top(field: str) -> list[dict[str, Any]]:
        counted: dict[Any, dict[str, Any]] = {}
        for event in events:
            value = event.get(field)
            if value is None:
                continue
            row = counted.setdefault(value, {"name": value, "events": 0, "streams": set()})
            row["events"] += 1
            row["streams"].add(event.get("session_key") or id(event))
        out = [{**row, "streams": len(row["streams"])} for row in counted.values()]
        out.sort(key=lambda r: -r["events"])
        return out[:TOP]

    remote = sum(1 for e in events if e["location"] == "wan")
    local = sum(1 for e in events if e["location"] == "lan")
    transcoded = sum(1 for e in events if e["transcode_decision"] == "transcode")
    streams = len({e["session_key"] or id(e) for e in events})
    people, devices, titles = top("username"), top("player"), top("full_title")

    return {
        "store": store,
        "days": days,
        "events": len(events),
        "streams": streams,
        "remote": remote,
        "local": local,
        "transcoded": transcoded,
        "people": people,
        "devices": devices,
        "titles": titles,
        "causes": top("cause"),
        "notes": _trouble_notes(len(events), remote, local, people, titles),
    }


def _trouble_notes(events: int, remote: int, local: int, people: list[dict[str, Any]],
                   titles: list[dict[str, Any]]) -> list[str]:
    """The two or three sentences worth leading with, in the order they answer
    the question. Nothing is said about a handful of stalls: four bad streams
    in a month is a month, not a pattern."""
    if events < 5:
        return []
    notes = []
    if remote and remote >= events * 0.8:
        notes.append(
            "Every stall here was a viewer watching from outside the house"
            if remote == events
            else f"{remote} of {events} stalls here were viewers watching from outside the house"
        )
        notes.append("That points at the line out of the house, or at the bitrate of these files, rather than at this storage.")
    elif local and local >= events * 0.5:
        notes.append(f"{local} of {events} stalls here were on your own network, which is where storage trouble shows up.")
    if people and people[0]["events"] >= max(5, events * 0.5):
        notes.append(f"{people[0]['events']} of them were {people[0]['name']}, on {people[0]['streams']} streams.")
    if titles and titles[0]["events"] >= max(5, events * 0.4):
        notes.append(f"{titles[0]['events']} were one title: {titles[0]['name']}.")
    return notes


def rename(prefix: str, label: str) -> None:
    """Name a root. Two roots with one name are one store."""
    from app.models import LibraryStore

    with session_scope() as db:
        row = db.get(LibraryStore, prefix)
        if row is None:
            db.add(LibraryStore(prefix=prefix, label=label))
        else:
            row.label = label

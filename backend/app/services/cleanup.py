"""What is taking up room without earning it.

Not a delete button. Plex, Radarr and Sonarr own the files; this says which
ones nobody has watched, how much room each takes, and why it stands out, and
hands the decision over. Anything you decide to keep can be marked as kept, so
the list is the things you have not thought about yet rather than the same
argument every month.

Three reasons a file lands here, weakest first:

- **big and never played**: nothing has ever played it, and it is large
- **not played in years**: it was watched once, long ago, and is large
- **4K nobody sees in 4K**: every play was scaled down, so the extra size
  bought nothing on the screens people actually use
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.db import session_scope

GB = 1024**3
BIG_ENOUGH = 8 * GB
"""Below this, the room saved is not worth anyone's attention."""

STALE_DAYS = 730
"""Two years without a play, which is long enough to mean something."""


def _kept() -> dict[int, str | None]:
    from app.models import KeepDecision

    with session_scope() as db:
        return {row.rating_key: row.reason for row in db.execute(select(KeepDecision)).scalars()}


WATCHING_DAYS = 60
"""How recently a show has to have been watched to count as being worked
through.

Long enough to cover somebody who watches an episode a week and takes a month
off, short enough that a show abandoned last year is not protected for ever.
"""


def _shows_being_watched(db, keys: list[int]) -> dict[int, tuple[str | None, int]]:
    """Shows anybody has played lately, and who last did.

    An episode nobody has played, in a show somebody is partway through, is
    not an abandoned file. It is the next episode. On this library 1,751 of
    the 8,911 big never played episodes are in a show watched in the last
    sixty days, so a fifth of the suggestions were asking somebody to delete
    what they were about to watch.
    """
    from sqlalchemy import func, select

    from app.models import History, User

    since = int(datetime.now(UTC).timestamp()) - WATCHING_DAYS * 86400
    rows = db.execute(
        select(
            History.grandparent_rating_key,
            func.max(History.started),
            func.coalesce(User.friendly_name, User.username),
        )
        .join(User, User.user_id == History.user_id, isouter=True)
        .where(
            History.grandparent_rating_key.is_not(None),
            History.started >= since,
        )
        .group_by(History.grandparent_rating_key)
    ).all()
    return {int(show): (who, int(when or 0)) for show, when, who in rows if show is not None}


def candidates(days: int = 365, limit: int = 200) -> dict[str, Any]:
    """Files worth a second look, biggest saving first."""
    from app.models import History, MediaItem, StreamSession
    from app.services.library import describe_file
    from app.services.library_scan import in_library
    from app.services.stores import name_for, labels

    now = int(datetime.now(UTC).timestamp())
    kept = _kept()
    named = labels()

    with session_scope() as db:
        items = db.execute(
            select(MediaItem).where(
                MediaItem.media_type.in_(("movie", "episode")),
                MediaItem.file_size.is_not(None),
                MediaItem.file_size >= BIG_ENOUGH,
                in_library(),
            )
        ).scalars().all()
        if not items:
            return {"items": [], "found": 0, "reclaimable": 0, "kept": len(kept), "days": days}

        keys = [item.rating_key for item in items]
        watching = _shows_being_watched(db, keys)
        played: dict[int, tuple[int, int | None]] = {
            key: (int(count or 0), last)
            for key, count, last in db.execute(
                select(History.rating_key, func.count(), func.max(History.started))
                .where(History.rating_key.in_(keys))
                .group_by(History.rating_key)
            ).all()
        }
        # What was actually sent to a screen, for the 4K question.
        scaled: dict[int, tuple[int, int]] = {}
        for key, resolution, count in db.execute(
            select(StreamSession.rating_key, StreamSession.stream_video_resolution, func.count())
            .where(StreamSession.rating_key.in_(keys))
            .group_by(StreamSession.rating_key, StreamSession.stream_video_resolution)
        ).all():
            seen, down = scaled.get(key, (0, 0))
            is_4k = str(resolution or "").lower() in ("4k", "2160", "2160p")
            scaled[key] = (seen + int(count or 0), down + (0 if is_4k else int(count or 0)))

        out = []
        spared = 0
        for item in items:
            if item.rating_key in kept:
                continue
            plays, last = played.get(item.rating_key, (0, None))
            age_days = int((now - last) / 86400) if last else None
            reason = _reason(item, plays, age_days, scaled.get(item.rating_key))
            if reason is None:
                continue
            # Somebody is working through this show, so this is their next
            # episode rather than a file nobody wants. Counted rather than
            # silently dropped: a list that quietly shrinks is a list nobody
            # can reason about.
            show = item.grandparent_rating_key
            if show is not None and int(show) in watching and reason[0] in ("never_played", "not_played_in_years"):
                spared += 1
                continue
            out.append({
                **describe_file(item),
                "media_type": item.media_type,
                "plays": plays,
                "last_play": last,
                "days_since": age_days,
                "store": name_for(item.file_path, named),
                "reason": reason[0],
                "why": reason[1],
            })

    out.sort(key=lambda row: -(row.get("file_size") or 0))
    # The room adds up across everything that stands out, not just the page of
    # it shown, or the number shrinks as you work through the list.
    reclaimable = sum(row.get("file_size") or 0 for row in out)
    return {
        "items": out[:limit],
        "found": len(out),
        "reclaimable": reclaimable,
        "kept": len(kept),
        "watching": spared,
        "watching_days": WATCHING_DAYS,
        "days": days,
    }


def _reason(item, plays: int, age_days: int | None, streams: tuple[int, int] | None) -> tuple[str, str] | None:
    """Why this file stands out, said plainly, or None if it does not."""
    size = int(item.file_size or 0)
    gigabytes = size / GB
    if plays == 0:
        return "never_played", f"Nothing has ever played it, and it takes {gigabytes:.0f} GB."
    if age_days is not None and age_days >= STALE_DAYS:
        years = age_days / 365
        return "not_played_in_years", (
            f"Played {plays} {'time' if plays == 1 else 'times'}, last about {years:.0f} years ago, "
            f"and it takes {gigabytes:.0f} GB."
        )
    resolution = str(item.video_resolution or "").lower()
    if resolution in ("4k", "2160", "2160p") and streams and streams[0] >= 3 and streams[1] == streams[0]:
        return "never_seen_in_4k", (
            f"All {streams[0]} recorded streams were sent below 4K, so its {gigabytes:.0f} GB "
            "has never reached a screen as 4K."
        )
    return None


def keep(rating_key: int, who: str | None, reason: str | None) -> None:
    """Decided to keep it. It stops being suggested until that is undone."""
    from app.models import KeepDecision

    with session_scope() as db:
        db.merge(KeepDecision(
            rating_key=rating_key, kept_by=who, reason=reason or None,
            kept_at=datetime.now(UTC).replace(tzinfo=None),
        ))


def unkeep(rating_key: int) -> bool:
    from app.models import KeepDecision

    with session_scope() as db:
        row = db.get(KeepDecision, rating_key)
        if row is None:
            return False
        db.delete(row)
        return True


def kept_list() -> list[dict[str, Any]]:
    """What has been decided already, so it can be changed."""
    from app.models import KeepDecision, MediaItem

    with session_scope() as db:
        rows = db.execute(select(KeepDecision).order_by(KeepDecision.kept_at.desc())).scalars().all()
        titles = {
            m.rating_key: (m.full_title or m.title)
            for m in db.execute(select(MediaItem).where(MediaItem.rating_key.in_([r.rating_key for r in rows]))).scalars()
        }
        return [
            {
                "rating_key": row.rating_key,
                "title": titles.get(row.rating_key) or f"Item {row.rating_key}",
                "reason": row.reason,
                "kept_by": row.kept_by,
                "kept_at": row.kept_at.isoformat() if row.kept_at else None,
            }
            for row in rows
        ]


# ---- one list, three ways of looking at it ---------------------------------
#
# Problem files, messy files and files taking up room were three pages asking
# three questions about the same library, with different actions on each. They
# are one page now: the question changes, the rows and what you can do about
# them do not.

LENSES = {
    "trouble": "Trouble for the people watching",
    "messy": "Awkward to play",
    "room": "Taking up room",
}


def attention(kind: str, days: int, threshold_kbps: int, limit: int = 200) -> dict[str, Any]:
    from app.db import session_scope
    from app.services import library
    from app.services.stores import labels

    kept = _kept()
    # Read once for the whole page. Worked out per row it was a database round
    # trip per file, four hundred of them, for an answer that cannot change
    # while the page is being built.
    named = labels()
    # Enough to still fill the page once the kept files are dropped, rather
    # than twice as many described for the sake of it.
    wanted = limit + len(kept)
    with session_scope() as db:
        if kind == "messy":
            found = library.messy_files(db, days, limit=wanted)
            rows = [_row(f, "messy", _messy_why(f), threshold_kbps, named) for f in found["files"]]
            extra = {"checked": found["checked"], "counts": found["counts"]}
        elif kind == "room":
            found = candidates(days=days, limit=wanted)
            rows = [_row(f, "room", f.get("why"), threshold_kbps, named) for f in found["items"]]
            extra = {
                "reclaimable": found["reclaimable"],
                "found": found["found"],
                "watching": found.get("watching", 0),
                "watching_days": found.get("watching_days"),
            }
        else:
            found = library.problem_files(db, threshold_kbps, days, limit=wanted)
            rows = [_row(f, "trouble", _trouble_why(f), threshold_kbps, named) for f in found]
            extra = {}

    rows = [row for row in rows if row["rating_key"] not in kept]
    return {"kind": kind, "items": rows[:limit], "total": len(rows), "kept": len(kept), "days": days, **extra}


def _row(file: dict[str, Any], kind: str, why: str | None, threshold_kbps: int,
         named: dict[str, str] | None = None) -> dict[str, Any]:
    """Every row the same shape, whichever question found it, and no wider than
    the row on screen.

    Named field by field rather than spread from whatever the query returned.
    The three queries behind this each select what they need for their own
    sorting, which is a good deal more than a row shows, and spreading it sent
    the lot: the subtitle track list of every file, the full path, and every
    finding with its whole description, two hundred times over, so that the
    page could print one line of it. Four hundred and twenty kilobytes to draw
    fifty seven.

    The findings are still worked out, because a file listed for taking up room
    deserves the same "what is wrong and how to fix it" as one listed for
    stalling, and because the count is part of the row. Only the first one's
    title travels; opening the row fetches the file properly.
    """
    from app.services.findings import explain
    from app.services.stores import name_for

    findings = file.get("findings")
    if findings is None:
        findings = explain(file, threshold_kbps, None, None,
                           "Sonarr" if file.get("media_type") == "episode" else "Radarr")
    return {
        "rating_key": file.get("rating_key"),
        "title": file.get("title"),
        "media_type": file.get("media_type"),
        "year": file.get("year"),
        "file_bitrate": file.get("file_bitrate"),
        "file_size": file.get("file_size"),
        "plays": file.get("plays"),
        "kind": kind,
        "why": why,
        "store": file.get("store") or name_for(file.get("file_path"), named),
        "finding": (findings[0] or {}).get("title") if findings else None,
        "findings_count": len(findings or []),
    }


def _trouble_why(file: dict[str, Any]) -> str:
    stalls, remote = int(file.get("stalls") or 0), int(file.get("remote_plays") or 0)
    transcodes = int(file.get("remote_transcodes") or 0)
    said = []
    if stalls:
        people = int(file.get("stall_users") or 0)
        said.append(f"stalled {stalls} {'time' if stalls == 1 else 'times'} for {people or 1} {'person' if people <= 1 else 'people'}")
    if remote and transcodes:
        said.append(f"transcoded for {transcodes} of {remote} remote plays")
    elif remote:
        said.append(f"watched remotely {remote} {'time' if remote == 1 else 'times'}")
    return "; ".join(said).capitalize() + "." if said else ""


def _messy_why(file: dict[str, Any]) -> str:
    from app.services.library import ISSUES

    named = [ISSUES.get(key, key.replace("_", " ")) for key in file.get("issues") or []]
    if not named:
        findings = [f.get("title") for f in file.get("findings") or []]
        named = [f for f in findings if f]
    return "; ".join(named[:3]) + ("." if named else "")

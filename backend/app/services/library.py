"""Library health: files judged by how people actually watch them.

Plain inventory is Tautulli's job and conversions are Tdarr's. What is here
needs the viewing history beside the file: a high bitrate only matters if it
is watched remotely, a 4K copy only earns its space if it reaches a 4K screen,
and a request only paid off if the person who asked watched it.
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import History, Library, MediaItem, StreamEvent, StreamSession, User
from app.plays import plays as count_plays
from app.plays import plays_when as count_plays_when

# Audio most TVs and sticks play without help. Anything else in a file with
# none of these is transcoded for most people.
COMPATIBLE_AUDIO = {"aac", "ac3", "eac3", "mp3", "opus", "vorbis", "mp2"}
IMAGE_SUBTITLES = {"pgs", "vobsub", "dvd_subtitle", "hdmv_pgs_subtitle", "dvb_subtitle"}
LEGACY_CONTAINERS = {"avi", "wmv", "asf", "flv", "mpeg", "mpg", "vob", "divx", "ogm", "rm", "rmvb"}

ISSUES: dict[str, str] = {
    "no_compatible_audio": "No audio most devices can play (only TrueHD, DTS or similar)",
    "audio_converted": "Audio was converted for people who watched it",
    "subtitles_burned": "Subtitles were burned in for people who watched it",
    "image_subtitles_only": "Only image subtitles, which are burned in when turned on",
    "styled_subtitles": "Styled (ASS) subtitles, which many devices burn in",
    "subtitle_clutter": "Many duplicate subtitle tracks",
    "untagged_audio": "Several audio tracks, some with no language set",
    "legacy_container": "Old container format",
}


def _tracks(value: str | None) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except ValueError:
        return []


def file_issues(item: MediaItem) -> list[str]:
    """What is awkward about a file, independent of who watches it."""
    return issues_of(item.audio_tracks, item.subtitle_tracks, item.file_container)


def issues_of(audio_tracks: str | None, subtitle_tracks: str | None, container: str | None) -> list[str]:
    """The same question asked of the three columns it actually needs.

    Whole library sweeps read these columns rather than loading every file, so
    the work is here and `file_issues` is the convenience on top.
    """
    issues: list[str] = []
    audio = _tracks(audio_tracks)
    subs = _tracks(subtitle_tracks)
    codecs = {str(a.get("codec") or "").lower() for a in audio}
    if audio and not codecs & COMPATIBLE_AUDIO:
        issues.append("no_compatible_audio")
    sub_codecs = {str(s.get("codec") or "").lower() for s in subs}
    if subs and sub_codecs <= IMAGE_SUBTITLES:
        issues.append("image_subtitles_only")
    if sub_codecs & {"ass", "ssa"}:
        issues.append("styled_subtitles")
    if len(subs) >= 6:
        groups = Counter((str(s.get("codec")), str(s.get("language")), bool(s.get("forced"))) for s in subs)
        if max(groups.values()) >= 3:
            issues.append("subtitle_clutter")
    # Only matters when there is a choice to make: with one track, a missing
    # language changes nothing for anyone.
    if len(audio) > 1 and any(not a.get("language") or str(a.get("language")).lower() in ("und", "unknown", "") for a in audio):
        issues.append("untagged_audio")
    if str(container or "").lower() in LEGACY_CONTAINERS:
        issues.append("legacy_container")
    return issues


_ISSUES_CACHE: dict[int, tuple[Any, tuple[str, ...]]] = {}
"""Worked out issues, kept against the moment the file was last read.

Reading thirty thousand track lists took most of a second every time the page
was opened, for an answer that only changes when the file is read again. The
scan stamps `file_checked_at`, so that is the key: a rescanned file recomputes
itself and nothing else has to be invalidated.
"""


CACHE_LIMIT = 250_000
"""A ceiling, so a library far larger than any of these was written for cannot
quietly become the biggest thing in memory. Past it the whole lot is dropped
and worked out again, which costs one slow page."""


def issues_cached(rating_key: int, checked_at: Any, audio: str | None, subs: str | None, container: str | None) -> list[str]:
    hit = _ISSUES_CACHE.get(rating_key)
    if hit is not None and hit[0] == checked_at:
        return list(hit[1])
    found = issues_of(audio, subs, container)
    if len(_ISSUES_CACHE) >= CACHE_LIMIT:
        _ISSUES_CACHE.clear()
    _ISSUES_CACHE[rating_key] = (checked_at, tuple(found))
    return found


def _title(item: MediaItem) -> str:
    if item.media_type == "episode" and item.media_index is not None and item.parent_media_index is not None:
        show = item.grandparent_title or (item.full_title or "").split(" - ")[0]
        return f"{show} - S{item.parent_media_index:02d}E{item.media_index:02d} - {item.title}"
    return item.full_title or item.title or f"Item {item.rating_key}"


def describe_file(item: MediaItem) -> dict[str, Any]:
    return {
        "rating_key": item.rating_key,
        "title": _title(item),
        "media_type": item.media_type,
        "year": item.year,
        "file_bitrate": item.file_bitrate,
        "file_size": item.file_size,
        "file_container": item.file_container,
        "file_path": item.file_path,
        "versions": item.versions,
        "video_codec": item.video_codec,
        "video_resolution": item.video_resolution,
        "video_bit_depth": item.video_bit_depth,
        "video_dynamic_range": item.video_dynamic_range,
        "audio_codec": item.audio_codec,
        "audio_channels": item.audio_channels,
        "audio_tracks": _tracks(item.audio_tracks),
        "subtitle_tracks": _tracks(item.subtitle_tracks),
        "issues": file_issues(item),
    }


def _since(days: int) -> tuple[int, datetime]:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    return int(cutoff.timestamp()), cutoff


def play_stats(db: Session, days: int, keys: list[int] | None = None) -> dict[int, dict[str, Any]]:
    """Per title: plays, remote plays, remote transcodes, users, last play."""
    since, _ = _since(days)
    remote = History.location == "wan"
    transcode = History.transcode_decision == "transcode"
    stmt = (
        select(
            History.rating_key,
            count_plays(History).label("plays"),
            count_plays_when(History, remote).label("remote"),
            count_plays_when(History, transcode).label("transcodes"),
            count_plays_when(History, remote & transcode).label("remote_transcodes"),
            func.count(func.distinct(History.user_id)).label("users"),
            func.max(History.started).label("last_play"),
        )
        .where(History.started >= since, History.rating_key.is_not(None))
        .group_by(History.rating_key)
    )
    if keys is not None:
        stmt = stmt.where(History.rating_key.in_(keys))
    return {r.rating_key: r._asdict() for r in db.execute(stmt).all()}


def stall_stats(db: Session, days: int) -> dict[int, dict[str, Any]]:
    _, cutoff = _since(days)
    rows = db.execute(
        select(
            StreamEvent.rating_key,
            func.count().label("stalls"),
            func.count(func.distinct(StreamEvent.user_id)).label("stall_users"),
            func.sum(StreamEvent.seconds).label("stall_seconds"),
        )
        .where(StreamEvent.started_at >= cutoff, StreamEvent.rating_key.is_not(None))
        .group_by(StreamEvent.rating_key)
    ).all()
    return {r.rating_key: r._asdict() for r in rows}


def cause_stats(db: Session, days: int) -> dict[int, Counter]:
    _, cutoff = _since(days)
    out: dict[int, Counter] = defaultdict(Counter)
    for key, cause in db.execute(
        select(StreamSession.rating_key, StreamSession.primary_cause).where(
            StreamSession.started_at >= cutoff, StreamSession.primary_cause.is_not(None)
        )
    ).all():
        if key is not None:
            out[key][cause] += 1
    return out


def problem_files(db: Session, threshold_kbps: int, days: int, limit: int = 100) -> list[dict[str, Any]]:
    """Files that cause trouble for the people watching them, worst first.

    A file is listed when it is over the bitrate threshold and watched
    remotely, stalls, or is transcoded for most remote viewers. The score
    weighs a stall as three remote transcodes, since a stall is what someone
    actually notices.
    """
    plays = play_stats(db, days)
    stalls = stall_stats(db, days)
    causes = cause_stats(db, days)
    keys = set(plays) | set(stalls)
    items = {
        i.rating_key: i
        for i in db.execute(select(MediaItem).where(MediaItem.rating_key.in_(keys), MediaItem.title.is_not(None))).scalars()
    }
    out = []
    for key, item in items.items():
        p = plays.get(key, {})
        s = stalls.get(key, {})
        remote = int(p.get("remote") or 0)
        remote_transcodes = int(p.get("remote_transcodes") or 0)
        stall_count = int(s.get("stalls") or 0)
        reasons = []
        over = bool(item.file_bitrate and item.file_bitrate >= threshold_kbps)
        if over and remote:
            reasons.append("over_threshold")
        if stall_count:
            reasons.append("stalls")
        if remote >= 2 and remote_transcodes / remote >= 0.5:
            reasons.append("mostly_transcoded")
        if not reasons:
            continue
        score = remote_transcodes + 3 * stall_count + (remote if over else 0)
        out.append({
            **describe_file(item),
            "plays": int(p.get("plays") or 0),
            "remote_plays": remote,
            "remote_transcodes": remote_transcodes,
            "users": int(p.get("users") or 0),
            "last_play": p.get("last_play"),
            "stalls": stall_count,
            "stall_users": int(s.get("stall_users") or 0),
            "causes": [c for c, _ in causes.get(key, Counter()).most_common()],
            "reasons": reasons,
            "score": score,
        })
        from app.services.findings import explain

        row = out[-1]
        stall_kind = "file" if int(s.get("stall_users") or 0) > 1 else "one_off"
        row["findings"] = explain(
            row,
            threshold_kbps,
            [{"cause": c, "streams": n} for c, n in causes.get(key, Counter()).items()],
            [{"cause": stall_kind, "stalls": stall_count}] if stall_count else [],
            "Sonarr" if item.media_type == "episode" else "Radarr",
        )
        for finding in row["findings"]:
            # The detail card reads the reason back from Tautulli; the list does not wait for that.
            if finding["key"] == "transcoded_unknown":
                finding["title"] = "Usually transcoded, open it for the reason"
    out.sort(key=lambda r: (-r["score"], -(r["file_bitrate"] or 0)))
    return out[:limit]


def transcode_causes(db: Session, days: int) -> dict[str, Any]:
    """Each reason streams were transcoded: how often, on which platforms,
    and which titles most."""
    from app.services.streams import CAUSES

    _, cutoff = _since(days)
    rows = db.execute(
        select(StreamSession.causes, StreamSession.platform, StreamSession.player, StreamSession.rating_key,
               StreamSession.full_title, StreamSession.transcode_hw)
        .where(StreamSession.started_at >= cutoff, StreamSession.causes.is_not(None))
    ).all()
    total = db.execute(select(func.count()).select_from(StreamSession).where(StreamSession.started_at >= cutoff)).scalar() or 0
    by_cause: dict[str, dict[str, Any]] = {}
    for causes, platform, player, key, title, hw in rows:
        for cause in (causes or "").split(","):
            if not cause:
                continue
            entry = by_cause.setdefault(cause, {"streams": 0, "hardware": 0, "platforms": Counter(),
                                                "players": Counter(), "titles": Counter(), "names": {}})
            entry["streams"] += 1
            entry["hardware"] += 1 if hw else 0
            entry["platforms"][platform or "Unknown"] += 1
            # The platform says Android; the device says which stick in which
            # room, which is the one somebody can actually go and change.
            entry["players"][player or "Unknown"] += 1
            if key is not None:
                entry["titles"][key] += 1
                entry["names"][key] = title
    out = []
    for cause, e in by_cause.items():
        out.append({
            "cause": cause,
            "label": CAUSES.get(cause, cause),
            "streams": e["streams"],
            "hardware": e["hardware"],
            "platforms": [{"name": n, "streams": c} for n, c in e["platforms"].most_common(5)],
            "players": [{"name": n, "streams": c} for n, c in e["players"].most_common(5)],
            "titles": [{"rating_key": k, "title": e["names"].get(k), "streams": c} for k, c in e["titles"].most_common(5)],
        })
    out.sort(key=lambda r: -r["streams"])

    # One session can transcode for several reasons, so the per-cause counts
    # add up to more than the number of streams. These are the streams.
    transcoded = len(rows)
    hardware = sum(1 for *_, hw in rows if hw)
    return {
        "total_streams": total,
        "transcoded": transcoded,
        "hardware": hardware,
        "enough_to_judge": transcoded >= ENOUGH_TRANSCODES,
        "causes": out,
    }


ENOUGH_TRANSCODES = 20
"""Below this, "none of them used hardware" is not a finding about the server.

Two software transcodes is a quiet week. Twenty with none of them accelerated
is a setting that has never been turned on, which is worth saying, because
software transcoding spends most of a core on each stream and the same work on
an iGPU is nearly free."""


def observed_trouble(db: Session, days: int) -> dict[int, Counter]:
    """What actually went wrong for the people who watched, by file.

    Reading the tracks tells you a file has DTS and nothing else, which is
    clearly awkward. It does not tell you that a perfectly ordinary AAC 5.1
    track is converted for half the sticks in the house. That only shows up in
    what happened, so it is read from the streams seen live.
    """
    _, cutoff = _since(days)
    out: dict[int, Counter] = {}
    rows = db.execute(
        select(StreamSession.rating_key, StreamSession.causes)
        .where(StreamSession.started_at >= cutoff, StreamSession.causes.is_not(None),
               StreamSession.rating_key.is_not(None))
    ).all()
    for key, causes in rows:
        counted = out.setdefault(int(key), Counter())
        for cause in (causes or "").split(","):
            if cause:
                counted[cause] += 1
    return out


def messy_files(db: Session, days: int, issue: str | None = None, limit: int = 200) -> dict[str, Any]:
    """Files with a known awkwardness, most watched first."""
    from app.services.library_scan import in_library

    # Columns, not whole rows: everything below needs four fields per file,
    # and the files worth describing in full are the handful that are shown.
    scanned = db.execute(
        select(MediaItem.rating_key, MediaItem.file_checked_at, MediaItem.audio_tracks,
               MediaItem.subtitle_tracks, MediaItem.file_container, MediaItem.media_type,
               MediaItem.full_title, MediaItem.title)
        .where(MediaItem.file_checked_at.is_not(None), MediaItem.file_bitrate.is_not(None), in_library())
    ).all()
    seen = observed_trouble(db, days)
    counts: Counter = Counter()
    flagged = []
    for key, checked_at, audio_tracks, subtitle_tracks, container, _media_type, full_title, short in scanned:
        issues = issues_cached(key, checked_at, audio_tracks, subtitle_tracks, container)
        happened = seen.get(key) or Counter()
        # Proof beats prediction. A file whose audio was converted for real
        # viewers belongs here even when its track list looks unremarkable,
        # and it is not listed twice when the track list already said so.
        if (happened.get("audio_codec") or happened.get("audio_channels")) and "no_compatible_audio" not in issues:
            issues = [*issues, "audio_converted"]
        if happened.get("subtitle_burn") and not {"image_subtitles_only", "styled_subtitles"} & set(issues):
            issues = [*issues, "subtitles_burned"]
        for i in issues:
            counts[i] += 1
        if issues and (issue is None or issue in issues):
            flagged.append((key, full_title or short or f"Item {key}", issues))
    plays = play_stats(db, days, [key for key, _, _ in flagged]) if flagged else {}
    from app.services.findings import explain

    # Sorted on what is cheap to know, then described.
    flagged.sort(key=lambda row: (-int((plays.get(row[0]) or {}).get("plays") or 0), row[1]))
    shown = flagged[:limit]
    items = {
        m.rating_key: m
        for m in db.execute(select(MediaItem).where(MediaItem.rating_key.in_([key for key, _, _ in shown]))).scalars()
    }

    rows = []
    for key, _name, issues in shown:
        item = items.get(key)
        if item is None:
            continue
        stats = plays.get(key, {})
        row = {
            **describe_file(item),
            "plays": int(stats.get("plays") or 0),
            "remote_plays": int(stats.get("remote") or 0),
            "transcodes": int(stats.get("transcodes") or 0),
        }
        row["issues"] = issues
        happened = seen.get(key) or Counter()
        causes = [{"cause": c, "streams": n} for c, n in happened.most_common()]
        row["findings"] = explain(row, 10**9, causes or None, None,
                                  "Sonarr" if item.media_type == "episode" else "Radarr")
        rows.append(row)
    return {
        "checked": len(scanned),
        "counts": [{"issue": k, "label": ISSUES[k], "files": counts.get(k, 0)} for k in ISSUES],
        "files": rows,
        "total": len(flagged),
    }


SHOW_SORTS = {
    "size": "Largest first",
    "plays": "Most watched",
    "quiet": "Least watched",
    "title": "Title",
}
"""How a list of shows can be ordered.

Fewer than a list of files, because most of those are about one file: a show
has no bitrate, no resolution and no one container, and offering to sort by
them was offering something that could not work."""


BROWSE_SORTS = {
    "per_hour": "Biggest per hour",
    "bitrate": "Highest bitrate",
    "size": "Largest file",
    "stalls": "Most stalls",
    "transcoded": "Most transcoded",
    "plays": "Most watched",
    "quiet": "Least watched",
    "problems": "Most wrong with it",
    "title": "Title",
}


_ROWS: dict[int, tuple[Any, dict[str, Any]]] = {}
_ROWS_FOR: tuple[Any, ...] | None = None
"""What each file says about itself, against the state it was read in.

Half the cost of the library list was working the same answers out again for
thirty thousand files that had not changed: parsing the audio tracks to list
their languages, formatting an episode title, and matching a path against the
store names. None of that depends on who watched it, so none of it has to be
redone when somebody does.

The key is the three things that change when the file does: when it was last
read, how big it is, and where it is. A tidy clears the first and rewrites the
other two, a scan stamps the first, and a replacement clears it, so anything
that alters a file shows up on the next page load rather than at the next scan.
Renaming a store or changing how much of a path names one changes the whole
cache's stamp instead, since that answer is the same question asked of
different settings.
"""


def _rows_cache(stamp: tuple[Any, ...]) -> dict[int, tuple[Any, dict[str, Any]]]:
    global _ROWS, _ROWS_FOR

    if stamp != _ROWS_FOR:
        _ROWS, _ROWS_FOR = {}, stamp
    return _ROWS


def forget_rows() -> None:
    """Drop the cache outright.

    Nothing in the app calls this and nothing should: the cache is keyed on a
    stamp made of the things that change a row, so a tidy, a scan or a
    replacement already invalidates it by altering one of them. This exists
    for tests, which change files underneath it on purpose, and the
    alternative is a test reaching into module globals."""
    global _ROWS_FOR

    _ROWS.clear()
    _ROWS_FOR = None


NOTHING_SEEN: dict[str, int] = {}
"""Shared, because most files have had no trouble and building a Counter each
time to answer `.get()` with None is thirty thousand allocations a request."""


BROWSE_COLUMNS = (
    MediaItem.rating_key,
    MediaItem.title,
    MediaItem.full_title,
    MediaItem.grandparent_title,
    MediaItem.media_index,
    MediaItem.parent_media_index,
    MediaItem.media_type,
    MediaItem.year,
    MediaItem.section_id,
    MediaItem.duration,
    MediaItem.video_resolution,
    MediaItem.file_bitrate,
    MediaItem.file_size,
    MediaItem.file_container,
    MediaItem.file_path,
    MediaItem.file_checked_at,
    MediaItem.audio_tracks,
    MediaItem.subtitle_tracks,
)
"""What a row of the library list is made of: eighteen columns of thirty nine.

Selected by name rather than as whole MediaItem objects. The page reads these
and nothing else, and the rest includes every plot summary in the library,
which was being read off disk, built into an object and thrown away thirty
thousand times a request. Measured on a library of this size, the same rows
cost 512 ms as objects and 199 ms as columns, most of the difference being
SQLAlchemy instrumenting attributes nobody asks for.

The rows still answer to `row.file_size` and the like, so everything that
reads them is unchanged."""


def shows(
    db: Session,
    days: int,
    section_id: int | None = None,
    search: str | None = None,
    stores: list[str] | None = None,
    sort: str = "title",
    limit: int = 500,
) -> dict[str, Any]:
    """Every show, from its episodes.

    There is no row for a show: it has no file and takes up no room, so the
    scan does not store one. What it has is episodes that all name the same
    grandparent, which is the show, so the show is a GROUP BY rather than a
    thing to go and fetch.
    """
    from app.services.library_scan import in_library

    where = [
        MediaItem.media_type == "episode",
        MediaItem.grandparent_rating_key.is_not(None),
        in_library(),
    ]
    if section_id is not None:
        where.append(MediaItem.section_id == section_id)
    if search:
        where.append(func.lower(MediaItem.grandparent_title).like(f"%{search.lower()}%"))

    rows = db.execute(
        select(
            MediaItem.grandparent_rating_key.label("rating_key"),
            func.max(MediaItem.grandparent_title).label("title"),
            func.max(MediaItem.section_id).label("section_id"),
            func.count().label("episodes"),
            func.count(func.distinct(MediaItem.parent_media_index)).label("seasons"),
            func.coalesce(func.sum(MediaItem.file_size), 0).label("file_size"),
            func.coalesce(func.sum(MediaItem.duration), 0).label("ms"),
            func.min(MediaItem.year).label("year"),
            # Any one of its episodes. A show mostly has no row of its own, so
            # anything that has to look the show up in Radarr or Sonarr goes
            # through an episode, which resolves to the series.
            func.min(MediaItem.rating_key).label("episode_key"),
        )
        .where(*where)
        .group_by(MediaItem.grandparent_rating_key)
    ).all()

    # Plays are counted against episodes, so a show's plays are its episodes'.
    since, _ = _since(days)
    played = dict(
        db.execute(
            select(MediaItem.grandparent_rating_key, count_plays(History))
            .join(History, History.rating_key == MediaItem.rating_key)
            .where(MediaItem.media_type == "episode", History.started >= since,
                   MediaItem.grandparent_rating_key.is_not(None))
            .group_by(MediaItem.grandparent_rating_key)
        ).all()
    )

    sections = {s.section_id: s.name for s in db.execute(select(Library)).scalars()}

    # Where each show's episodes sit. A show has no file of its own, so this
    # is the only way it has a place at all, and one part way through a move
    # has two. A second query rather than a column on the grouping above,
    # because a group can only carry one of several paths and the answer here
    # is all of them.
    from app.services.stores import labels, name_for

    named = labels()
    lives: dict[int, set[str]] = {}
    for key, path in db.execute(
        select(MediaItem.grandparent_rating_key, MediaItem.file_path).where(
            *where, MediaItem.file_path.is_not(None)
        )
    ).all():
        where_it_is = name_for(path, named)
        if where_it_is:
            lives.setdefault(key, set()).add(where_it_is)

    all_stores = {name for places in lives.values() for name in places}
    wanted_stores = {s for s in (stores or []) if s}

    out = [
        {
            "rating_key": r.rating_key,
            "title": r.title or f"Show {r.rating_key}",
            "episodes": r.episodes,
            "seasons": r.seasons,
            "file_size": int(r.file_size or 0),
            "hours": round((r.ms or 0) / 3_600_000, 2),
            "year": r.year,
            "section_id": r.section_id,
            "library": sections.get(r.section_id),
            "plays": int(played.get(r.rating_key) or 0),
            "stores": sorted(lives.get(r.rating_key, set())),
            "episode_key": r.episode_key,
        }
        for r in rows
        # Any episode in a ticked place is enough. The point of ticking is to
        # find what to move off a disk, and a show with one episode left on it
        # is still something on it.
        if not wanted_stores or (wanted_stores & lives.get(r.rating_key, set()))
    ]
    out.sort(key={
        "size": lambda s: -(s["file_size"] or 0),
        "plays": lambda s: -s["plays"],
        "quiet": lambda s: (s["plays"], -(s["file_size"] or 0)),
        "title": lambda s: (s["title"] or "").lower(),
    }.get(sort, lambda s: (s["title"] or "").lower()))
    return {
        "items": out[:limit],
        "total": len(out),
        # The same shape the file list answers with, so the controls above
        # either list work without knowing which one is showing.
        "sort": sort if sort in SHOW_SORTS else "title",
        "sorts": [{"key": key, "label": label} for key, label in SHOW_SORTS.items()],
        "sections": libraries_holding(db, "episode"),
        # Every place a show could be, worked out before any was dropped for
        # being in the wrong one.
        "stores": sorted(all_stores),
    }


def seasons(db: Session, show_key: int, days: int) -> dict[str, Any]:
    """One show's seasons, from the same place."""
    from app.services.library_scan import in_library

    where = [
        MediaItem.media_type == "episode",
        MediaItem.grandparent_rating_key == show_key,
        in_library(),
    ]
    rows = db.execute(
        select(
            MediaItem.parent_media_index.label("season"),
            # Its own key, so the season has a poster of its own.
            func.max(MediaItem.parent_rating_key).label("rating_key"),
            func.count().label("episodes"),
            func.coalesce(func.sum(MediaItem.file_size), 0).label("file_size"),
            func.coalesce(func.sum(MediaItem.duration), 0).label("ms"),
            func.max(MediaItem.grandparent_title).label("title"),
            func.max(MediaItem.section_id).label("section_id"),
        )
        .where(*where)
        .group_by(MediaItem.parent_media_index)
        .order_by(MediaItem.parent_media_index)
    ).all()
    if not rows:
        return {"title": None, "rating_key": show_key, "seasons": []}

    since, _ = _since(days)
    played = dict(
        db.execute(
            select(MediaItem.parent_media_index, count_plays(History))
            .join(History, History.rating_key == MediaItem.rating_key)
            .where(MediaItem.grandparent_rating_key == show_key, History.started >= since)
            .group_by(MediaItem.parent_media_index)
        ).all()
    )
    return {
        "rating_key": show_key,
        "title": rows[0].title,
        "section_id": rows[0].section_id,
        "seasons": [
            {
                "season": r.season,
                "rating_key": r.rating_key,
                "episodes": r.episodes,
                "file_size": int(r.file_size or 0),
                "hours": round((r.ms or 0) / 3_600_000, 2),
                "plays": int(played.get(r.season) or 0),
            }
            for r in rows
        ],
    }


def libraries_holding(db: Session, media_type: str | None) -> list[dict[str, Any]]:
    """The libraries that actually hold this kind of thing.

    Every library on the server was offered whatever was being browsed, so
    looking at films offered TV/Series and Music, and picking one asked for
    films in a library that has none. Asked without the library filter
    applied, so picking one does not remove the others.
    """
    from app.services.library_scan import in_library

    where = [in_library()]
    if media_type:
        where.append(MediaItem.media_type == media_type)
    here = set(
        db.execute(select(MediaItem.section_id).where(*where).distinct()).scalars()
    )
    return [
        {"section_id": s.section_id, "name": s.name}
        for s in db.execute(select(Library).order_by(Library.section_id)).scalars()
        if s.name and s.section_id in here
    ]


def browse(
    db: Session,
    days: int,
    sort: str = "per_hour",
    min_gb_per_hour: float = 0.0,
    min_bitrate_kbps: int = 0,
    resolution: str | None = None,
    section_id: int | None = None,
    language: str | None = None,
    media_type: str | None = None,
    problem: str | None = None,
    search: str | None = None,
    show: int | None = None,
    season: int | None = None,
    stores: list[str] | None = None,
    limit: int = 120,
    offset: int = 0,
) -> dict[str, Any]:
    """The library as something to look through, with what is wrong on each.

    One list behind both the table and the poster wall. Everything a tile shows
    comes from what has already been read: the tracks, the plays, the stalls,
    the live streams. Nothing here asks Plex anything.

    Sorted by size per hour unless asked otherwise, because that is the one
    measure that compares a three hour film with a forty minute cartoon.
    """
    from app.services.library_scan import in_library
    from app.services.stores import labels, name_for
    from app.settings_store import current

    # The filters that are columns are asked of the database; the ones that
    # need a track list parsed are left to the loop below. Browsing the films
    # should not read the episodes.
    where = [MediaItem.file_size.is_not(None), MediaItem.file_size > 0, in_library()]
    if media_type:
        where.append(MediaItem.media_type == media_type)
    if section_id is not None:
        where.append(MediaItem.section_id == section_id)
    if resolution:
        where.append(func.lower(MediaItem.video_resolution) == resolution.lower())
    if min_bitrate_kbps:
        where.append(MediaItem.file_bitrate >= min_bitrate_kbps)
    if search:
        where.append(func.lower(MediaItem.full_title).like(f"%{search.lower()}%"))
    # One show, or one season of it, for browsing television the way it is
    # arranged rather than as twenty six thousand loose episodes.
    if show is not None:
        where.append(MediaItem.grandparent_rating_key == show)
    if season is not None:
        where.append(MediaItem.parent_media_index == season)
    rows = db.execute(select(*BROWSE_COLUMNS).where(*where)).all()
    plays = play_stats(db, days)
    stalls = stall_stats(db, days)
    seen = observed_trouble(db, days)
    named = labels()
    sections = {s.section_id: s.name for s in db.execute(select(Library)).scalars()}
    settings = current()
    threshold = int(settings.library_bitrate_threshold_mbps * 1000)
    # Everything cached below was worked out against these, so a change to
    # either is a different answer and the whole lot is dropped.
    cache = _rows_cache((tuple(sorted(named.items())), settings.library_store_depth))

    out = []
    # Every store the rows could come from, collected before any of them are
    # dropped for being in the wrong one. Narrowing a list must not remove the
    # options for narrowing it: tick one location and the others vanishing is
    # a filter nobody can use twice.
    all_stores: set[str] = set()
    wanted_stores = {s for s in (stores or []) if s}
    for item in rows:
        known = cache.get(item.rating_key)
        stamp = (item.file_checked_at, item.file_size, item.file_path)
        if known is not None and known[0] == stamp:
            about = known[1]
        else:
            hours = (item.duration or 0) / 3_600_000
            about = {
                "rating_key": item.rating_key,
                "title": _title(item),
                "year": item.year,
                "media_type": item.media_type,
                "video_resolution": item.video_resolution,
                "file_bitrate": item.file_bitrate,
                "file_size": item.file_size,
                "file_container": item.file_container,
                "gb_per_hour": round(((item.file_size or 0) / 1e9 / hours) if hours > 0 else 0.0, 2),
                "hours": round(hours, 2),
                "languages": sorted({
                    str(track.get("language") or "").lower()
                    for track in _tracks(item.audio_tracks)
                    if track.get("language")
                }),
                "section_id": item.section_id,
                "store": name_for(item.file_path, named),
            }
            if len(cache) < CACHE_LIMIT:
                cache[item.rating_key] = (stamp, about)

        if about["store"]:
            all_stores.add(about["store"])
        if wanted_stores and about["store"] not in wanted_stores:
            continue
        if min_gb_per_hour and about["gb_per_hour"] < min_gb_per_hour:
            continue
        if language and language.lower() not in about["languages"]:
            continue
        stat = plays.get(item.rating_key, {})
        stall = stalls.get(item.rating_key, {})
        happened = seen.get(item.rating_key) or NOTHING_SEEN
        total_plays = int(stat.get("plays") or 0)
        remote = int(stat.get("remote") or 0)
        remote_transcodes = int(stat.get("remote_transcodes") or 0)
        tracks = issues_cached(item.rating_key, item.file_checked_at, item.audio_tracks,
                               item.subtitle_tracks, item.file_container)

        # The markers a tile can show at a glance. Each one is something the
        # app can already prove, not a guess from the file name.
        marks = []
        if int(stall.get("stalls") or 0):
            marks.append("stalls")
        if remote >= 2 and remote_transcodes / remote >= 0.5:
            marks.append("transcoded")
        if item.file_bitrate and item.file_bitrate >= threshold and remote:
            marks.append("heavy")
        if "no_compatible_audio" in tracks or happened.get("audio_codec") or happened.get("audio_channels"):
            marks.append("audio")
        if {"image_subtitles_only", "styled_subtitles", "subtitle_clutter"} & set(tracks) or happened.get("subtitle_burn"):
            marks.append("subtitles")
        if "legacy_container" in tracks:
            marks.append("container")
        if total_plays == 0:
            marks.append("unwatched")
        if problem and problem not in marks:
            continue

        out.append({
            **about,
            "section": sections.get(item.section_id),
            "plays": total_plays,
            "remote_plays": remote,
            "last_play": stat.get("last_play"),
            "stalls": int(stall.get("stalls") or 0),
            "transcode_percent": round(remote_transcodes / remote * 100) if remote else 0,
            "marks": marks,
        })

    order = {
        "per_hour": lambda r: -r["gb_per_hour"],
        "bitrate": lambda r: -(r["file_bitrate"] or 0),
        "size": lambda r: -(r["file_size"] or 0),
        "stalls": lambda r: -r["stalls"],
        "transcoded": lambda r: -r["transcode_percent"],
        "plays": lambda r: -r["plays"],
        "quiet": lambda r: (r["plays"], -(r["file_size"] or 0)),
        "problems": lambda r: -len(r["marks"]),
        "title": lambda r: r["title"].lower(),
    }.get(sort, lambda r: -r["gb_per_hour"])
    out.sort(key=order)

    start = max(0, offset)
    return {
        "items": out[start:start + limit],
        "total": len(out),
        # Where the shown rows start, so a page asking for more knows what it
        # already has rather than counting its own list and hoping.
        "offset": start,
        "size": sum(r["file_size"] or 0 for r in out),
        "sort": sort if sort in BROWSE_SORTS else "per_hour",
        "sorts": [{"key": key, "label": label} for key, label in BROWSE_SORTS.items()],
        "sections": libraries_holding(db, media_type),
        "languages": sorted({lang for row in out for lang in row["languages"]}),
        "resolutions": sorted({str(row["video_resolution"] or "").lower() for row in out if row["video_resolution"]}),
        "marks": sorted({mark for row in out for mark in row["marks"]}),
        # Named `stores` to match the Storage page, which calls the same thing
        # a store. These are the locations a library sits on.
        "stores": sorted(all_stores),
    }


def oversized(
    db: Session,
    days: int,
    min_gb_per_hour: float = 0.0,
    min_bitrate_kbps: int = 0,
    resolution: str | None = None,
    section_id: int | None = None,
    language: str | None = None,
    media_type: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Biggest per hour first. The same list as browse, named for the question
    the Big for what they are page asks."""
    answer = browse(
        db, days, sort="per_hour", min_gb_per_hour=min_gb_per_hour, min_bitrate_kbps=min_bitrate_kbps,
        resolution=resolution, section_id=section_id, language=language, media_type=media_type, limit=limit,
    )
    # That page only lists things with a length to divide by.
    answer["items"] = [row for row in answer["items"] if row["gb_per_hour"] > 0]
    return answer


def four_k(db: Session, days: int) -> list[dict[str, Any]]:
    """4K files and whether a 4K picture ever reaches anyone.

    From history: how often each is transcoded (for 4K that nearly always
    means scaled down). From live streams where recorded: what resolution was
    actually sent.
    """
    from app.services.library_scan import in_library

    items = db.execute(
        select(MediaItem).where(func.lower(MediaItem.video_resolution).in_(("4k", "2160", "2160p")), in_library())
    ).scalars().all()
    if not items:
        return []
    keys = [i.rating_key for i in items]
    plays = play_stats(db, days, keys)
    _, cutoff = _since(days)
    sent = defaultdict(Counter)
    for key, res in db.execute(
        select(StreamSession.rating_key, StreamSession.stream_video_resolution)
        .where(StreamSession.rating_key.in_(keys), StreamSession.started_at >= cutoff)
    ).all():
        sent[key][str(res or "unknown").lower()] += 1
    out = []
    for item in items:
        p = plays.get(item.rating_key, {})
        n = int(p.get("plays") or 0)
        transcodes = int(p.get("transcodes") or 0)
        live = sent.get(item.rating_key, Counter())
        live_total = sum(live.values())
        in_4k = sum(c for r, c in live.items() if r in ("4k", "2160", "2160p"))
        if n == 0:
            verdict = "unwatched"
        elif live_total and in_4k == 0:
            verdict = "never_4k"
        elif transcodes / n >= 0.6:
            verdict = "mostly_downscaled"
        else:
            verdict = "benefits"
        out.append({
            **describe_file(item),
            "plays": n,
            "transcodes": transcodes,
            "remote_plays": int(p.get("remote") or 0),
            "users": int(p.get("users") or 0),
            "last_play": p.get("last_play"),
            "streams_seen": live_total,
            "streams_in_4k": in_4k,
            "verdict": verdict,
        })
    order = {"never_4k": 0, "mostly_downscaled": 1, "unwatched": 2, "benefits": 3}
    out.sort(key=lambda r: (order[r["verdict"]], -(r["file_size"] or 0)))
    return out


async def unwatched_requests(db: Session | None = None, max_requests: int = 2000) -> dict[str, Any]:
    """Requests that became available and the requester never watched.

    Seerr is read asynchronously, then everything else runs in a worker
    thread with bulk queries. It used to query the database twice per
    request on the event loop, which with a few thousand requests froze the
    whole app, not just this page.
    """
    import asyncio

    from app.integrations.seerr import seerr

    if not seerr.configured():
        return {"configured": False, "requests": []}
    requests = await seerr.all_requests(max_requests)
    return await asyncio.to_thread(match_requests, requests)


def _request_links(item: MediaItem | None, tmdb_id: Any, media_type: str | None, rating_key: int) -> dict[str, str]:
    """Where a request can be opened. Built from what is already known, so a
    missing id means no button rather than one that goes nowhere."""
    from urllib.parse import quote

    from app.integrations.seerr import seerr
    from app.services import capabilities
    from app.settings_store import current

    settings = current()
    links: dict[str, str] = {}
    kind = "tv" if (media_type or "").lower() in ("tv", "show", "season", "episode") else "movie"

    # Only worth offering when the library actually has it: a Plex link to a
    # key Plex no longer knows lands on an error.
    if item is not None:
        server = settings.plex_machine_identifier or (capabilities.get().get("machine_identifier") or "")
        if server:
            links["plex"] = (
                f"https://app.plex.tv/desktop/#!/server/{server}"
                f"/details?key=%2Flibrary%2Fmetadata%2F{item.rating_key}"
            )
        if item.imdb_id:
            links["imdb"] = f"https://www.imdb.com/title/{item.imdb_id}/"

    tmdb = tmdb_id or (item.tmdb_id if item is not None else None)
    if tmdb:
        links["tmdb"] = f"https://www.themoviedb.org/{kind}/{tmdb}"
        if seerr.configured():
            links["seerr"] = f"{seerr.link_base}/{kind}/{tmdb}"
    title = item.title if item is not None else None
    if title:
        links["trakt"] = f"https://app.trakt.tv/search?query={quote(title)}"
    return links


def match_requests(requests: list[dict[str, Any]]) -> dict[str, Any]:
    from app.db import session_scope

    wanted: list[tuple[dict, int]] = []
    for r in requests:
        media = r.get("media") or {}
        key = media.get("ratingKey4k") if r.get("is4k") else media.get("ratingKey")
        try:
            key = int(key) if key is not None else None
        except (TypeError, ValueError):
            key = None
        # 5 is available, 4 partly available, in Seerr's media status.
        if media.get("status") in (4, 5) and key is not None:
            wanted.append((r, key))
    keys = sorted({k for _, k in wanted})

    with session_scope() as db:
        by_name: dict[str, int] = {}
        for u in db.execute(select(User.user_id, User.username, User.email, User.friendly_name)).all():
            for v in (u.username, u.email, u.friendly_name):
                if v:
                    by_name[str(v).strip().lower()] = u.user_id

        # Everyone who played each title, a show counting its episodes. One
        # pass per column in chunks, so each lookup can use an index.
        watchers: dict[int, set[int]] = defaultdict(set)
        for column in (History.rating_key, History.parent_rating_key, History.grandparent_rating_key):
            for i in range(0, len(keys), 500):
                chunk = keys[i : i + 500]
                for key, uid in db.execute(
                    select(column, History.user_id).where(column.in_(chunk), History.user_id.is_not(None)).distinct()
                ).all():
                    watchers[key].add(uid)

        items: dict[int, MediaItem] = {}
        for i in range(0, len(keys), 500):
            for item in db.execute(select(MediaItem).where(MediaItem.rating_key.in_(keys[i : i + 500]))).scalars():
                items[item.rating_key] = item

        # A title Plex no longer has may still be findable by its TMDB id,
        # which is the same film under a key that changed. Never an episode's:
        # that is TMDB's id for the episode, a different number space from the
        # film or show a request names, and the Plex scan fills one in for
        # every episode in the library, so a coincidence would find one.
        by_tmdb: dict[str, MediaItem] = {}
        tmdb_wanted = {str(r.get("media", {}).get("tmdbId")) for r, _ in wanted if (r.get("media") or {}).get("tmdbId")}
        if tmdb_wanted:
            for item in db.execute(
                select(MediaItem).where(MediaItem.tmdb_id.in_(sorted(tmdb_wanted)), MediaItem.media_type != "episode")
            ).scalars():
                if item.tmdb_id:
                    by_tmdb.setdefault(str(item.tmdb_id), item)

        now = time.time()
        # One row per title, not per request: two people asking for the same
        # film is one film, and it was appearing twice.
        merged: dict[int, dict[str, Any]] = {}
        out = []
        for r, key in wanted:
            media = r.get("media") or {}
            who = r.get("requestedBy") or {}
            user_id = next(
                (by_name[str(v).strip().lower()] for v in (who.get("plexUsername"), who.get("email"), who.get("displayName"))
                 if v and str(v).strip().lower() in by_name),
                None,
            )
            seen_by = watchers.get(key, set())
            if user_id is not None and user_id in seen_by:
                continue
            added = media.get("mediaAddedAt") or r.get("updatedAt")
            try:
                added_ts = datetime.fromisoformat(str(added).replace("Z", "+00:00")).timestamp() if added else None
            except ValueError:
                added_ts = None
            item = items.get(key)
            # Nothing in the library under that key. Seerr may still be right
            # that it was here once, so the id is tried as well.
            found_by_id = None
            if item is None and (media.get("tmdbId") is not None):
                found_by_id = by_tmdb.get(str(media.get("tmdbId")))
            named = item or found_by_id

            seen = merged.get(key)
            if seen is not None:
                # Another request for the same thing. Keep the row, add the
                # person, and let the longest wait stand.
                who_now = who.get("displayName") or who.get("plexUsername") or who.get("email")
                if who_now and who_now not in seen["requested_by_all"]:
                    seen["requested_by_all"].append(who_now)
                continue

            row = {
                "rating_key": key,
                "title": _title(named) if named is not None and named.title else None,
                # Whether the library actually has it. Seerr saying available
                # and the library having nothing is a different problem from
                # nobody having watched it, and the page says which.
                "in_library": item is not None,
                "matched_by_id": item is None and found_by_id is not None,
                "media_type": media.get("mediaType"),
                "tmdb_id": media.get("tmdbId"),
                "requested_by": who.get("displayName") or who.get("plexUsername") or who.get("email"),
                "user_id": user_id,
                "requested_at": r.get("createdAt"),
                "available_days": int((now - added_ts) / 86400) if added_ts else None,
                "watched_by_others": len(seen_by - {user_id}),
                "file_size": named.file_size if named is not None else None,
                "links": _request_links(named, media.get("tmdbId"), media.get("mediaType"), key),
            }
            row["requested_by_all"] = [row["requested_by"]] if row["requested_by"] else []
            merged[key] = row
            out.append(row)

    for row in out:
        people = row.pop("requested_by_all", [])
        if len(people) > 1:
            row["requested_by"] = people[0]
            row["also_requested_by"] = people[1:]

    out.sort(key=lambda x: -(x["available_days"] or 0))
    return {
        "configured": True,
        "requests": [r for r in out if r["in_library"]],
        # Seerr says these arrived; the library has no such file. Either it was
        # removed, or the status is stale.
        "missing": [r for r in out if not r["in_library"]],
    }


def playback_summary(db: Session, days: int, user_id: int | None = None, machine_id: str | None = None) -> dict[str, Any]:
    """How streams play for one person or one device: how often they
    transcode and why, how often they stall and what is likely to blame, and
    the titles that stall most. Answers "is it their device?" in one place."""
    from app.services.stalls import CAUSES as STALL_CAUSES
    from app.services.streams import CAUSES as TRANSCODE_CAUSES

    since, cutoff = _since(days)

    def narrow(stmt, model):
        if user_id is not None:
            stmt = stmt.where(model.user_id == user_id)
        if machine_id is not None:
            stmt = stmt.where(model.machine_id == machine_id)
        return stmt

    plays, transcoded = db.execute(
        narrow(
            select(count_plays(History), count_plays_when(History, History.transcode_decision == "transcode"))
            .where(History.started >= since),
            History,
        )
    ).one()
    sessions = db.execute(
        narrow(select(StreamSession.causes, StreamSession.transcode_hw).where(StreamSession.started_at >= cutoff), StreamSession)
    ).all()
    causes: Counter = Counter()
    for text, _hw in sessions:
        for c in (text or "").split(","):
            if c:
                causes[c] += 1
    stall_rows = db.execute(
        narrow(
            select(StreamEvent.cause, func.count(), func.sum(StreamEvent.seconds))
            .where(StreamEvent.started_at >= cutoff)
            .group_by(StreamEvent.cause),
            StreamEvent,
        )
    ).all()
    stalled_titles = db.execute(
        narrow(
            select(StreamEvent.rating_key, func.max(StreamEvent.full_title), func.count())
            .where(StreamEvent.started_at >= cutoff, StreamEvent.rating_key.is_not(None))
            .group_by(StreamEvent.rating_key)
            .order_by(func.count().desc())
            .limit(5),
            StreamEvent,
        )
    ).all()
    stalls = sum(n for _, n, _ in stall_rows)
    # A stall recorded without its title still has its key, and the library
    # knows the name: "item 4103" is not something anybody can recognise.
    unnamed = [k for k, t, _ in stalled_titles if not t]
    named = dict(
        db.execute(
            select(MediaItem.rating_key, func.coalesce(MediaItem.full_title, MediaItem.title))
            .where(MediaItem.rating_key.in_(unnamed))
        ).all()
    ) if unnamed else {}
    return {
        "days": days,
        "plays": int(plays or 0),
        "transcoded": int(transcoded or 0),
        "streams_recorded": len(sessions),
        "hardware": sum(1 for _, hw in sessions if hw),
        "transcode_causes": [
            {"cause": c, "label": TRANSCODE_CAUSES.get(c, c), "streams": n} for c, n in causes.most_common()
        ],
        "stalls": stalls,
        "stall_minutes": round(sum(float(sec or 0) for _, _, sec in stall_rows) / 60, 1),
        "stall_causes": [
            {"cause": c or "one_off", "label": STALL_CAUSES.get(c or "one_off", c), "stalls": n}
            for c, n, _ in sorted(stall_rows, key=lambda r: -r[1])
        ],
        "stalled_titles": [{"rating_key": k, "title": t or named.get(k), "stalls": n} for k, t, n in stalled_titles],
    }

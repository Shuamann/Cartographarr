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

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import History, MediaItem, StreamEvent, StreamSession, User

# Audio most TVs and sticks play without help. Anything else in a file with
# none of these is transcoded for most people.
COMPATIBLE_AUDIO = {"aac", "ac3", "eac3", "mp3", "opus", "vorbis", "mp2"}
IMAGE_SUBTITLES = {"pgs", "vobsub", "dvd_subtitle", "hdmv_pgs_subtitle", "dvb_subtitle"}
LEGACY_CONTAINERS = {"avi", "wmv", "asf", "flv", "mpeg", "mpg", "vob", "divx", "ogm", "rm", "rmvb"}

ISSUES: dict[str, str] = {
    "no_compatible_audio": "No audio most devices can play (only TrueHD, DTS or similar)",
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
    issues: list[str] = []
    audio = _tracks(item.audio_tracks)
    subs = _tracks(item.subtitle_tracks)
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
    if str(item.file_container or "").lower() in LEGACY_CONTAINERS:
        issues.append("legacy_container")
    return issues


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
            func.count().label("plays"),
            func.sum(case((remote, 1), else_=0)).label("remote"),
            func.sum(case((transcode, 1), else_=0)).label("transcodes"),
            func.sum(case((remote & transcode, 1), else_=0)).label("remote_transcodes"),
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
    out.sort(key=lambda r: (-r["score"], -(r["file_bitrate"] or 0)))
    return out[:limit]


def transcode_causes(db: Session, days: int) -> dict[str, Any]:
    """Each reason streams were transcoded: how often, on which platforms,
    and which titles most."""
    from app.services.streams import CAUSES

    _, cutoff = _since(days)
    rows = db.execute(
        select(StreamSession.causes, StreamSession.platform, StreamSession.rating_key, StreamSession.full_title,
               StreamSession.transcode_hw)
        .where(StreamSession.started_at >= cutoff, StreamSession.causes.is_not(None))
    ).all()
    total = db.execute(select(func.count()).select_from(StreamSession).where(StreamSession.started_at >= cutoff)).scalar() or 0
    by_cause: dict[str, dict[str, Any]] = {}
    for causes, platform, key, title, hw in rows:
        for cause in (causes or "").split(","):
            if not cause:
                continue
            entry = by_cause.setdefault(cause, {"streams": 0, "hardware": 0, "platforms": Counter(), "titles": Counter(), "names": {}})
            entry["streams"] += 1
            entry["hardware"] += 1 if hw else 0
            entry["platforms"][platform or "Unknown"] += 1
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
            "titles": [{"rating_key": k, "title": e["names"].get(k), "streams": c} for k, c in e["titles"].most_common(5)],
        })
    out.sort(key=lambda r: -r["streams"])
    return {"total_streams": total, "causes": out}


def messy_files(db: Session, days: int, issue: str | None = None, limit: int = 200) -> dict[str, Any]:
    """Files with a known awkwardness, most watched first."""
    items = db.execute(
        select(MediaItem).where(MediaItem.file_checked_at.is_not(None), MediaItem.file_bitrate.is_not(None))
    ).scalars().all()
    counts: Counter = Counter()
    flagged = []
    for item in items:
        issues = file_issues(item)
        for i in issues:
            counts[i] += 1
        if issues and (issue is None or issue in issues):
            flagged.append((item, issues))
    plays = play_stats(db, days, [i.rating_key for i, _ in flagged]) if flagged else {}
    rows = [
        {**describe_file(item), "plays": int(plays.get(item.rating_key, {}).get("plays") or 0)}
        for item, _ in flagged
    ]
    rows.sort(key=lambda r: (-r["plays"], r["title"]))
    return {
        "checked": len(items),
        "counts": [{"issue": k, "label": ISSUES[k], "files": counts.get(k, 0)} for k in ISSUES],
        "files": rows[:limit],
        "total": len(rows),
    }


def four_k(db: Session, days: int) -> list[dict[str, Any]]:
    """4K files and whether a 4K picture ever reaches anyone.

    From history: how often each is transcoded (for 4K that nearly always
    means scaled down). From live streams where recorded: what resolution was
    actually sent.
    """
    items = db.execute(
        select(MediaItem).where(func.lower(MediaItem.video_resolution).in_(("4k", "2160", "2160p")))
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


async def unwatched_requests(db: Session, max_requests: int = 2000) -> dict[str, Any]:
    """Requests that became available and the requester never watched."""
    from app.integrations.seerr import seerr

    if not seerr.configured():
        return {"configured": False, "requests": []}
    requests = await seerr.all_requests(max_requests)
    users = db.execute(select(User.user_id, User.username, User.email, User.friendly_name)).all()
    by_name: dict[str, int] = {}
    for u in users:
        for v in (u.username, u.email, u.friendly_name):
            if v:
                by_name[str(v).strip().lower()] = u.user_id
    now = time.time()
    out = []
    for r in requests:
        media = r.get("media") or {}
        key = media.get("ratingKey4k") if r.get("is4k") else media.get("ratingKey")
        try:
            key = int(key) if key is not None else None
        except (TypeError, ValueError):
            key = None
        # 5 is available, 4 partly available, in Seerr's media status.
        if media.get("status") not in (4, 5) or key is None:
            continue
        who = r.get("requestedBy") or {}
        user_id = next(
            (by_name[str(v).strip().lower()] for v in (who.get("plexUsername"), who.get("email"), who.get("displayName"))
             if v and str(v).strip().lower() in by_name),
            None,
        )
        watched_by = db.execute(
            select(func.count(func.distinct(History.user_id))).where(
                (History.rating_key == key) | (History.parent_rating_key == key) | (History.grandparent_rating_key == key)
            )
        ).scalar() or 0
        requester_plays = 0
        if user_id is not None:
            requester_plays = db.execute(
                select(func.count()).select_from(History).where(
                    History.user_id == user_id,
                    (History.rating_key == key) | (History.parent_rating_key == key) | (History.grandparent_rating_key == key),
                )
            ).scalar() or 0
        if requester_plays:
            continue
        added = media.get("mediaAddedAt") or r.get("updatedAt")
        try:
            added_ts = datetime.fromisoformat(str(added).replace("Z", "+00:00")).timestamp() if added else None
        except ValueError:
            added_ts = None
        item = db.get(MediaItem, key)
        out.append({
            "rating_key": key,
            "title": _title(item) if item is not None and item.title else None,
            "media_type": media.get("mediaType"),
            "tmdb_id": media.get("tmdbId"),
            "requested_by": who.get("displayName") or who.get("plexUsername") or who.get("email"),
            "user_id": user_id,
            "requested_at": r.get("createdAt"),
            "available_days": int((now - added_ts) / 86400) if added_ts else None,
            "watched_by_others": watched_by,
            "file_size": item.file_size if item is not None else None,
        })
    out.sort(key=lambda x: -(x["available_days"] or 0))
    return {"configured": True, "requests": out}

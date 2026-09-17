"""Library health. Admin only: file paths and who watches what."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, func, select

from app.auth.deps import AdminUser
from app.models import History, MediaItem, StreamEvent, StreamSession
from app.routers.data import Db
from app.services import library
from app.settings_store import current

router = APIRouter(prefix="/api/library")

Days = Query(90, ge=1, le=3650)


@router.get("/overview")
def overview(_: AdminUser, db: Db) -> dict:
    playable = MediaItem.media_type.in_(("movie", "episode"))
    total = db.execute(select(func.count()).select_from(MediaItem).where(playable, MediaItem.title.is_not(None))).scalar() or 0
    checked = db.execute(
        select(func.count()).select_from(MediaItem).where(playable, MediaItem.file_checked_at.is_not(None))
    ).scalar() or 0
    size = db.execute(select(func.sum(MediaItem.file_size))).scalar() or 0
    resolutions = db.execute(
        select(MediaItem.video_resolution, func.count(), func.sum(MediaItem.file_size))
        .where(MediaItem.file_bitrate.is_not(None))
        .group_by(MediaItem.video_resolution)
        .order_by(func.count().desc())
    ).all()
    return {
        "titles": total,
        "checked": checked,
        "size": size,
        "threshold_mbps": current().library_bitrate_threshold_mbps,
        "streams_recorded": db.execute(select(func.count()).select_from(StreamSession)).scalar() or 0,
        "stalls_recorded": db.execute(select(func.count()).select_from(StreamEvent)).scalar() or 0,
        "resolutions": [{"resolution": r or "Unknown", "files": n, "size": s or 0} for r, n, s in resolutions],
    }


@router.get("/problems")
def problems(_: AdminUser, db: Db, days: int = Days, threshold_mbps: float | None = Query(None, ge=0.5, le=500)) -> list:
    threshold = threshold_mbps if threshold_mbps is not None else current().library_bitrate_threshold_mbps
    return library.problem_files(db, int(threshold * 1000), days)


@router.get("/transcodes")
def transcodes(_: AdminUser, db: Db, days: int = Days) -> dict:
    return library.transcode_causes(db, days)


@router.get("/messy")
def messy(_: AdminUser, db: Db, days: int = Days, issue: str | None = None) -> dict:
    if issue is not None and issue not in library.ISSUES:
        raise HTTPException(400, f"No such issue. Try: {', '.join(library.ISSUES)}")
    return library.messy_files(db, days, issue)


@router.get("/four-k")
def four_k(_: AdminUser, db: Db, days: int = Query(365, ge=1, le=3650)) -> list:
    return library.four_k(db, days)


@router.get("/requests")
async def requests(_: AdminUser, db: Db) -> dict:
    try:
        return await library.unwatched_requests(db)
    except Exception as exc:  # noqa: BLE001
        from app.integrations.base import describe_failure

        raise HTTPException(502, f"Seerr: {describe_failure(exc)}") from exc


@router.get("/file/{rating_key}")
def file(rating_key: int, _: AdminUser, db: Db, days: int = Query(365, ge=1, le=3650)) -> dict:
    item = db.get(MediaItem, rating_key)
    if item is None or item.title is None:
        raise HTTPException(404, "No such title")
    stats = library.play_stats(db, days, [rating_key]).get(rating_key, {})
    platforms = [
        {"platform": name or "Unknown", "plays": n, "transcodes": int(t or 0)}
        for name, n, t in db.execute(
            select(History.platform, func.count(), func.sum(case((History.transcode_decision == "transcode", 1), else_=0)))
            .where(History.rating_key == rating_key)
            .group_by(History.platform)
            .order_by(func.count().desc())
        ).all()
    ]
    stalls = db.execute(
        select(StreamEvent.cause, func.count()).where(StreamEvent.rating_key == rating_key).group_by(StreamEvent.cause)
    ).all()
    causes = db.execute(
        select(StreamSession.primary_cause, func.count())
        .where(StreamSession.rating_key == rating_key, StreamSession.primary_cause.is_not(None))
        .group_by(StreamSession.primary_cause)
    ).all()
    return {
        **library.describe_file(item),
        "plays": int(stats.get("plays") or 0),
        "remote_plays": int(stats.get("remote") or 0),
        "transcodes": int(stats.get("transcodes") or 0),
        "users": int(stats.get("users") or 0),
        "last_play": stats.get("last_play"),
        "platforms": platforms,
        "stall_causes": [{"cause": c or "one_off", "stalls": n} for c, n in stalls],
        "transcode_causes": [{"cause": c, "streams": n} for c, n in causes],
    }

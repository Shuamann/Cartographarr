"""Library health. Admin only: file paths and who watches what."""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query
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


_requests_cache: dict[str, object] = {"at": 0.0, "value": None}


@router.get("/requests")
async def requests(_: AdminUser, fresh: bool = False) -> dict:
    import asyncio
    import time

    if not fresh and _requests_cache["value"] is not None and time.time() - float(_requests_cache["at"]) < 600:
        return _requests_cache["value"]  # type: ignore[return-value]
    try:
        value = await asyncio.wait_for(library.unwatched_requests(), timeout=90)
    except TimeoutError as exc:
        raise HTTPException(504, "Seerr took longer than 90 seconds to list its requests.") from exc
    except Exception as exc:  # noqa: BLE001
        from app.integrations.base import describe_failure

        raise HTTPException(502, f"Seerr: {describe_failure(exc)}") from exc
    _requests_cache["at"], _requests_cache["value"] = time.time(), value
    return value


def _file_payload(rating_key: int, days: int) -> dict | None:
    """Everything about one file from the database. Run in a worker thread."""
    from app.db import session_scope
    from app.services.library import _since

    since, cutoff = _since(days)
    with session_scope() as db:
        item = db.get(MediaItem, rating_key)
        if item is None or item.title is None:
            return None
        stats = library.play_stats(db, days, [rating_key]).get(rating_key, {})
        platforms = [
            {"platform": name or "Unknown", "plays": n, "transcodes": int(t or 0)}
            for name, n, t in db.execute(
                select(History.platform, func.count(), func.sum(case((History.transcode_decision == "transcode", 1), else_=0)))
                .where(History.rating_key == rating_key, History.started >= since)
                .group_by(History.platform)
                .order_by(func.count().desc())
            ).all()
        ]
        stalls = db.execute(
            select(StreamEvent.cause, func.count())
            .where(StreamEvent.rating_key == rating_key, StreamEvent.started_at >= cutoff)
            .group_by(StreamEvent.cause)
        ).all()
        causes = db.execute(
            select(StreamSession.primary_cause, func.count())
            .where(StreamSession.rating_key == rating_key, StreamSession.primary_cause.is_not(None),
                   StreamSession.started_at >= cutoff)
            .group_by(StreamSession.primary_cause)
        ).all()
        # The latest transcoded plays, so their reasons can be read from
        # Tautulli when live recording did not see them.
        transcoded_rows = [
            row_id
            for (row_id,) in db.execute(
                select(History.row_id)
                .where(History.rating_key == rating_key, History.transcode_decision == "transcode", History.started >= since)
                .order_by(History.started.desc())
                .limit(3)
            ).all()
        ]
        return {
            **library.describe_file(item),
            "media_type": item.media_type,
            "plays": int(stats.get("plays") or 0),
            "remote_plays": int(stats.get("remote") or 0),
            "transcodes": int(stats.get("transcodes") or 0),
            "users": int(stats.get("users") or 0),
            "last_play": stats.get("last_play"),
            "platforms": platforms,
            "stall_causes": [{"cause": c or "one_off", "stalls": n} for c, n in stalls],
            "transcode_causes": [{"cause": c, "streams": n} for c, n in causes],
            "_transcoded_rows": transcoded_rows,
        }


async def _causes_from_history(row_ids: list[int]) -> list[dict]:
    """Why earlier plays transcoded, from Tautulli's per-play stream details.
    Best effort: a slow or missing answer just leaves the reason unknown."""
    import asyncio
    from collections import Counter

    from app.services.streams import transcode_causes
    from app.settings_store import is_configured
    from app.tautulli.client import TautulliClient

    if not row_ids or not is_configured():
        return []
    client = TautulliClient(current())
    counts: Counter = Counter()
    try:
        for row_id in row_ids:
            try:
                data = await asyncio.wait_for(client.call("get_stream_data", row_id=row_id), timeout=10)
            except Exception:  # noqa: BLE001
                continue
            for cause in transcode_causes(data or {}):
                counts[cause] += 1
    finally:
        await client.aclose()
    return [{"cause": c, "streams": n, "from_history": True} for c, n in counts.items()]


@router.get("/file/{rating_key}")
async def file(rating_key: int, _: AdminUser, days: int = Query(365, ge=1, le=3650)) -> dict:
    import asyncio

    from app.integrations import arr as arr_integrations
    from app.services import findings

    payload = await asyncio.to_thread(_file_payload, rating_key, days)
    if payload is None:
        raise HTTPException(404, "No such title")
    rows = payload.pop("_transcoded_rows")
    if not payload["transcode_causes"] and rows:
        payload["transcode_causes"] = await _causes_from_history(rows)
    service = arr_integrations.for_media_type(payload["media_type"])
    payload["findings"] = findings.explain(
        payload,
        int(current().library_bitrate_threshold_mbps * 1000),
        payload["transcode_causes"],
        payload["stall_causes"],
        service.label,
    )
    payload["arr"] = {"name": service.name, "label": service.label, "configured": service.configured()}
    return payload


@router.post("/file/{rating_key}/arr")
async def replace_file(rating_key: int, admin: AdminUser, action: str = Body(..., embed=True)) -> dict:
    """Hand a file back to Radarr or Sonarr: search for a replacement, or tag
    it. Nothing is deleted."""
    import asyncio

    from app import audit
    from app.db import session_scope
    from app.integrations import arr as arr_integrations
    from app.integrations.base import describe_failure
    from app.redact import redact

    if action not in ("search", "tag"):
        raise HTTPException(400, "Action is search or tag")
    with session_scope() as db:
        item = db.get(MediaItem, rating_key)
        if item is None or item.title is None:
            raise HTTPException(404, "No such title")
        service = arr_integrations.for_media_type(item.media_type)
        episodic = item.media_type == "episode"
        show_key = item.grandparent_rating_key
        show = db.get(MediaItem, show_key) if episodic and show_key else None
        if episodic:
            external = show.tvdb_id if show else None
        else:
            external = item.tmdb_id if service.name == "radarr" else item.tvdb_id
        title = library._title(item)
        season, episode = item.parent_media_index, item.media_index
    if not service.configured():
        raise HTTPException(409, f"Connect {service.label} in Settings first")
    if episodic and not external and show_key:
        from app.services.sync import cache_one

        await cache_one(show_key)
        with session_scope() as db:
            show = db.get(MediaItem, show_key)
            external = show.tvdb_id if show else None
    if not external:
        kind = "TMDB" if service.name == "radarr" else "TVDB"
        raise HTTPException(409, f"No {kind} id for this title, so {service.label} cannot find it")
    try:
        if action == "search":
            result = await asyncio.wait_for(service.search(external, season, episode), timeout=45)
        else:
            result = await asyncio.wait_for(service.tag(external), timeout=45)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        audit.record(admin, f"library.{action}", f"Tried to hand {title} to {service.label}", target=str(rating_key),
                     result=f"failed: {redact(exc)}")
        raise HTTPException(502, f"{service.label}: {describe_failure(exc)}") from exc
    audit.record(admin, f"library.{action}", result, target=str(rating_key))
    return {"ok": True, "message": result}

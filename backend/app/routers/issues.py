"""Reports of something wrong with a file, and the evidence around them.

A report on its own says "audio is out of sync". Read next to the file's
tracks, the reporter's own plays of it, whether those transcoded and whether
they stalled, it says why. See services/issues.py.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.auth.deps import AdminUser
from app.db import session_scope
from app.models import History, Issue, MediaItem, StreamEvent, StreamSession, User
from app.settings_store import current

router = APIRouter(prefix="/api/issues")


def _comments(issue: Issue) -> list[dict[str, Any]]:
    try:
        return json.loads(issue.comments or "[]")
    except ValueError:
        return []


def _brief(issue: Issue, names: dict[int, str]) -> dict[str, Any]:
    return {
        "id": issue.id,
        "seerr_id": issue.seerr_id,
        "source": issue.source,
        "issue_type": issue.issue_type,
        "status": issue.status,
        "message": issue.message,
        "title": issue.title,
        "media_type": issue.media_type,
        "rating_key": issue.rating_key,
        "season": issue.season,
        "episode": issue.episode,
        "reporter_name": names.get(issue.reporter_user_id or -1) or issue.reporter_name,
        "reporter_user_id": issue.reporter_user_id,
        "comments": len(_comments(issue)),
        "created_at": issue.created_at.isoformat() if issue.created_at else None,
        "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
    }


@router.get("")
def list_issues(
    _: AdminUser,
    status: str = Query("open", pattern="^(open|resolved|all)$"),
    issue_type: str | None = Query(None, pattern="^(video|audio|subtitles|other)$"),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    with session_scope() as db:
        stmt = select(Issue).order_by(Issue.created_at.desc().nulls_last(), Issue.id.desc()).limit(limit)
        if status != "all":
            stmt = stmt.where(Issue.status == status)
        if issue_type:
            stmt = stmt.where(Issue.issue_type == issue_type)
        issues = db.execute(stmt).scalars().all()
        names = {
            u.user_id: u.friendly_name or u.username
            for u in db.execute(select(User).where(User.user_id.in_([i.reporter_user_id for i in issues if i.reporter_user_id]))).scalars()
        }
        counts = dict(db.execute(select(Issue.status, func.count()).group_by(Issue.status)).all())
        by_type = dict(
            db.execute(select(Issue.issue_type, func.count()).where(Issue.status == "open").group_by(Issue.issue_type)).all()
        )
        return {
            "items": [_brief(i, names) for i in issues],
            "open": counts.get("open", 0),
            "resolved": counts.get("resolved", 0),
            "by_type": by_type,
            "seerr_url": _seerr_link(),
            "seerr_configured": _seerr_configured(),
        }


def _seerr_configured() -> bool:
    from app.integrations.seerr import seerr

    return seerr.configured()


def _seerr_link() -> str | None:
    from app.integrations.seerr import seerr

    return seerr.link_base or None


def _plays(db, rating_key: int, user_id: int | None) -> list[dict[str, Any]]:
    """Plays of this file, the reporter's first, each with what went wrong."""
    rows = db.execute(
        select(History)
        .where(History.rating_key == rating_key)
        .order_by(History.started.desc())
        .limit(50)
    ).scalars().all()
    out = []
    for row in rows:
        # Stalls inside this play, not this person's stalls in general: that is
        # what turns "it buffered" into evidence for this report.
        window = [StreamEvent.rating_key == rating_key, StreamEvent.user_id == row.user_id]
        if row.started:
            window.append(StreamEvent.started_at >= datetime.fromtimestamp(row.started, UTC).replace(tzinfo=None))
        if row.stopped:
            window.append(StreamEvent.started_at <= datetime.fromtimestamp(row.stopped + 60, UTC).replace(tzinfo=None))
        stalls = db.execute(select(func.count(), func.sum(StreamEvent.seconds)).where(*window)).one()
        out.append({
            "row_id": row.row_id,
            "user_id": row.user_id,
            "started": row.started,
            "stopped": row.stopped,
            "platform": row.platform,
            "player": row.player,
            "location": row.location,
            "transcode_decision": row.transcode_decision,
            "percent_complete": row.percent_complete,
            "mine": bool(user_id) and row.user_id == user_id,
            "stalls": int(stalls[0] or 0),
            "stall_seconds": int(stalls[1] or 0),
        })
    out.sort(key=lambda p: (not p["mine"], -(p["started"] or 0)))
    return out


def _payload(issue_id: int, days: int) -> dict[str, Any] | None:
    from app.routers.library import _file_payload

    with session_scope() as db:
        issue = db.get(Issue, issue_id)
        if issue is None:
            return None
        names = {
            u.user_id: u.friendly_name or u.username
            for u in db.execute(select(User)).scalars()
        }
        data = {
            **_brief(issue, names),
            "comment_list": _comments(issue),
            "tmdb_id": issue.tmdb_id,
            "show_rating_key": issue.show_rating_key,
        }
        key = issue.rating_key
        if key is None:
            return {**data, "file": None, "plays": [], "streams": []}
        data["plays"] = [{**p, "user_name": names.get(p["user_id"] or -1)} for p in _plays(db, key, issue.reporter_user_id)]
        item = db.get(MediaItem, key)
        data["file_title"] = (item.full_title or item.title) if item else None
        # What live recording saw while this file played: why it transcoded,
        # and whether it stalled.
        data["streams"] = [
            {"platform": s.platform, "cause": s.primary_cause, "buffers": s.buffer_count,
             "started_at": s.started_at.isoformat() if s.started_at else None,
             "user_id": s.user_id, "user_name": names.get(s.user_id or -1)}
            for s in db.execute(
                select(StreamSession).where(StreamSession.rating_key == key).order_by(StreamSession.started_at.desc()).limit(20)
            ).scalars()
        ]
        data["other_reports"] = [
            _brief(other, names)
            for other in db.execute(
                select(Issue).where(Issue.rating_key == key, Issue.id != issue.id).order_by(Issue.id.desc()).limit(10)
            ).scalars()
        ]
    data["file"] = _file_payload(key, days)
    return data


@router.get("/{issue_id}")
async def issue_detail(issue_id: int, _: AdminUser, days: int = Query(365, ge=1, le=3650)) -> dict:
    import asyncio

    from app.integrations import arr as arr_integrations
    from app.services import findings

    data = await asyncio.to_thread(_payload, issue_id, days)
    if data is None:
        raise HTTPException(404, "No such issue")
    file = data.get("file")
    if file:
        file.pop("_transcoded_rows", None)
        service = arr_integrations.for_media_type(file["media_type"])
        file["findings"] = findings.explain(
            file,
            int(current().library_bitrate_threshold_mbps * 1000),
            file["transcode_causes"],
            file["stall_causes"],
            service.label,
        )
        file["arr"] = {"name": service.name, "label": service.label, "configured": service.configured()}
    return data

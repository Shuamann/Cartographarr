"""Reports of something wrong with a file, and the evidence around them.

A report on its own says "audio is out of sync". Read next to the file's
tracks, the reporter's own plays of it, whether those transcoded and whether
they stalled, it says why. See services/issues.py.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from sqlalchemy import func, select

from app import audit
from app.auth.deps import AdminUser
from app.db import session_scope
from app.models import History, Issue, MediaItem, StreamEvent, StreamSession, User
from app.redact import redact
from app.settings_store import current

log = logging.getLogger(__name__)
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
            # Nothing to attach: the page still expects every list to exist.
            return {**data, "file": None, "plays": [], "streams": [], "other_reports": []}
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


TYPES = ("video", "audio", "subtitles", "other")


@router.post("")
def raise_issue(
    admin: AdminUser,
    rating_key: int = Body(..., embed=True),
    issue_type: str = Body("other", embed=True),
    message: str = Body("", embed=True),
) -> dict:
    """Report a problem with a file, here rather than in Seerr.

    Issues live in this app, so they work whether or not Seerr is set up. A
    report made here stays here for now; mirroring into Seerr comes with the
    write side.
    """
    if issue_type not in TYPES:
        raise HTTPException(400, f"Kind should be one of {', '.join(TYPES)}")
    if not message.strip():
        raise HTTPException(400, "Say what is wrong, so whoever picks this up knows where to look")
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as db:
        item = db.get(MediaItem, rating_key)
        if item is None:
            raise HTTPException(404, "No such title")
        issue = Issue(
            source="local",
            issue_type=issue_type,
            status="open",
            message=message.strip(),
            media_type=item.media_type,
            tmdb_id=item.tmdb_id,
            tvdb_id=item.tvdb_id,
            rating_key=rating_key,
            show_rating_key=item.grandparent_rating_key,
            season=item.parent_media_index,
            episode=item.media_index,
            title=item.full_title or item.title,
            reporter_name=admin.username,
            reporter_user_id=admin.plex_user_id,
            comments=json.dumps([{"message": message.strip(), "author": admin.username, "created_at": now.isoformat()}]),
            created_at=now,
            updated_at=now,
        )
        db.add(issue)
        db.flush()
        issue_id, title = issue.id, issue.title
    audit.record(admin, "issue.create", f"Reported {issue_type} trouble with {title}", target=str(issue_id))
    return {"id": issue_id}


async def _to_seerr(issue_id: int, send) -> str | None:
    """Do the Seerr half of an action. A failure is reported, not raised: the
    decision was made here, and the next sync would undo a half written one."""
    from app.integrations.seerr import seerr
    from app.services import issues as service

    with session_scope() as db:
        issue = db.get(Issue, issue_id)
        seerr_id = issue.seerr_id if issue else None
    if not (seerr_id and seerr.configured()):
        return None
    try:
        await send(service, seerr_id)
    except Exception as exc:  # noqa: BLE001
        from app.integrations.base import describe_failure

        return f"Seerr was not updated: {describe_failure(exc)}"
    return None


@router.post("/{issue_id}/comment")
async def comment(issue_id: int, admin: AdminUser, message: str = Body(..., embed=True)) -> dict:
    if not message.strip():
        raise HTTPException(400, "Nothing to add")
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as db:
        issue = db.get(Issue, issue_id)
        if issue is None:
            raise HTTPException(404, "No such issue")
        notes = _comments(issue)
        notes.append({"message": message.strip(), "author": admin.username, "created_at": now.isoformat()})
        issue.comments = json.dumps(notes)
        issue.updated_at = now
        title = issue.title
    warning = await _to_seerr(issue_id, lambda service, seerr_id: service.comment(seerr_id, message.strip(), admin.username))
    audit.record(admin, "issue.comment", f"Commented on {title}", target=str(issue_id))
    return {"id": issue_id, "comments": len(notes), "warning": warning}


@router.post("/{issue_id}/status")
async def set_status(issue_id: int, admin: AdminUser, status: str = Body(..., embed=True)) -> dict:
    if status not in ("open", "resolved"):
        raise HTTPException(400, "Status is open or resolved")
    with session_scope() as db:
        issue = db.get(Issue, issue_id)
        if issue is None:
            raise HTTPException(404, "No such issue")
        issue.status = status
        issue.updated_at = datetime.now(UTC).replace(tzinfo=None)
        title = issue.title
    warning = await _to_seerr(issue_id, lambda service, seerr_id: service.set_status(seerr_id, status, admin.username))
    audit.record(admin, "issue.status", f"Marked {title} {status}", target=str(issue_id))
    return {"id": issue_id, "status": status, "warning": warning}


# ---- choosing what the report is about -------------------------------------
#
# A text box asks someone to name a file. What they actually know is "the thing
# I just watched", or "that show, the third episode". So: what is playing and
# what was played recently first, then shows and films by name, then episodes
# under a show, with posters throughout.

def _card(item: MediaItem, **extra: Any) -> dict[str, Any]:
    return {
        "rating_key": item.rating_key,
        "title": item.full_title or item.title,
        "show": item.grandparent_title,
        "season": item.parent_media_index,
        "episode": item.media_index,
        "media_type": item.media_type,
        "year": item.year,
        "summary": item.summary,
        **extra,
    }


@router.get("/recent")
async def recent(_: AdminUser, limit: int = Query(12, ge=1, le=50)) -> dict:
    """Playing now, then lately watched. What a report is usually about."""
    import asyncio

    from app.routers.live import activity

    def lately() -> list[dict[str, Any]]:
        with session_scope() as db:
            keys: list[int] = []
            for (key,) in db.execute(
                select(History.rating_key)
                .where(History.rating_key.is_not(None))
                .order_by(History.started.desc())
                .limit(limit * 4)
            ).all():
                if key not in keys:
                    keys.append(key)
            items = {i.rating_key: i for i in db.execute(select(MediaItem).where(MediaItem.rating_key.in_(keys))).scalars()}
            return [_card(items[key]) for key in keys if key in items and items[key].title][:limit]

    playing: list[dict[str, Any]] = []
    try:
        with session_scope() as db:
            live = await activity(db)
            keys = [int(s["rating_key"]) for s in live.get("sessions") or [] if s.get("rating_key")]
            items = {i.rating_key: i for i in db.execute(select(MediaItem).where(MediaItem.rating_key.in_(keys))).scalars()}
            playing = [_card(items[key], playing=True) for key in keys if key in items]
    except Exception as exc:  # noqa: BLE001 - the list is still useful without it
        log.debug("could not read what is playing: %s", redact(exc))

    watched = await asyncio.to_thread(lately)
    seen = {card["rating_key"] for card in playing}
    return {"items": playing + [card for card in watched if card["rating_key"] not in seen]}


@router.get("/search")
def search(_: AdminUser, q: str = Query(min_length=1), limit: int = Query(12, ge=1, le=50)) -> dict:
    """Films and shows by name. Episodes are reached through their show."""
    like = f"%{q.strip()}%"
    with session_scope() as db:
        films = [
            _card(item)
            for item in db.execute(
                select(MediaItem)
                .where(MediaItem.media_type == "movie", MediaItem.title.is_not(None), MediaItem.title.ilike(like))
                .order_by(MediaItem.title)
                .limit(limit)
            ).scalars()
        ]
        # Shows are read off their episodes, because a library scan stores the
        # files, and an episode is the file.
        shows = [
            {
                "rating_key": key,
                "title": title,
                "media_type": "show",
                "episodes": int(count or 0),
                "season_count": int(seasons or 0),
            }
            for key, title, count, seasons in db.execute(
                select(
                    MediaItem.grandparent_rating_key,
                    func.max(MediaItem.grandparent_title),
                    func.count(),
                    func.count(func.distinct(MediaItem.parent_media_index)),
                )
                .where(
                    MediaItem.media_type == "episode",
                    MediaItem.grandparent_rating_key.is_not(None),
                    MediaItem.grandparent_title.ilike(like),
                )
                .group_by(MediaItem.grandparent_rating_key)
                .order_by(func.max(MediaItem.grandparent_title))
                .limit(limit)
            ).all()
        ]
    return {"shows": shows, "films": films}


@router.get("/shows/{show_key}/episodes")
def episodes(show_key: int, _: AdminUser) -> dict:
    """Every episode of one show, in order, for picking one."""
    with session_scope() as db:
        items = db.execute(
            select(MediaItem)
            .where(MediaItem.grandparent_rating_key == show_key, MediaItem.media_type == "episode")
            .order_by(MediaItem.parent_media_index, MediaItem.media_index)
        ).scalars().all()
        if not items:
            raise HTTPException(404, "No episodes here")
        return {
            "show": items[0].grandparent_title,
            "show_rating_key": show_key,
            "episodes": [_card(item) for item in items],
        }


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

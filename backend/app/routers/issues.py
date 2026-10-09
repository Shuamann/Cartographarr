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
from app.auth.deps import AdminUser, CurrentUser
from app.db import session_scope
from app.models import History, Issue, MediaItem, StreamEvent, StreamSession, User
from app.redact import redact
from app.services import issues as issue_service
from app.settings_store import current

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/issues")


def _asker(user) -> int | None:
    """None for an admin, otherwise the Plex user a viewer is limited to.

    A viewer sees what they reported and nothing else: not other people's
    reports, not who else watched the file, not where it sits on disk.
    """
    if user.role == "admin":
        return None
    if not current().viewer_reports_issues:
        raise HTTPException(403, "Reporting is switched off on this server")
    from app.privacy import linked_plex_user

    linked = linked_plex_user(user)
    if linked is None:
        raise HTTPException(
            409,
            "Your account is not linked to a Plex user, so this server cannot tell what you have watched. "
            "Ask an admin to link it.",
        )
    return linked


def _comments(issue: Issue) -> list[dict[str, Any]]:
    try:
        return json.loads(issue.comments or "[]")
    except ValueError:
        return []


def _thread(issue: Issue, names: dict[int, str]) -> list[dict[str, Any]]:
    """The comments, each signed by whoever wrote it.

    By the name this app knows them by where there is a Plex id, the same as
    the reporter. Seerr opens every issue with the reporter's own message, so
    an unsigned first comment is theirs, and saying "someone" there names
    nobody when the answer is on the same row.
    """
    out = []
    for n, note in enumerate(_comments(issue)):
        author = names.get(note.get("author_id") or -1) or note.get("author")
        if not author and n == 0:
            author = names.get(issue.reporter_user_id or -1) or issue.reporter_name
        out.append({**note, "author": author})
    return out


def _numbers(issue: Issue) -> tuple[int | None, int | None]:
    """Season and episode, only for an episode. Seerr sends 0 and 0 for a
    film, and reports read in before that was caught still carry them."""
    if issue.media_type not in ("tv", "episode") or not issue.episode:
        return None, None
    return issue.season, issue.episode


def _brief(issue: Issue, names: dict[int, str], items: dict[int, Any] | None = None) -> dict[str, Any]:
    item = (items or {}).get(issue.rating_key or -1)
    season, episode = _numbers(issue)
    return {
        # The year a row shows above its title, read from the library rather
        # than from the report, which never carried one.
        "year": item.year if item is not None else None,
        # The title in its parts, so a row that has to shorten it can give up
        # the show name and keep the episode number. A report keeps one string,
        # "The Show - Episode", and cutting that from the end loses the part
        # somebody is looking for.
        "show_title": item.grandparent_title if item is not None else None,
        "episode_title": item.title if item is not None and item.media_type == "episode" else None,
        # A row with no title is a placeholder, written when something asked
        # Plex for a key it no longer has, so that nothing asks again. It is
        # the opposite of being in the library.
        "in_library": item is not None and item.title is not None,
        "id": issue.id,
        "seerr_id": issue.seerr_id,
        "source": issue.source,
        "issue_type": issue.issue_type,
        "status": issue.status,
        "message": issue.message,
        "title": issue.title,
        "media_type": issue.media_type,
        "rating_key": issue.rating_key,
        "season": season,
        "episode": episode,
        "reporter_name": names.get(issue.reporter_user_id or -1) or issue.reporter_name,
        "reporter_user_id": issue.reporter_user_id,
        "comments": len(_comments(issue)),
        "created_at": issue.created_at.isoformat() if issue.created_at else None,
        "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
        # Kept here after Seerr stopped listing it, which is worth saying
        # beside the link that would no longer go anywhere.
        "seerr_gone": bool(issue.seerr_gone_at),
        # Closed by a new file arriving rather than by somebody, which is the
        # answer to "is the file I reported still the one there".
        "replaced": bool(issue.replaced_at) and issue.status == "resolved",
    }


@router.get("")
def list_issues(
    user: CurrentUser,
    status: str = Query("open", pattern="^(open|resolved|all)$"),
    issue_type: str | None = Query(None, pattern="^(video|audio|subtitles|other)$"),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    mine = _asker(user)
    with session_scope() as db:
        stmt = select(Issue).order_by(Issue.created_at.desc().nulls_last(), Issue.id.desc()).limit(limit)
        if status != "all":
            stmt = stmt.where(Issue.status == status)
        if issue_type:
            stmt = stmt.where(Issue.issue_type == issue_type)
        if mine is not None:
            stmt = stmt.where(Issue.reporter_user_id == mine)
        issues = db.execute(stmt).scalars().all()
        names = {
            u.user_id: u.friendly_name or u.username
            for u in db.execute(select(User).where(User.user_id.in_([i.reporter_user_id for i in issues if i.reporter_user_id]))).scalars()
        }
        keys = sorted({i.rating_key for i in issues if i.rating_key})
        items = {
            row.rating_key: row
            for row in db.execute(
                select(MediaItem.rating_key, MediaItem.year, MediaItem.grandparent_title, MediaItem.title,
                       MediaItem.media_type).where(MediaItem.rating_key.in_(keys))
            ).all()
        } if keys else {}
        evidence = _evidence(db, keys, mine)
        totals = select(Issue.status, func.count()).group_by(Issue.status)
        kinds = select(Issue.issue_type, func.count()).where(Issue.status == "open").group_by(Issue.issue_type)
        if mine is not None:
            totals = totals.where(Issue.reporter_user_id == mine)
            kinds = kinds.where(Issue.reporter_user_id == mine)
        counts = dict(db.execute(totals).all())
        by_type = dict(db.execute(kinds).all())
        return {
            "items": [{**_brief(i, names, items), **_row_evidence(evidence, i, mine)} for i in issues],
            "open": counts.get("open", 0),
            "resolved": counts.get("resolved", 0),
            "by_type": by_type,
            "seerr_url": _seerr_link() if mine is None else None,
            "seerr_configured": _seerr_configured(),
            "mine_only": mine is not None,
        }


def _evidence(db, keys: list[int], mine: int | None) -> dict[int, dict[int | None, list[int]]]:
    """Plays and stalls of each reported file, per person, in two queries.

    Per person because the question a row answers is whose problem it is: the
    reporter stalling while everybody else played it cleanly points at their
    connection, and everybody stalling points at the file. A viewer is only
    ever counted against their own plays.
    """
    out: dict[int, dict[int | None, list[int]]] = {}
    for i in range(0, len(keys), 500):
        chunk = keys[i : i + 500]
        plays = select(History.rating_key, History.user_id, func.count()).where(History.rating_key.in_(chunk))
        stalls = select(StreamEvent.rating_key, StreamEvent.user_id, func.count()).where(StreamEvent.rating_key.in_(chunk))
        if mine is not None:
            plays = plays.where(History.user_id == mine)
            stalls = stalls.where(StreamEvent.user_id == mine)
        for key, uid, count in db.execute(plays.group_by(History.rating_key, History.user_id)).all():
            out.setdefault(key, {}).setdefault(uid, [0, 0])[0] += int(count)
        for key, uid, count in db.execute(stalls.group_by(StreamEvent.rating_key, StreamEvent.user_id)).all():
            out.setdefault(key, {}).setdefault(uid, [0, 0])[1] += int(count)
    return out


def _row_evidence(evidence: dict[int, dict[int | None, list[int]]], issue: Issue, mine: int | None) -> dict[str, Any]:
    """The reporter's plays against everybody else's, for one row."""
    people = evidence.get(issue.rating_key or -1, {})
    reporter = issue.reporter_user_id
    theirs = people.get(reporter, [0, 0]) if reporter is not None else [0, 0]
    out: dict[str, Any] = {"reporter_plays": theirs[0], "reporter_stalls": theirs[1]}
    if mine is None:
        others = [counts for uid, counts in people.items() if uid != reporter]
        out["other_people"] = sum(1 for counts in others if counts[0])
        out["other_plays"] = sum(counts[0] for counts in others)
        out["other_stalls"] = sum(counts[1] for counts in others)
    return out


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
            "comment_list": _thread(issue, names),
            "context": json.loads(issue.context) if issue.context else None,
            "tmdb_id": issue.tmdb_id,
            "show_rating_key": issue.show_rating_key,
        }
        key = issue.rating_key
        if key is None:
            # Nothing to attach: the page still expects every list to exist.
            return {**data, "file": None, "plays": [], "streams": [], "other_reports": []}
        data["plays"] = [{**p, "user_name": names.get(p["user_id"] or -1)} for p in _plays(db, key, issue.reporter_user_id)]
        item = db.get(MediaItem, key)
        if item is None and issue.tmdb_id:
            # Plex renumbers things. The report remembers the old key; the id
            # finds the same title under the new one.
            item = db.execute(
                select(MediaItem).where(MediaItem.tmdb_id == str(issue.tmdb_id)).limit(1)
            ).scalar_one_or_none()
            if item is not None:
                data["found_under"] = item.rating_key
        data["file_title"] = (item.full_title or item.title) if item else None
        if item is not None:
            data.update(_brief(issue, names, {issue.rating_key or -1: item}))
        data["whereis"] = _whereis(item)
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


def _whereis(item: MediaItem | None) -> dict[str, Any]:
    """Whether the file is actually on the disk.

    A row in the library is a record that the file was there at the last scan.
    This looks. The two disagree exactly when something has been deleted,
    moved or unmounted, which is the case worth telling somebody about and the
    one the page could not answer at all.

    A path this container cannot reach is not the same as a file that is gone,
    so the two are said differently: one is a mount to fix, the other is a
    file to replace.
    """
    import os

    if item is None or not item.file_path:
        return {"state": "unknown", "path": None, "size": None}

    from app.services import mediafix

    here = mediafix.local_path(item.file_path)
    if here is None:
        return {
            "state": "unreachable",
            "path": item.file_path,
            "size": item.file_size,
        }
    try:
        size = os.path.getsize(here)
    except OSError:
        return {"state": "gone", "path": item.file_path, "size": item.file_size}
    return {
        "state": "present",
        "path": item.file_path,
        "size": size,
        # The scan's figure against what is on the disk now. A file that has
        # changed size since is a file somebody replaced.
        "changed": bool(item.file_size and abs(size - item.file_size) > 1024),
    }


TYPES = ("video", "audio", "subtitles", "other")


@router.post("")
async def raise_issue(
    user: CurrentUser,
    rating_key: int = Body(..., embed=True),
    issue_type: str = Body("other", embed=True),
    message: str = Body("", embed=True),
    row_id: int | None = Body(None, embed=True),
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
    mine = _asker(user)
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as db:
        item = db.get(MediaItem, rating_key)
        if item is None:
            raise HTTPException(404, "No such title")
        # Reported from a play: keep what that play looked like, since it is
        # the half nobody remembers to write down.
        context = _context(db, row_id, mine) if row_id else None
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
            reporter_name=user.username,
            reporter_user_id=mine if mine is not None else user.plex_user_id,
            context=json.dumps(context) if context else None,
            comments=json.dumps([{"message": message.strip(), "author": user.username, "created_at": now.isoformat()}]),
            created_at=now,
            updated_at=now,
        )
        db.add(issue)
        db.flush()
        issue_id, title = issue.id, issue.title
    audit.record(user, "issue.create", f"Reported {issue_type} trouble with {title}", target=str(issue_id))
    await issue_service.announce(issue_id)
    return {"id": issue_id}


@router.post("/{issue_id}/comment")
async def comment(issue_id: int, user: CurrentUser, message: str = Body(..., embed=True)) -> dict:
    if not message.strip():
        raise HTTPException(400, "Nothing to add")
    # Whose report it is stays a question for the router: the service writes
    # the note, this decides whether this person may.
    mine = _asker(user)
    if mine is not None:
        with session_scope() as db:
            issue = db.get(Issue, issue_id)
            if issue is None or issue.reporter_user_id != mine:
                raise HTTPException(404, "No such issue")
    try:
        title, notes, warning = await issue_service.add_comment(issue_id, message, user.username)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    audit.record(user, "issue.comment", f"Commented on {title}", target=str(issue_id))
    return {"id": issue_id, "comments": notes, "warning": warning}


@router.post("/{issue_id}/status")
async def set_status(issue_id: int, admin: AdminUser, status: str = Body(..., embed=True)) -> dict:
    try:
        title, warning = await issue_service.mark(issue_id, status, admin.username)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
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
async def recent(user: CurrentUser, limit: int = Query(12, ge=1, le=50)) -> dict:
    """Playing now, then lately watched. What a report is usually about."""
    import asyncio

    from app.routers.live import activity

    mine = _asker(user)

    def lately() -> list[dict[str, Any]]:
        with session_scope() as db:
            where = [History.rating_key.is_not(None)]
            if mine is not None:
                where.append(History.user_id == mine)
            keys: list[int] = []
            for (key,) in db.execute(
                select(History.rating_key)
                .where(*where)
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
            sessions = [
                s for s in live.get("sessions") or []
                if mine is None or (s.get("user_id") and int(s["user_id"]) == mine)
            ]
            keys = [int(s["rating_key"]) for s in sessions if s.get("rating_key")]
            items = {i.rating_key: i for i in db.execute(select(MediaItem).where(MediaItem.rating_key.in_(keys))).scalars()}
            playing = [_card(items[key], playing=True) for key in keys if key in items]
    except Exception as exc:  # noqa: BLE001 - the list is still useful without it
        log.debug("could not read what is playing: %s", redact(exc))

    watched = await asyncio.to_thread(lately)
    seen = {card["rating_key"] for card in playing}
    return {"items": playing + [card for card in watched if card["rating_key"] not in seen]}


@router.get("/search")
def search(user: CurrentUser, q: str = Query(min_length=1), limit: int = Query(12, ge=1, le=50)) -> dict:
    """Films and shows by name. Episodes are reached through their show."""
    _asker(user)
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
def episodes(show_key: int, user: CurrentUser) -> dict:
    """Every episode of one show, in order, for picking one."""
    _asker(user)
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
async def issue_detail(issue_id: int, user: CurrentUser, days: int = Query(365, ge=1, le=3650)) -> dict:
    import asyncio

    from app.integrations import arr as arr_integrations
    from app.services import findings

    mine = _asker(user)
    data = await asyncio.to_thread(_payload, issue_id, days)
    if data is None or (mine is not None and data.get("reporter_user_id") != mine):
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
    # Trimmed last: the findings above are read from the causes, and a viewer
    # should see the findings without seeing everyone else's streams.
    return _as_reported_by(data, mine) if mine is not None else data


def _context(db, row_id: int, mine: int | None) -> dict[str, Any] | None:
    """What one play looked like, kept with the report it came from."""
    row = db.get(History, row_id)
    if row is None or (mine is not None and row.user_id != mine):
        return None
    window = [StreamEvent.rating_key == row.rating_key, StreamEvent.user_id == row.user_id]
    if row.started:
        window.append(StreamEvent.started_at >= datetime.fromtimestamp(row.started, UTC).replace(tzinfo=None))
    if row.stopped:
        window.append(StreamEvent.started_at <= datetime.fromtimestamp(row.stopped + 60, UTC).replace(tzinfo=None))
    stalls, seconds = db.execute(select(func.count(), func.sum(StreamEvent.seconds)).where(*window)).one()
    return {
        "row_id": row.row_id,
        "started": row.started,
        "player": row.player,
        "platform": row.platform,
        "product": row.product,
        "location": row.location,
        "transcode_decision": row.transcode_decision,
        "percent_complete": row.percent_complete,
        "stalls": int(stalls or 0),
        "stall_seconds": int(seconds or 0),
    }


def _as_reported_by(data: dict[str, Any], mine: int) -> dict[str, Any]:
    """The same report, with everything that is not theirs taken out.

    A viewer asked about their own report, so they get their own plays and
    nothing about anyone else: no other reports, no other people's streams, and
    not where the file lives on the server.
    """
    file = data.get("file")
    if file:
        file = {k: v for k, v in file.items() if k not in ("file_path", "platforms", "stall_causes", "transcode_causes")}
    # Whether the file is there is theirs to know, since it answers their
    # report. Where it lives is not.
    whereis = data.get("whereis")
    if whereis:
        whereis = {**whereis, "path": None}
    return {
        **data,
        "file": file,
        "whereis": whereis,
        "plays": [p for p in data.get("plays") or [] if p.get("user_id") == mine],
        "streams": [],
        "other_reports": [],
    }

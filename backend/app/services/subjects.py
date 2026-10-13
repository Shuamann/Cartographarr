"""What a rule is about, when it is not about a stream.

A stream rule is handed a session by live activity. A file rule has to be
handed something too, so this builds the subjects: one dictionary per file,
issue, replacement or person, shaped the way the condition fields expect to
read them. Everything here comes from what the app has already collected, so a
sweep costs a few queries rather than a conversation with Plex.

Subjects are deliberately flat and dull. The interesting part is that they let
one matcher, one cooldown, one record only switch and one Log serve rules about
things nobody is watching.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.db import session_scope

WINDOW_DAYS = 30
"""How far back a file rule looks when counting plays, stalls and transcodes."""


def files(window_days: int = WINDOW_DAYS, limit: int = 2000) -> list[dict[str, Any]]:
    """Every file worth asking a question about, with how it has behaved.

    Files nobody has played in the window are left out: a rule about stalls or
    transcodes has nothing to say about them, and the whole library would be
    tens of thousands of subjects to no purpose.
    """
    from app.models import History, MediaItem, StreamEvent, StreamSession
    from app.plays import plays, plays_when
    from app.services.library import file_issues
    from app.services.library_scan import in_library
    from app.services.stores import labels, name_for

    since = int((datetime.now(UTC) - timedelta(days=window_days)).timestamp())
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=window_days)
    named = labels()

    with session_scope() as db:
        remote = History.location == "wan"
        watched = {
            key: (int(total or 0), int(wan or 0), int(transcoded or 0), last)
            for key, total, wan, transcoded, last in db.execute(
                select(
                    History.rating_key,
                    plays(History),
                    plays_when(History, remote),
                    plays_when(History, History.transcode_decision == "transcode"),
                    func.max(History.started),
                )
                .where(History.started >= since, History.rating_key.is_not(None))
                .group_by(History.rating_key)
            ).all()
        }
        if not watched:
            return []

        keys = list(watched)[:limit]
        stalls = {
            key: (int(count or 0), int(people or 0))
            for key, count, people in db.execute(
                select(StreamEvent.rating_key, func.count(), func.count(func.distinct(StreamEvent.user_id)))
                .where(StreamEvent.rating_key.in_(keys), StreamEvent.started_at >= cutoff, StreamEvent.kind == "buffering")
                .group_by(StreamEvent.rating_key)
            ).all()
        }
        causes = {
            key: cause
            for key, cause in db.execute(
                select(StreamSession.rating_key, func.max(StreamSession.primary_cause))
                .where(StreamSession.rating_key.in_(keys), StreamSession.started_at >= cutoff)
                .group_by(StreamSession.rating_key)
            ).all()
        }
        items = db.execute(select(MediaItem).where(MediaItem.rating_key.in_(keys), in_library())).scalars().all()

        out = []
        for item in items:
            total, wan, transcoded, last = watched.get(item.rating_key, (0, 0, 0, None))
            stall_count, stall_people = stalls.get(item.rating_key, (0, 0))
            out.append({
                "subject": "file",
                # A collection is filed against a film or a show, never
                # against an episode, so the condition asking about one needs
                # the keys above this file as well as its own.
                "rating_key": item.rating_key,
                "parent_rating_key": item.parent_rating_key,
                "grandparent_rating_key": item.grandparent_rating_key,
                "full_title": item.full_title or item.title,
                "title": item.title,
                "media_type": item.media_type,
                "section_id": item.section_id,
                "year": item.year,
                "file_bitrate": item.file_bitrate,
                "file_size": item.file_size,
                "file_container": item.file_container,
                "video_codec": item.video_codec,
                "video_resolution": item.video_resolution,
                "audio_codec": item.audio_codec,
                "store": name_for(item.file_path, named),
                "findings": file_issues(item),
                "plays": total,
                "remote_plays": wan,
                "transcodes": transcoded,
                "transcode_percent": round(transcoded / total * 100) if total else 0,
                "stalls": stall_count,
                "stall_people": stall_people,
                "stall_cause": causes.get(item.rating_key),
                "last_play": last,
            })
    return out


def issues(window_hours: int = 24) -> list[dict[str, Any]]:
    """Reports raised lately, with the file they are about.

    A rule about a report nearly always wants to know something about the
    file, so the file's own answers come along rather than making the rule
    chase them.
    """
    from app.models import Issue, MediaItem
    from app.services.library import file_issues

    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=window_hours)
    with session_scope() as db:
        rows = db.execute(
            select(Issue).where(Issue.created_at >= since).order_by(Issue.id.desc())
        ).scalars().all()
        items = {
            m.rating_key: m
            for m in db.execute(
                select(MediaItem).where(MediaItem.rating_key.in_([r.rating_key for r in rows if r.rating_key]))
            ).scalars()
        }
        out = []
        for row in rows:
            item = items.get(row.rating_key) if row.rating_key else None
            out.append({
                "subject": "issue",
                "issue_id": row.id,
                "issue_type": row.issue_type,
                "issue_status": row.status,
                "issue_source": row.source,
                "message": row.message,
                "user_id": row.reporter_user_id,
                "rating_key": row.rating_key,
                "parent_rating_key": item.parent_rating_key if item else None,
                "grandparent_rating_key": item.grandparent_rating_key if item else None,
                "full_title": row.title,
                "media_type": row.media_type,
                "file_bitrate": item.file_bitrate if item else None,
                "video_codec": item.video_codec if item else None,
                "video_resolution": item.video_resolution if item else None,
                "audio_codec": item.audio_codec if item else None,
                "findings": file_issues(item) if item else [],
            })
    return out


def replacements(window_hours: int = 48) -> list[dict[str, Any]]:
    """Replacements that finished, failed, or have been waiting too long."""
    from app.models import Replacement

    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=window_hours)
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as db:
        rows = db.execute(
            select(Replacement).where(Replacement.updated_at >= since)
        ).scalars().all()
        return [
            {
                "subject": "replacement",
                "replacement_id": row.id,
                "rating_key": row.rating_key,
                "full_title": row.title,
                "replacement_status": row.status,
                "service": row.service,
                "waiting_hours": round((now - (row.updated_at or now)).total_seconds() / 3600, 1),
            }
            for row in rows
        ]


def people(quiet_days: int = 90) -> list[dict[str, Any]]:
    """Everyone the server knows, with how long since they watched anything."""
    from app.models import Device, History, User
    from app.plays import plays

    now = int(datetime.now(UTC).timestamp())
    with session_scope() as db:
        watched = {
            key: (int(count or 0), last)
            for key, count, last in db.execute(
                select(History.user_id, plays(History), func.max(History.started))
                .where(History.user_id.is_not(None))
                .group_by(History.user_id)
            ).all()
        }
        unreviewed = {
            uid
            for (uid,) in db.execute(
                select(Device.user_id).where(Device.is_new_unreviewed.is_(True), Device.user_id.is_not(None)).distinct()
            ).all()
        }
        out = []
        for person in db.execute(select(User)).scalars():
            count, last = watched.get(person.user_id, (0, None))
            out.append({
                "subject": "person",
                "user_id": person.user_id,
                "username": person.friendly_name or person.username,
                "friendly_name": person.friendly_name,
                "plays": count,
                "last_play": last,
                "days_since_play": int((now - last) / 86400) if last else None,
                "quiet": bool(last and (now - last) / 86400 >= quiet_days) or (count == 0),
                "device_unreviewed": person.user_id in unreviewed,
                "deleted_in_tautulli": bool(person.deleted_in_tautulli),
            })
    return out


BUILDERS = {"file": files, "issue": issues, "replacement": replacements, "person": people}


def for_trigger(trigger: str) -> list[dict[str, Any]]:
    builder = BUILDERS.get(trigger)
    return builder() if builder else []


def identity(subject: dict[str, Any]) -> str:
    """What this subject is, for cooldowns: the same file twice in an hour is
    the same thing happening, not two things."""
    kind = subject.get("subject")
    for key in ("issue_id", "replacement_id", "rating_key", "user_id"):
        if subject.get(key) is not None:
            return f"{kind}:{key}:{subject[key]}"
    return f"{kind}:unknown"

"""What each live stream has been doing, across polls.

Tautulli reports a stream's state at the moment it is asked, not how long it
has been in that state or how often it has changed. Rules like "buffering for
more than 20 seconds" or "buffered three times" need both, so every activity
poll is fed through here and the answers are kept in memory.

Each buffering episode is also saved when it ends, with the stream's details,
so buffering can be reported on later: who, which device and network, what
bitrate, direct play or transcode.

Timing is only as fine as the poll (every few seconds), so a stall shorter
than one poll can be missed and every duration is accurate to about one poll.
Restarting the app starts the counts again.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

BUFFERING = "buffering"
PAUSED = "paused"


@dataclass
class Track:
    session_key: str
    first_seen: float
    last_seen: float
    state: str | None
    state_since: float
    buffer_count: int = 0
    buffer_seconds: float = 0.0
    buffer_started: float | None = None
    # Where playback was when a stall began, to tell a seek from a stall.
    buffer_offset: int | None = None
    buffer_progress: int | None = None
    seeks: int = 0
    last_session: dict[str, Any] = field(default_factory=dict)
    # The stream_sessions row, and what it holds, so each poll only writes
    # when something changed or a minute has passed.
    row_id: int | None = None
    row: dict[str, Any] = field(default_factory=dict)
    written_at: float = 0.0
    # Time spent paused, so a play recorded from this stream says how long it
    # was actually watched rather than how long it was open.
    paused_seconds: float = 0.0


_tracks: dict[str, Track] = {}


def observe(sessions: list[dict[str, Any]], now: float | None = None, activity: dict[str, Any] | None = None) -> None:
    """Update every stream's history from one activity poll."""
    from app.services import streams

    now = time.time() if now is None else now
    seen: set[str] = set()
    # Streams that were not here last poll. Their devices are written down
    # once, at the start, rather than on every poll for as long as the film
    # lasts.
    started: list[dict[str, Any]] = []

    for session in sessions:
        key = str(session.get("session_key"))
        seen.add(key)
        state = str(session.get("state") or "").lower() or None
        track = _tracks.get(key)
        if track is None:
            track = Track(session_key=key, first_seen=now, last_seen=now, state=state, state_since=now)
            _tracks[key] = track
            started.append(session)
            if state == BUFFERING:
                _start_buffering(track, session, now)
        elif state != track.state:
            if track.state == BUFFERING:
                _end_buffering(track, now, session)
            if track.state == PAUSED:
                track.paused_seconds += now - track.state_since
            if state == BUFFERING:
                _start_buffering(track, session, now)
            track.state = state
            track.state_since = now
        track.last_seen = now
        track.last_session = session

        row = streams.merge(track.row, session, now) if track.row else streams.row_for(session, now)
        # Kept on the row as it plays, so a restart does not lose them.
        row["buffer_count"] = track.buffer_count
        row["buffer_seconds"] = round(track.buffer_seconds, 1)
        changed = {k: v for k, v in row.items() if k not in ("last_seen_at", "progress_end") and track.row.get(k) != v}
        if track.row_id is None or changed or now - track.written_at >= 60:
            track.row_id = streams.save(row, track.row_id)
            track.written_at = now
        track.row = row

    # A device playing something exists, whether or not it has ever finished a
    # play. The inventory is otherwise rebuilt from history, so until now the
    # player name on the dashboard linked to a page that answered "No such
    # device" for anything streaming for the first time.
    if started:
        streams.seen(started, now)

    if activity is not None:
        streams.sample(activity, sessions, now)

    # A stream no longer in activity has ended. Close any stall it was in.
    for key in [k for k in _tracks if k not in seen]:
        track = _tracks.pop(key)
        if track.state == BUFFERING:
            _end_buffering(track, track.last_seen)
        if track.row_id is not None:
            streams.save(track.row, track.row_id)
            streams.finish(track.row_id, track.last_seen, track.buffer_count, track.buffer_seconds)
            if track.state == PAUSED:
                track.paused_seconds += track.last_seen - track.state_since
            # The play itself, for an install with nobody else writing them.
            from app.services import recorded

            recorded.record(track.row_id, track.last_session, track.row, track.first_seen, track.last_seen,
                            track.paused_seconds)


def metrics(session_key: str, now: float | None = None) -> dict[str, Any]:
    """The tracked figures for one stream, as condition context."""
    now = time.time() if now is None else now
    track = _tracks.get(str(session_key))
    if track is None:
        return {}
    current = (now - track.buffer_started) if track.state == BUFFERING and track.buffer_started else 0.0
    return {
        "buffering_seconds": round(current, 1) if track.state == BUFFERING else None,
        "buffer_count": track.buffer_count,
        "buffer_total_seconds": round(track.buffer_seconds + current, 1),
        "tracked_seconds": round(now - track.first_seen, 1),
        "state_seconds": round(now - track.state_since, 1),
    }


def reset() -> None:
    _tracks.clear()


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _start_buffering(track: Track, session: dict[str, Any], now: float) -> None:
    track.buffer_count += 1
    track.buffer_started = now
    track.buffer_offset = _int(session.get("view_offset"))
    track.buffer_progress = _int(session.get("progress_percent"))


SEEK_SLACK_MS = 20000
END_OF_VIDEO_PERCENT = 98


def _not_a_stall(track: Track, seconds: float, after: dict[str, Any] | None) -> str | None:
    """Why a buffering episode is not worth counting, or None if it is.

    Plex reports "buffering" whenever the player waits for data, which also
    happens when someone skips forward or back, and for a moment as one
    episode ends and the next starts. Counting those buried real stalls.
    """
    if seconds < 1:
        return "too short to see"
    if track.buffer_progress is not None and track.buffer_progress >= END_OF_VIDEO_PERCENT:
        return "end of the video"
    new_offset = _int((after or {}).get("view_offset"))
    if track.buffer_offset is not None and new_offset is not None:
        moved = new_offset - track.buffer_offset
        # Playing on through a stall moves the position by at most the stall
        # itself; a seek moves it much further, or backwards.
        if abs(moved - seconds * 1000) > SEEK_SLACK_MS:
            return "a seek"
    return None


def _end_buffering(track: Track, ended: float, after: dict[str, Any] | None = None) -> None:
    started = track.buffer_started or ended
    seconds = max(ended - started, 0.0)
    track.buffer_started = None
    reason = _not_a_stall(track, seconds, after)
    if reason is not None:
        track.buffer_count = max(track.buffer_count - 1, 0)
        if reason == "a seek":
            track.seeks += 1
        log.debug("buffering on %s not counted: %s", track.session_key, reason)
        return
    track.buffer_seconds += seconds
    try:
        _record(track, started, ended, seconds)
    except Exception:  # noqa: BLE001 - losing one event must not break the poll
        log.exception("could not record a buffering event")


def _record(track: Track, started: float, ended: float, seconds: float) -> None:
    from app.db import session_scope
    from app.models import StreamEvent

    s = track.last_session

    def num(value: Any) -> int | None:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    with session_scope() as db:
        event = StreamEvent(
                kind=BUFFERING,
                session_key=track.session_key,
                user_id=num(s.get("user_id")),
                username=s.get("friendly_name") or s.get("username"),
                machine_id=s.get("machine_id"),
                player=s.get("player"),
                platform=s.get("platform"),
                product=s.get("product"),
                ip_address=s.get("ip_address"),
                location=s.get("location"),
                rating_key=num(s.get("rating_key")),
                full_title=s.get("full_title"),
                media_type=s.get("media_type"),
                transcode_decision=s.get("transcode_decision"),
                video_resolution=s.get("video_full_resolution"),
                quality_profile=s.get("quality_profile"),
                bandwidth=num(s.get("bandwidth")),
                stream_bitrate=num(s.get("stream_bitrate")),
                progress_percent=num(s.get("progress_percent")),
                started_at=datetime.fromtimestamp(started, UTC),
                ended_at=datetime.fromtimestamp(ended, UTC),
                seconds=round(seconds, 1),
            )
        db.add(event)
        db.flush()
        try:
            from app.services import stalls, streams
            from app.settings_store import current

            settings = current()
            event.cause, event.cause_detail = stalls.classify(
                db, event, streams.upload_capacity()[0], int(settings.upload_alert_percent or 90)
            )
        except Exception:  # noqa: BLE001 - a cause is a bonus; the stall itself is kept
            log.exception("could not classify a stall")

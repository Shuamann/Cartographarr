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
    last_session: dict[str, Any] = field(default_factory=dict)


_tracks: dict[str, Track] = {}


def observe(sessions: list[dict[str, Any]], now: float | None = None) -> None:
    """Update every stream's history from one activity poll."""
    now = time.time() if now is None else now
    seen: set[str] = set()

    for session in sessions:
        key = str(session.get("session_key"))
        seen.add(key)
        state = str(session.get("state") or "").lower() or None
        track = _tracks.get(key)
        if track is None:
            track = Track(session_key=key, first_seen=now, last_seen=now, state=state, state_since=now)
            _tracks[key] = track
            if state == BUFFERING:
                track.buffer_count = 1
                track.buffer_started = now
        elif state != track.state:
            if track.state == BUFFERING:
                _end_buffering(track, now)
            if state == BUFFERING:
                track.buffer_count += 1
                track.buffer_started = now
            track.state = state
            track.state_since = now
        track.last_seen = now
        track.last_session = session

    # A stream no longer in activity has ended. Close any stall it was in.
    for key in [k for k in _tracks if k not in seen]:
        track = _tracks.pop(key)
        if track.state == BUFFERING:
            _end_buffering(track, track.last_seen)


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


def _end_buffering(track: Track, ended: float) -> None:
    started = track.buffer_started or ended
    seconds = max(ended - started, 0.0)
    track.buffer_seconds += seconds
    track.buffer_started = None
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
        db.add(
            StreamEvent(
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
        )

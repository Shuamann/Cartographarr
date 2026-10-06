"""Plays written down as they finish, for an install with no Tautulli.

History is the record everything else is built from: the History tab, the map,
Endpoints, the sharing signals, the people list. Until now only the Tautulli
sync wrote it, so an install connected to Plex alone had all of those empty
while it watched every stream go by. The live tracker already follows each
stream from start to end, so when one ends it is written here as a play.

One row per stream, which is one Plex session, because that is how the
Tautulli sync counts too: it asks for one row per session so that a play
carried from a phone to a television keeps both. A pause inside a session
stays one play. Stopping and starting again is a new session in Plex and a new
row in both.

Only while Tautulli is not connected. With it connected the sync writes these
plays, and writing them here as well would count every one twice. The ids are
negative, the stream record's own id turned over, so they can never meet one of
Tautulli's, and when Tautulli is connected later the sync removes any play of
its own that it finds here already (see drop_duplicates).
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

MIN_SECONDS = 30
"""Shorter than this is a stream somebody opened and closed, not a play.
Tautulli ignores the same, at the same length, by default."""

SAME_PLAY_SECONDS = 120
"""How far apart two records of one play may say it started. Tautulli writes
the time Plex reported the session; this app writes the poll that first saw it,
which can be a poll or two later."""


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _flag(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return bool(_int(value))
    return bool(value)


def play_row(stream_id: int, session: dict[str, Any], stream: dict[str, Any], started: float, stopped: float,
             paused: float) -> dict[str, Any] | None:
    """The History row for one finished stream, in the columns the sync
    writes, or None for something too short to be a play."""
    elapsed = max(0, int(stopped - started))
    played = max(0, int(elapsed - paused))
    if played < MIN_SECONDS:
        return None
    row_id = -int(stream_id)
    return {
        "row_id": row_id,
        "reference_id": row_id,
        "user_id": _int(session.get("user_id")),
        "machine_id": session.get("machine_id"),
        "ip_address": session.get("ip_address") or None,
        "started": int(started),
        "stopped": int(stopped),
        "duration": elapsed,
        "play_duration": played,
        "paused_counter": int(paused),
        "percent_complete": _int(session.get("progress_percent")),
        "media_type": session.get("media_type"),
        "section_id": _int(session.get("section_id")),
        "rating_key": _int(session.get("rating_key")),
        "parent_rating_key": _int(session.get("parent_rating_key")),
        "grandparent_rating_key": _int(session.get("grandparent_rating_key")),
        "title": session.get("title"),
        "full_title": session.get("full_title"),
        "grandparent_title": session.get("grandparent_title"),
        "parent_media_index": _int(session.get("parent_media_index")),
        "media_index": _int(session.get("media_index")),
        "year": _int(session.get("year")),
        "thumb": session.get("thumb"),
        "live": False,
        "platform": session.get("platform"),
        "player": session.get("player"),
        "product": session.get("product"),
        # The worst decision seen while it played, as the stream record keeps
        # it: a stream that went to a transcode halfway through was one.
        "transcode_decision": stream.get("transcode_decision") or session.get("transcode_decision"),
        "location": session.get("location"),
        "secure": _flag(session.get("secure")),
        "relayed": _flag(session.get("relayed")),
    }


def record(stream_id: int | None, session: dict[str, Any], stream: dict[str, Any], started: float,
           stopped: float, paused: float) -> None:
    """Write one finished stream as a play. Never raises: the tracker calls
    this from the enforcer's poll, and losing a play must not stop that."""
    from app.settings_store import tautulli_configured

    if stream_id is None or tautulli_configured():
        return
    row = play_row(stream_id, session, stream, started, stopped, paused)
    if row is None:
        return
    try:
        from app.db import session_scope
        from app.models import History, User
        from app.services.sync import _upsert

        with session_scope() as db:
            _upsert(db, History, [row])
            # Somebody who plays has a name, even with no Tautulli to list the
            # server's users: Plex says who it is with every stream.
            uid = row["user_id"]
            person = db.get(User, uid) if uid is not None else None
            if uid is not None and person is None:
                db.add(User(
                    user_id=uid,
                    username=session.get("username"),
                    friendly_name=session.get("friendly_name") or session.get("username"),
                    thumb=session.get("user_thumb"),
                    last_seen=row["stopped"],
                ))
            elif person is not None:
                person.last_seen = max(person.last_seen or 0, row["stopped"])
    except Exception:  # noqa: BLE001
        log.exception("could not record a play")


def drop_duplicates(db, rows: list[dict[str, Any]]) -> int:
    """Remove plays recorded here that Tautulli has now delivered too.

    For an install that ran on Plex alone and then connected a Tautulli that
    had been watching all along. The same play, by the same person, of the
    same item, starting within a couple of minutes, is one play, and
    Tautulli's copy is the one kept: it carries more.
    """
    from sqlalchemy import delete, select

    from app.models import History

    wanted = [(r.get("user_id"), r.get("rating_key"), r.get("started")) for r in rows
              if r.get("user_id") is not None and r.get("rating_key") is not None and r.get("started")]
    if not wanted:
        return 0
    users = sorted({u for u, _, _ in wanted})
    keys = sorted({k for _, k, _ in wanted})
    ours = db.execute(
        select(History.row_id, History.user_id, History.rating_key, History.started)
        .where(History.row_id < 0, History.user_id.in_(users), History.rating_key.in_(keys))
    ).all()
    if not ours:
        return 0
    theirs: dict[tuple[int, int], list[int]] = {}
    for user, key, started in wanted:
        theirs.setdefault((user, key), []).append(int(started))
    gone = [
        row_id for row_id, user, key, started in ours
        if started is not None and any(abs(started - t) <= SAME_PLAY_SECONDS for t in theirs.get((user, key), []))
    ]
    if gone:
        db.execute(delete(History).where(History.row_id.in_(gone)))
    return len(gone)

"""Plays written down from Plex as they finish, for an install with no Tautulli.

Without these, an install on Plex alone had an empty History, an empty map and
an empty Endpoints for ever, while it watched every stream go by. The counting
has to agree with the Tautulli sync's, or every figure in the app moves the day
somebody connects Tautulli: one row per Plex session, nothing too short to be a
play, and never the same play twice.
"""

import asyncio

from app.services import recorded, tracker
from tests.test_auth import claim

T0 = 1_760_000_000


def no_tautulli(monkeypatch):
    from app import settings_store

    monkeypatch.delenv("TAUTULLI_URL", raising=False)
    monkeypatch.delenv("TAUTULLI_API_KEY", raising=False)
    settings_store.invalidate()
    settings_store.save({"plex_token": "t", "plex_url": "http://plex.example.test:32400",
                         "activity_source": "plex", "library_source": "plex"})


def live(state="playing", key="7", **over):
    """A session as the Plex adapter hands it on, in Tautulli's field names."""
    base = {
        "session_key": key, "session_id": f"s{key}", "state": state, "user_id": 21, "username": "river",
        "friendly_name": "River", "machine_id": "tv-1", "player": "Living Room", "platform": "Roku",
        "product": "Plex for Roku", "ip_address": "203.0.113.40", "location": "wan", "secure": True,
        "relayed": False, "media_type": "episode", "rating_key": 880, "grandparent_rating_key": 500,
        "section_id": 2, "title": "Turf War", "full_title": "The Office - Turf War", "grandparent_title": "The Office",
        "parent_media_index": 8, "media_index": 23, "year": 2012, "progress_percent": 40,
        "transcode_decision": "direct play",
    }
    return {**base, **over}


def plays():
    from app.db import session_scope
    from app.models import History

    with session_scope() as db:
        return [
            {c: getattr(h, c) for c in ("row_id", "reference_id", "user_id", "started", "stopped", "duration",
                                         "play_duration", "paused_counter", "percent_complete",
                                         "transcode_decision", "ip_address", "machine_id", "rating_key")}
            for h in db.query(History).order_by(History.row_id).all()
        ]


def test_a_finished_stream_becomes_one_play(client, monkeypatch):
    """Paused in the middle is still one play, and the pause is not counted
    as watching. The worst decision seen while it played is the one kept."""
    from app.db import session_scope
    from app.models import User

    no_tautulli(monkeypatch)
    claim(client)
    tracker.reset()
    tracker.observe([live()], now=T0)
    tracker.observe([live("paused")], now=T0 + 600)
    tracker.observe([live("playing", transcode_decision="transcode", progress_percent=60)], now=T0 + 900)
    tracker.observe([live(progress_percent=95)], now=T0 + 2400)
    tracker.observe([], now=T0 + 2410)

    [play] = plays()
    assert play["row_id"] < 0 and play["reference_id"] == play["row_id"]
    assert (play["started"], play["stopped"]) == (T0, T0 + 2400)
    assert play["duration"] == 2400 and play["paused_counter"] == 300 and play["play_duration"] == 2100
    assert play["percent_complete"] == 95 and play["transcode_decision"] == "transcode"
    assert (play["user_id"], play["machine_id"], play["ip_address"], play["rating_key"]) == (21, "tv-1", "203.0.113.40", 880)
    # Somebody who plays has a name, with no Tautulli to list the users.
    with session_scope() as db:
        assert db.get(User, 21).friendly_name == "River"


def test_a_stream_opened_and_closed_is_not_a_play(client, monkeypatch):
    no_tautulli(monkeypatch)
    claim(client)
    tracker.reset()
    tracker.observe([live()], now=T0)
    tracker.observe([live()], now=T0 + 20)
    tracker.observe([], now=T0 + 25)
    assert plays() == []


def test_two_sessions_are_two_plays(client, monkeypatch):
    """Stopped and started again is a new session in Plex, and a new row in
    the Tautulli sync too, which asks for one row per session."""
    no_tautulli(monkeypatch)
    claim(client)
    tracker.reset()
    tracker.observe([live(key="7")], now=T0)
    tracker.observe([live(key="7")], now=T0 + 590)
    tracker.observe([], now=T0 + 600)
    tracker.observe([live(key="8")], now=T0 + 700)
    tracker.observe([live(key="8")], now=T0 + 1390)
    tracker.observe([], now=T0 + 1400)
    assert len(plays()) == 2


def test_nothing_is_written_here_while_tautulli_writes_it(client):
    """With Tautulli connected the sync records these plays. Writing them here
    as well would count every one twice."""
    claim(client)
    tracker.reset()
    tracker.observe([live()], now=T0)
    tracker.observe([live()], now=T0 + 590)
    tracker.observe([], now=T0 + 600)
    assert plays() == []


def test_tautulli_connected_later_replaces_the_plays_it_also_has(client, monkeypatch):
    """An install that ran on Plex alone, then connected a Tautulli that had
    been watching all along. The same play, from both, is one play, and
    Tautulli's is the one kept: it carries more."""
    from app.db import session_scope
    from app.services import sync

    no_tautulli(monkeypatch)
    claim(client)
    tracker.reset()
    tracker.observe([live()], now=T0)
    tracker.observe([live()], now=T0 + 590)
    tracker.observe([], now=T0 + 600)
    tracker.observe([live(key="9", rating_key=40)], now=T0 + 5000)
    tracker.observe([live(key="9", rating_key=40)], now=T0 + 5590)
    tracker.observe([], now=T0 + 5600)
    assert len(plays()) == 2

    theirs = {"row_id": 9001, "reference_id": 9001, "user_id": 21, "rating_key": 880, "started": T0 - 40}
    with session_scope() as db:
        sync._upsert(db, sync.History, [theirs])
        assert recorded.drop_duplicates(db, [theirs]) == 1
    left = plays()
    assert [p["row_id"] for p in left if p["row_id"] < 0] and 9001 in [p["row_id"] for p in left]
    # The other play, of something Tautulli did not deliver, stays.
    assert len(left) == 2


def test_the_sync_builds_devices_and_history_from_recorded_plays(client, monkeypatch):
    """With no Tautulli the sync has nothing to read, but the devices, places
    and sharing signals are built from plays, and those are here now."""
    from app import main
    from app.db import session_scope
    from app.models import Device

    no_tautulli(monkeypatch)
    claim(client)
    tracker.reset()
    tracker.observe([live()], now=T0)
    tracker.observe([live()], now=T0 + 590)
    tracker.observe([], now=T0 + 600)

    result = asyncio.run(main._cycle())
    assert result["history"] == 0 and result["devices"] >= 1
    with session_scope() as db:
        device = db.query(Device).filter(Device.machine_id == "tv-1", Device.user_id == 21).one()
        assert device.play_count == 1
    listed = client.get("/api/history").json()
    assert listed["total"] == 1
    assert client.post("/api/sync/run").status_code == 200


def test_a_recorded_play_says_where_its_detail_is_not(client, monkeypatch):
    no_tautulli(monkeypatch)
    claim(client)
    tracker.reset()
    tracker.observe([live()], now=T0)
    tracker.observe([live()], now=T0 + 590)
    tracker.observe([], now=T0 + 600)
    [play] = plays()
    detail = client.get(f"/api/history/{play['row_id']}").json()
    assert detail["stream"] is None and "Recorded from Plex" in detail["stream_error"]

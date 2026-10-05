"""A device that is streaming has a page, whether or not it has finished a play.

The device inventory is rebuilt from history by a GROUP BY, and history only
gets a play once Tautulli has finished recording it. So the player name on the
dashboard, which links straight to the device, answered "No such device" for
anything playing for the first time.
"""

from tests.test_auth import claim


def a_session(key="s1", machine="ps5-099", user=1, player="PS5-099", platform="PlayStation"):
    return {
        "session_key": key,
        "machine_id": machine,
        "user_id": user,
        "player": player,
        "platform": platform,
        "product": "Plex for PlayStation 5",
        "state": "playing",
    }


def test_a_device_streaming_for_the_first_time_can_be_opened(client):
    from app.services import tracker

    claim(client)
    tracker._tracks.clear()

    # Nothing has ever finished, so history and the inventory are both empty.
    assert client.get("/api/devices/ps5-099").status_code == 404

    tracker.observe([a_session()], now=1_000_000.0)
    found = client.get("/api/devices/ps5-099")
    assert found.status_code == 200
    body = found.json()
    assert body["machine_id"] == "ps5-099"
    assert body["player"] == "PS5-099" and body["platform"] == "PlayStation"


def test_the_first_device_ever_seen_is_not_flagged_as_new(client):
    """On a fresh install everything is unknown, and flagging the lot is noise.
    refresh_devices makes the same call for the same reason."""
    from app.db import session_scope
    from app.models import Device
    from app.services import tracker

    claim(client)
    tracker._tracks.clear()
    tracker.observe([a_session()], now=1_000_000.0)
    with session_scope() as db:
        first = db.query(Device).filter(Device.machine_id == "ps5-099").one()
        assert not first.is_new_unreviewed

    # Now that the app knows of a device, the next one is genuinely new.
    tracker._tracks.clear()
    tracker.observe([a_session(key="s2", machine="roku-7", user=2, player="Roku Ultra", platform="Roku")],
                    now=1_000_100.0)
    with session_scope() as db:
        later = db.query(Device).filter(Device.machine_id == "roku-7").one()
        assert later.is_new_unreviewed


def test_a_stream_that_keeps_playing_is_written_once(client):
    """Not a write every five seconds for the length of a film."""
    from app.db import session_scope
    from app.models import Device
    from app.services import tracker

    claim(client)
    tracker._tracks.clear()
    tracker.observe([a_session()], now=1_000_000.0)
    with session_scope() as db:
        was = db.query(Device).filter(Device.machine_id == "ps5-099").one().last_seen

    # The same stream, still going, several polls later.
    for tick in range(1, 5):
        tracker.observe([a_session()], now=1_000_000.0 + tick * 5)
    with session_scope() as db:
        rows = db.query(Device).filter(Device.machine_id == "ps5-099").all()
        assert len(rows) == 1
        assert rows[0].last_seen == was


def test_what_history_knows_is_not_overwritten(client):
    """The GROUP BY over all of history is the authority for the earliest
    sighting and the play count; a live sighting only knows about now."""
    from app.db import session_scope
    from app.models import Device
    from app.services import tracker

    claim(client)
    tracker._tracks.clear()
    with session_scope() as db:
        db.add(Device(machine_id="ps5-099", user_id=1, player="old name", first_seen=1, last_seen=2,
                      play_count=57, is_new_unreviewed=True))

    tracker.observe([a_session()], now=1_000_000.0)
    with session_scope() as db:
        row = db.query(Device).filter(Device.machine_id == "ps5-099").one()
        assert row.first_seen == 1, "the earliest sighting is never moved forward"
        assert row.play_count == 57, "the play count belongs to history"
        assert row.is_new_unreviewed, "reviewing is not undone by it playing again"
        assert row.last_seen == 1_000_000
        assert row.player == "PS5-099", "but what it calls itself now is current"


def test_a_session_without_a_user_is_skipped(client):
    from app.db import session_scope
    from app.models import Device
    from app.services import tracker

    claim(client)
    tracker._tracks.clear()
    tracker.observe([{**a_session(), "user_id": None}], now=1_000_000.0)
    tracker.observe([{**a_session(key="s3"), "machine_id": None}], now=1_000_010.0)
    with session_scope() as db:
        assert db.query(Device).count() == 0

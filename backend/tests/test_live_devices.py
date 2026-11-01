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
    """On a fresh install everything is unknown, and flagging the lot is noise."""
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


def test_a_ban_made_mid_stream_knows_who_and_what_it_banned(client):
    from app.db import session_scope
    from app.models import BannedDevice
    from app.services import tracker

    claim(client)
    tracker._tracks.clear()
    machine = "ps5-099-abcdef0123456789"

    # The device is playing, which is when somebody reaches for Ban.
    tracker.observe([a_session(machine=machine, user=7)], now=1_000_000.0)
    assert client.post("/api/bans", json={"machine_id": machine}).status_code == 200

    with session_scope() as db:
        row = db.get(BannedDevice, machine)
        assert row.label == "PS5-099", "not a slice of the machine id"
        assert row.user_id == 7, "a ban with no user counts against nobody"


def test_the_ban_list_answers_to_the_ban_list_switch(client):
    """Both halves of it, devices and addresses."""
    from app.services import enforcer
    from app.settings_store import save

    claim(client)
    save({"ban_record_only": False, "geo_block_record_only": True, "enforce_dry_run": False})

    addresses = enforcer.Rule(
        id=enforcer.ADDRESS_BAN_ID, name=enforcer.ADDRESS_RULE_NAME, enabled=True,
        action="terminate", message="", conditions="{}", actions="[]",
    )
    devices = enforcer.Rule(
        id=enforcer.DEVICE_BAN_ID, name=enforcer.BAN_RULE_NAME, enabled=True,
        action="terminate", message="", conditions="{}", actions="[]",
    )
    country = enforcer.Rule(
        id=-1, name=enforcer.COUNTRY_RULE_NAME, enabled=True,
        action="terminate", message="", conditions="{}", actions="[]",
    )

    assert not enforcer.record_only(devices), "the ban list is set to act"
    assert not enforcer.record_only(addresses), "and addresses are the ban list"
    assert enforcer.record_only(country), "the country list is still only recording"

    # And the other way round, so neither is wired to the wrong switch.
    save({"ban_record_only": True, "geo_block_record_only": False})
    assert enforcer.record_only(devices) and enforcer.record_only(addresses)
    assert not enforcer.record_only(country)


def a_ban_rule(which="device"):
    from app.services import enforcer

    return enforcer.Rule(
        id=enforcer.DEVICE_BAN_ID if which == "device" else enforcer.ADDRESS_BAN_ID,
        name=enforcer.BAN_RULE_NAME if which == "device" else enforcer.ADDRESS_RULE_NAME,
        enabled=True, action="terminate", message="", conditions="{}", actions="[]",
    )


def test_a_ban_acts_on_a_fresh_install(client):
    """Out of the box, with nothing configured, a ban stops the stream."""
    from app.services import enforcer

    claim(client)
    for which in ("device", "address"):
        assert not enforcer.record_only(a_ban_rule(which)), which


def test_the_environment_lock_still_wins(client):
    """Set as an env var, enforce_dry_run is a safety lock over everything."""
    from unittest.mock import patch

    from app.services import enforcer

    claim(client)
    with patch.object(enforcer, "dry_run_locked", return_value=True):
        assert enforcer.record_only(a_ban_rule("device"))
        assert enforcer.record_only(a_ban_rule("address"))


def test_asking_for_record_only_is_still_honoured(client):
    from app.services import enforcer
    from app.settings_store import save

    claim(client)
    save({"ban_record_only": True})
    assert enforcer.record_only(a_ban_rule("device"))
    assert enforcer.record_only(a_ban_rule("address"))

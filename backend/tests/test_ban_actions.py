import asyncio
from datetime import UTC, datetime

from app.actions import registry
from app.db import session_scope
from app.models import BannedAddress, BannedDevice, Device

SESSION = {
    "session_key": "42",
    "user_id": 7,
    "machine_id": "00000000-1111-2222-3333-444444444444",
    "player": "The bedroom stick",
    "ip_address": "203.0.113.9",
    "geo": {"city": "Topeka", "country": "United States"},
}


def run(name: str, session: dict, **params) -> str:
    action = registry.get(name)
    assert action is not None, name
    return asyncio.run(action.execute(session, params))


# ---- what it writes ----------------------------------------------------------

def test_banning_a_device_adds_it_to_the_list(client):
    said = run("ban_device", SESSION, hours="24", reason="Kept coming back")

    with session_scope() as db:
        ban = db.get(BannedDevice, SESSION["machine_id"])
        assert ban is not None
        assert ban.label == "The bedroom stick"
        assert ban.user_id == 7
        assert ban.reason == "Kept coming back"
        # Who did it, so the list does not look like somebody's decision.
        assert ban.banned_by == "a rule"
        assert ban.expires_at is not None
    assert "banned" in said


def test_a_rule_ban_is_timed_unless_told_otherwise(client):
    """A rule acting on its own should not make a permanent decision quietly."""
    run("ban_device", SESSION)

    with session_scope() as db:
        ban = db.get(BannedDevice, SESSION["machine_id"])
        hours = (ban.expires_at - datetime.now(UTC).replace(tzinfo=None)).total_seconds() / 3600
        assert 23 < hours <= 24


def test_it_can_be_told_to_ban_for_good(client):
    run("ban_device", SESSION, hours="0")
    with session_scope() as db:
        assert db.get(BannedDevice, SESSION["machine_id"]).expires_at is None


def test_banning_an_address_records_where_it_was(client):
    run("ban_address", SESSION, hours="168")

    with session_scope() as db:
        ban = db.get(BannedAddress, "203.0.113.9")
        assert ban is not None
        assert ban.label == "Topeka, United States"
        assert ban.banned_by == "a rule"


def test_the_label_falls_back_to_the_device_on_record(client):
    with session_scope() as db:
        db.add(Device(machine_id=SESSION["machine_id"], user_id=7, player="Known by name"))

    run("ban_device", {**SESSION, "player": None})

    with session_scope() as db:
        assert db.get(BannedDevice, SESSION["machine_id"]).label == "Known by name"


# ---- and when it must not act ------------------------------------------------

def test_a_stream_with_no_device_is_an_error_not_a_silent_pass(client):
    """Silently doing nothing would read as a working rule in the Log."""
    try:
        run("ban_device", {**SESSION, "machine_id": None})
    except RuntimeError as exc:
        assert "no device" in str(exc)
    else:
        raise AssertionError("banning nothing should have raised")


def test_a_stream_with_no_address_is_too(client):
    try:
        run("ban_address", {**SESSION, "ip_address": None})
    except RuntimeError as exc:
        assert "no address" in str(exc)
    else:
        raise AssertionError("banning nothing should have raised")


def test_banning_what_is_already_banned_changes_nothing(client):
    """Including the reason and the expiry somebody set by hand."""
    run("ban_device", SESSION, hours="0", reason="By hand")
    run("ban_device", SESSION, hours="1", reason="By a rule")

    with session_scope() as db:
        ban = db.get(BannedDevice, SESSION["machine_id"])
        assert ban.reason == "By hand" and ban.expires_at is None


# ---- how it is offered -------------------------------------------------------

def test_both_are_offered_as_rule_actions(client):
    names = {a["name"] for a in [{"name": a.name, "param_schema": a.param_schema} for a in registry.all_actions()]}
    assert {"ban_device", "ban_address"} <= names


def test_the_length_is_a_list_rather_than_a_box(client):
    """Typing a number of hours into a text area is not a question anybody should be asked."""
    spec = next(a for a in [{"name": a.name, "param_schema": a.param_schema} for a in registry.all_actions()] if a["name"] == "ban_device")
    options = spec["param_schema"]["hours"]["options"]
    assert [o["value"] for o in options] == ["1", "24", "168", "720", "0"]
    assert spec["param_schema"]["hours"]["default"] == "24"

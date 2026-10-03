"""Banning an address rather than a device.

A device ban follows one machine. It is the right tool until the machine comes
back under a new identifier, or until the thing worth stopping is the household
rather than one box in it. Then the connection is what you have.

The cases that matter are the ones where it must not match: a ban on one
address must not take out the neighbour, and a range must mean exactly the
range that was typed.
"""

from datetime import UTC, datetime, timedelta

from app.db import session_scope
from app.models import BannedAddress
from app.services import enforcer
from tests.test_auth import claim

SESSION = {
    "session_key": "42",
    "user_id": 123,
    "machine_id": "00000000-1111-2222-3333-444444444444",
    "ip_address": "203.0.113.9",  # RFC 5737 documentation range
    "state": "playing",
}
CONTEXT = {"user_stream_count": 1}


def ban(address: str, **over) -> None:
    with session_scope() as db:
        db.add(BannedAddress(address=address, banned_at=datetime.now(UTC), **over))


# ---- the rule ---------------------------------------------------------------

def test_no_banned_addresses_is_no_rule(client):
    """An empty list must not become a rule that matches everything."""
    assert enforcer.address_ban_rule() is None


def test_a_banned_address_matches_that_address(client):
    ban("203.0.113.9")
    rule = enforcer.address_ban_rule()
    assert rule is not None
    assert enforcer.matches(rule, SESSION, CONTEXT) is True


def test_it_does_not_match_the_neighbour(client):
    ban("203.0.113.9")
    rule = enforcer.address_ban_rule()
    assert enforcer.matches(rule, {**SESSION, "ip_address": "203.0.113.10"}, CONTEXT) is False


def test_a_range_covers_what_is_in_it_and_nothing_else(client):
    ban("203.0.113.0/29")
    rule = enforcer.address_ban_rule()
    assert enforcer.matches(rule, {**SESSION, "ip_address": "203.0.113.4"}, CONTEXT) is True
    assert enforcer.matches(rule, {**SESSION, "ip_address": "203.0.113.99"}, CONTEXT) is False


def test_an_expired_ban_is_not_in_the_rule(client):
    ban("203.0.113.9", expires_at=datetime.now(UTC) - timedelta(hours=1))
    assert enforcer.address_ban_rule() is None


def test_an_expired_ban_is_swept_up(client):
    ban("203.0.113.9", expires_at=datetime.now(UTC) - timedelta(hours=1))
    assert enforcer.expire_bans() == 1
    with session_scope() as db:
        assert db.get(BannedAddress, "203.0.113.9") is None


# ---- the endpoints ----------------------------------------------------------

def test_banning_and_unbanning_an_address(client):
    claim(client)
    assert client.post("/api/address-bans", json={"address": "203.0.113.9", "reason": "sharing"}).status_code == 200

    listed = client.get("/api/address-bans").json()
    assert [row["address"] for row in listed] == ["203.0.113.9"]
    assert listed[0]["reason"] == "sharing"

    assert client.delete("/api/address-bans/203.0.113.9").status_code == 200
    assert client.get("/api/address-bans").json() == []


def test_a_range_is_accepted_as_typed(client):
    claim(client)
    assert client.post("/api/address-bans", json={"address": "203.0.113.0/24"}).status_code == 200
    assert [r["address"] for r in client.get("/api/address-bans").json()] == ["203.0.113.0/24"]


def test_something_that_is_not_an_address_is_refused(client):
    claim(client)
    answer = client.post("/api/address-bans", json={"address": "the bedroom roku"})
    assert answer.status_code == 400
    assert "not an address" in answer.json()["detail"]


def test_banning_the_same_address_twice_is_refused(client):
    claim(client)
    client.post("/api/address-bans", json={"address": "203.0.113.9"})
    assert client.post("/api/address-bans", json={"address": "203.0.113.9"}).status_code == 409


def test_banning_an_address_is_admin_only(client):
    assert client.post("/api/address-bans", json={"address": "203.0.113.9"}).status_code in (401, 403)

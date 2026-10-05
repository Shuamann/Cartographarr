"""The address list.

A person, a device and an address are three ways of asking the same question,
and only two of them had a list. The detail view for an address already existed
and already worked; there was no way in to it, which is why clicking an address
anywhere went to the map instead.
"""

import time

from tests.test_auth import claim


def seed():
    from app.db import session_scope
    from app.models import BannedAddress, History, IpLocation, User

    now = int(time.time())
    with session_scope() as db:
        db.add(User(user_id=1, username="alpha", friendly_name="Alpha"))
        db.add(User(user_id=2, username="beta", friendly_name="Beta"))
        db.add(IpLocation(ip="198.51.100.1", city="Springfield", country="United States",
                          asn_org="Home ISP", is_hosting=False))
        db.add(IpLocation(ip="203.0.113.9", city="Nowhere", country="Elsewhere",
                          asn_org="Cloud VPN", is_hosting=True))
        plays = [
            (1, 1, "tv", "198.51.100.1", now - 60),
            (2, 1, "phone", "198.51.100.1", now - 120),
            (3, 2, "laptop", "198.51.100.1", now - 180),
            (4, 1, "tv", "203.0.113.9", now - 9000),
        ]
        for row_id, user, machine, ip, started in plays:
            db.add(History(row_id=row_id, user_id=user, machine_id=machine,
                           ip_address=ip, started=started, rating_key=100 + row_id))
        db.add(BannedAddress(address="203.0.113.0/24", banned_by="admin"))


def test_every_address_anyone_played_from(client):
    claim(client)
    seed()
    rows = client.get("/api/addresses").json()
    by_ip = {r["ip_address"]: r for r in rows}
    assert set(by_ip) == {"198.51.100.1", "203.0.113.9"}

    busy = by_ip["198.51.100.1"]
    assert busy["plays"] == 3
    assert busy["users"] == 2 and busy["devices"] == 3
    assert busy["city"] == "Springfield" and busy["asn_org"] == "Home ISP"
    assert busy["is_hosting"] is False
    # Newest first, which is how somebody looks for what just happened.
    assert rows[0]["ip_address"] == "198.51.100.1"


def test_an_address_inside_a_banned_range_reads_as_banned(client):
    """The ban is written against the block, not the address."""
    claim(client)
    seed()
    rows = {r["ip_address"]: r for r in client.get("/api/addresses").json()}
    assert rows["203.0.113.9"]["banned"] is True
    assert rows["198.51.100.1"]["banned"] is False
    assert rows["203.0.113.9"]["is_hosting"] is True


def test_searching_the_addresses(client):
    claim(client)
    seed()
    assert [r["ip_address"] for r in client.get("/api/addresses?search=203.0").json()] == ["203.0.113.9"]


def test_a_viewer_sees_only_addresses_they_played_from(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "own")
    rows = client.get("/api/addresses").json()
    # The viewer fixture's own plays only, never everybody's.
    assert all(r["users"] <= 1 for r in rows), rows

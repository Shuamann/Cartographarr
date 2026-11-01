import time

from tests.test_auth import claim


def seed():
    from app.db import session_scope
    from app.models import Device, History, User

    now = int(time.time())
    with session_scope() as db:
        db.add(User(user_id=1, username="alpha", friendly_name="Alpha"))
        db.add(User(user_id=2, username="beta", friendly_name="Beta"))
        db.add(Device(machine_id="tv", user_id=1, player="The TV", last_seen=now))
        db.add(Device(machine_id="phone", user_id=1, player="A Phone", last_seen=now))
        db.add(Device(machine_id="laptop", user_id=2, player="A Laptop", last_seen=now))
        plays = [
            (1, 1, "tv", "198.51.100.1"),
            (2, 1, "phone", "198.51.100.2"),
            (3, 2, "laptop", "198.51.100.1"),
        ]
        for row_id, user, machine, ip in plays:
            db.add(History(row_id=row_id, user_id=user, machine_id=machine,
                           ip_address=ip, started=now - row_id, rating_key=row_id))


def test_addresses_narrowed_by_person_and_device(client):
    claim(client)
    seed()
    everything = {a["ip_address"] for a in client.get("/api/addresses").json()}
    assert everything == {"198.51.100.1", "198.51.100.2"}

    alpha = {a["ip_address"] for a in client.get("/api/addresses?user_id=1").json()}
    assert alpha == {"198.51.100.1", "198.51.100.2"}
    beta = {a["ip_address"] for a in client.get("/api/addresses?user_id=2").json()}
    assert beta == {"198.51.100.1"}

    # Alpha, but only what the phone did: one address, not both.
    both = {a["ip_address"] for a in client.get("/api/addresses?user_id=1&machine_id=phone").json()}
    assert both == {"198.51.100.2"}


def test_people_narrowed_by_device_and_address(client):
    claim(client)
    seed()
    here = {u["user_id"] for u in client.get("/api/users?ip_address=198.51.100.1").json()}
    assert here == {1, 2}, "two people have played from this address"
    assert {u["user_id"] for u in client.get("/api/users?machine_id=laptop").json()} == {2}


def test_devices_narrowed_by_person_and_address(client):
    claim(client)
    seed()
    assert {d["machine_id"] for d in client.get("/api/devices?ip_address=198.51.100.1").json()} == {"tv", "laptop"}
    assert {d["machine_id"] for d in client.get("/api/devices?only_user_id=1").json()} == {"tv", "phone"}
    # Both at once, which is the point of it.
    narrow = client.get("/api/devices?only_user_id=1&ip_address=198.51.100.1").json()
    assert {d["machine_id"] for d in narrow} == {"tv"}


def test_several_of_one_kind_are_an_either_or(client):
    claim(client)
    seed()
    rows = client.get("/api/devices?ip_address=198.51.100.1&ip_address=198.51.100.2").json()
    assert {d["machine_id"] for d in rows} == {"tv", "phone", "laptop"}


def test_a_combination_nothing_matches_is_empty_not_everything(client):
    claim(client)
    seed()
    assert client.get("/api/addresses?user_id=999").json() == []
    assert client.get("/api/devices?only_user_id=2&ip_address=198.51.100.2").json() == []

"""Trusted devices, and the one thing trusting quiets.

The shared account signal fires when one account plays from two places too far
apart to be the same person. It catches real sharing and it also catches the
ordinary life of a household: a phone on mobile data, a laptop carried to
work, a VPN whose exit moves between cities. Trusting a device is how somebody
tells it which is which.
"""

import time

from tests.test_auth import claim

DAY = 86400


def _device(db, machine_id, user_id, plays=50, age_days=200, trusted=False):
    from datetime import UTC, datetime

    from app.models import Device

    now = int(time.time())
    db.add(Device(
        machine_id=machine_id, user_id=user_id, player=machine_id.title(), play_count=plays,
        first_seen=now - age_days * DAY, last_seen=now,
        trusted_at=datetime.now(UTC) if trusted else None,
    ))


def test_trusting_a_device_is_recorded_with_who_said_so(client):
    from app.db import session_scope
    from app.models import Device

    claim(client)
    with session_scope() as db:
        _device(db, "phone", 7)

    assert client.post("/api/devices/phone/trust").json()["trusted"] is True
    with session_scope() as db:
        device = db.query(Device).filter(Device.machine_id == "phone").one()
        assert device.trusted_at is not None and device.trusted_by

    assert client.post("/api/devices/phone/trust?trusted=false").json()["trusted"] is False
    with session_scope() as db:
        device = db.query(Device).filter(Device.machine_id == "phone").one()
        assert device.trusted_at is None and device.trusted_by is None


def test_trusting_is_per_account_not_per_device(client):
    """A device is one row per account that has used it. Vouching for one
    person's use of a shared television does not vouch for anybody else's."""
    from app.db import session_scope
    from app.models import Device

    claim(client)
    with session_scope() as db:
        _device(db, "telly", 7)
        _device(db, "telly", 9)

    client.post("/api/devices/telly/trust?user_id=7")
    with session_scope() as db:
        trusted = {d.user_id: d.trusted_at is not None for d in db.query(Device).filter(Device.machine_id == "telly")}
    assert trusted == {7: True, 9: False}


def test_a_pair_of_trusted_devices_raises_nothing(client, monkeypatch):
    from app.services import travel

    claim(client)
    from app.db import session_scope

    with session_scope() as db:
        _device(db, "phone", 7, trusted=True)
        _device(db, "laptop", 7, trusted=True)
    assert travel.trusted_devices() == {(7, "phone"), (7, "laptop")}


def test_half_a_trusted_pair_still_raises(client):
    """The case most worth seeing: a device somebody recognises playing
    alongside one they do not. Trusting one end must not quiet it."""
    from app.db import session_scope
    from app.services import travel

    claim(client)
    with session_scope() as db:
        _device(db, "phone", 7, trusted=True)
        _device(db, "stranger", 7)

    trusted = travel.trusted_devices()
    assert (7, "phone") in trusted and (7, "stranger") not in trusted


def test_the_rule_reads_both_ends(client):
    """Written against the source because the walk itself needs a database of
    plays with locations behind it, and the condition is the thing that was
    got wrong on the first attempt."""
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "travel.py").read_text(encoding="utf-8")
    at = source.index("trusted_devices()", source.index("def find_flags"))
    block = source[at : at + 1600]
    assert "(row.user_id, last.machine_id) in trusted" in block
    assert "(row.user_id, row.machine_id) in trusted" in block
    assert " and " in block, "both ends, not either"


def test_a_device_two_accounts_have_used_is_never_suggested(client):
    """That is the ambiguous case the signal exists for. No amount of history
    on one side makes up for it."""
    from app.db import session_scope
    from app.services import trust

    claim(client)
    with session_scope() as db:
        _device(db, "shared", 7, plays=900)
        _device(db, "shared", 9, plays=5)
        _device(db, "mine", 7, plays=50)

    assert [s["machine_id"] for s in trust.suggestions()] == ["mine"]


def test_a_device_with_little_history_or_little_age_is_not_suggested(client):
    from app.db import session_scope
    from app.services import trust

    claim(client)
    with session_scope() as db:
        _device(db, "barely-used", 7, plays=3)
        _device(db, "brand-new", 7, plays=200, age_days=2)
        _device(db, "settled", 7, plays=200, age_days=200)

    assert [s["machine_id"] for s in trust.suggestions()] == ["settled"]


def test_the_suggestions_can_be_taken_in_one_go_and_undone_one_at_a_time(client):
    from app.db import session_scope
    from app.models import Device

    claim(client)
    with session_scope() as db:
        _device(db, "phone", 7)
        _device(db, "laptop", 7)

    assert client.post("/api/devices/trust-suggested").json() == {"trusted": 2}
    assert client.get("/api/devices/trust-suggestions").json() == []
    client.post("/api/devices/phone/trust?trusted=false")
    with session_scope() as db:
        assert db.query(Device).filter(Device.trusted_at.is_not(None)).count() == 1


def test_the_listing_says_which_devices_are_trusted(client):
    from app.db import session_scope

    claim(client)
    with session_scope() as db:
        _device(db, "phone", 7, trusted=True)
        _device(db, "laptop", 7)

    rows = {d["machine_id"]: d["trusted_at"] for d in client.get("/api/devices").json()}
    assert rows["phone"] is not None and rows["laptop"] is None


def test_a_viewer_cannot_vouch_for_their_own_device(client):
    """It quiets a signal about them, which is marking their own homework."""
    claim(client)
    from app.db import session_scope

    with session_scope() as db:
        _device(db, "phone", 7)
    client.post("/api/auth/logout")
    assert client.post("/api/devices/phone/trust").status_code in (401, 403)


def test_a_literal_path_is_declared_before_the_one_with_a_placeholder():
    """/devices/{machine_id} swallowed /devices/trust-suggestions and answered
    "No such device", which reads as the feature being broken rather than as
    the route being in the wrong place.

    Only a route that could actually catch it counts: the same method, the
    same segments up to the placeholder, and the same number of segments
    overall. /history/{row_id} has never been a threat to /media/search.
    """
    import pathlib
    import re

    source = (pathlib.Path(__file__).resolve().parents[1] / "app" / "routers" / "data.py").read_text(encoding="utf-8")
    routes = re.findall(r'@router\.(get|post|put|delete)\("([^"]+)"', source)
    catchers: dict[tuple, str] = {}
    for method, path in routes:
        parts = path.strip("/").split("/")
        placeholder = next((i for i, p in enumerate(parts) if p.startswith("{")), None)
        if placeholder is not None:
            catchers.setdefault((method, tuple(parts[:placeholder]), len(parts)), path)
            continue
        for depth in range(len(parts)):
            caught = catchers.get((method, tuple(parts[:depth]), len(parts)))
            assert caught is None, f"{method} {path} is declared after {caught}, which will catch it first"


def _two_places_at_once(db, machine_a, machine_b):
    """One account playing in Kansas City and Miami fifty seconds apart, from
    two different devices. Nobody travels 2,000 km in fifty seconds, so this
    is the signal firing on exactly what it is for."""
    from app.models import History, IpLocation, User

    db.add(User(user_id=7, username="viewer7"))
    db.add(IpLocation(ip="203.0.113.1", city="Kansas City", lat=39.1, lon=-94.6, is_hosting=False))
    db.add(IpLocation(ip="203.0.113.2", city="Miami", lat=25.8, lon=-80.2, is_hosting=False))
    db.add(History(row_id=1, user_id=7, ip_address="203.0.113.1", machine_id=machine_a,
                   started=1000, stopped=2000, full_title="A Film"))
    db.add(History(row_id=2, user_id=7, ip_address="203.0.113.2", machine_id=machine_b,
                   started=2050, stopped=3000, full_title="A Show"))


def test_the_signal_fires_when_neither_device_is_trusted(client):
    """The control. Without this the next two tests prove nothing: a rule that
    quiets a signal looks identical to a rule that never fired."""
    from app.db import session_scope
    from app.services import travel
    from app.settings_store import current

    claim(client)
    with session_scope() as db:
        _device(db, "phone", 7)
        _device(db, "laptop", 7)
        _two_places_at_once(db, "phone", "laptop")

    travel.find_flags(current())
    assert len(client.get("/api/travel-flags").json()) == 1


def test_a_pair_of_trusted_devices_is_not_raised(client):
    """A phone on mobile data and a laptop carried to work are the same person
    every time, and the signal has no way to know it without being told."""
    from app.db import session_scope
    from app.services import travel
    from app.settings_store import current

    claim(client)
    with session_scope() as db:
        _device(db, "phone", 7, trusted=True)
        _device(db, "laptop", 7, trusted=True)
        _two_places_at_once(db, "phone", "laptop")

    travel.find_flags(current())
    assert client.get("/api/travel-flags").json() == []


def test_one_trusted_device_and_one_unknown_is_still_raised(client):
    """The case most worth seeing. A device somebody recognises playing
    alongside one they do not is what sharing looks like from the outside, so
    trusting half a pair has to leave the signal standing."""
    from app.db import session_scope
    from app.services import travel
    from app.settings_store import current

    claim(client)
    with session_scope() as db:
        _device(db, "phone", 7, trusted=True)
        _device(db, "stranger", 7)
        _two_places_at_once(db, "phone", "stranger")

    travel.find_flags(current())
    assert len(client.get("/api/travel-flags").json()) == 1


def test_trusting_a_device_for_somebody_else_does_not_quiet_this_account(client):
    """Trust is per account. The same television trusted for the person who
    owns it says nothing about the person who signed into it afterwards."""
    from app.db import session_scope
    from app.services import travel
    from app.settings_store import current

    claim(client)
    with session_scope() as db:
        _device(db, "phone", 7)
        _device(db, "phone", 9, trusted=True)
        _device(db, "laptop", 7)
        _device(db, "laptop", 9, trusted=True)
        _two_places_at_once(db, "phone", "laptop")

    travel.find_flags(current())
    assert len(client.get("/api/travel-flags").json()) == 1

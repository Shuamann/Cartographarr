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
    """A device is one row per account that has used it."""
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
    from app.db import session_scope
    from app.services import travel

    claim(client)
    with session_scope() as db:
        _device(db, "phone", 7, trusted=True)
        _device(db, "stranger", 7)

    trusted = travel.trusted_devices()
    assert (7, "phone") in trusted and (7, "stranger") not in trusted


def test_the_rule_reads_both_ends(client):
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "travel.py").read_text(encoding="utf-8")
    at = source.index("trusted_devices()", source.index("def find_flags"))
    block = source[at : at + 1600]
    assert "(row.user_id, last.machine_id) in trusted" in block
    assert "(row.user_id, row.machine_id) in trusted" in block
    assert " and " in block, "both ends, not either"


def test_a_device_two_accounts_have_used_is_never_suggested(client):
    """That is the ambiguous case the signal exists for."""
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


def every_route(routes):
    """Flattened, in the order a request is matched against them."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from every_route(inner.routes)
        else:
            yield route


def test_no_two_handlers_answer_the_same_path():
    from app.main import app

    seen: dict[tuple[str, str], int] = {}
    for route in every_route(app.routes):
        path, methods = getattr(route, "path", None), getattr(route, "methods", None)
        if not path or not methods:
            continue
        for method in methods:
            seen[(method, path)] = seen.get((method, path), 0) + 1
    twice = sorted(f"{method} {path}" for (method, path), n in seen.items() if n > 1)
    assert len(seen) > 100, f"only {len(seen)} routes seen, so this is not looking at the app"
    assert not twice, "Two handlers answer each of these, and only the first one ever runs: " + ", ".join(twice)


def test_a_literal_path_is_declared_before_the_one_with_a_placeholder():
    """A placeholder route swallows a literal one declared after it."""
    from app.main import app

    catchers: dict[tuple, str] = {}
    checked = 0
    for route in every_route(app.routes):
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        checked += 1
        parts = path.strip("/").split("/")
        placeholder = next((i for i, p in enumerate(parts) if p.startswith("{")), None)
        for method in methods:
            if placeholder is not None:
                catchers.setdefault((method, tuple(parts[:placeholder]), len(parts)), path)
                continue
            for depth in range(len(parts)):
                caught = catchers.get((method, tuple(parts[:depth]), len(parts)))
                assert caught is None, f"{method} {path} is declared after {caught}, which will catch it first"
    assert checked > 100, f"only {checked} routes seen, so this is not looking at the app"

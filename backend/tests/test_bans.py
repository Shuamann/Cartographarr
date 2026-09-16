"""The ban list.

It stops streams, so what matters is that it catches the banned device and
nothing else, and that it goes through the same path as every other rule.
"""

import json

from tests.test_auth import claim


def test_ban_rule_matches_only_banned_devices(client):
    from app.db import session_scope
    from app.models import BannedDevice
    from app.services import enforcer

    assert enforcer.ban_rule() is None  # nothing banned, no rule at all

    with session_scope() as db:
        db.add(BannedDevice(machine_id="bad-device", label="Bad"))

    rule = enforcer.ban_rule()
    assert rule is not None and rule.name == enforcer.BAN_RULE_NAME
    assert enforcer.matches(rule, {"session_key": "1", "machine_id": "bad-device"}, {}) is True
    assert enforcer.matches(rule, {"session_key": "2", "machine_id": "good-device"}, {}) is False
    # A session with no device id is never caught by the ban list.
    assert enforcer.matches(rule, {"session_key": "3"}, {}) is False
    assert json.loads(rule.actions)[0]["name"] == "terminate"


def test_ban_and_unban_are_admin_only_and_logged(client):
    claim(client)
    assert client.post("/api/bans", json={"machine_id": "dev-9", "reason": "shared login"}).status_code == 200
    assert client.post("/api/bans", json={"machine_id": "dev-9"}).status_code == 409
    assert [b["machine_id"] for b in client.get("/api/bans").json()] == ["dev-9"]
    assert client.delete("/api/bans/dev-9").status_code == 200
    assert client.get("/api/bans").json() == []

    actions = [e["action"] for e in client.get("/api/log?kind=changes").json()]
    assert "device.ban" in actions and "device.unban" in actions

    client.post(
        "/api/auth/users",
        json={"username": "viewer", "password": "a-long-enough-password", "role": "viewer"},
    )
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "viewer", "password": "a-long-enough-password"})
    assert client.post("/api/bans", json={"machine_id": "dev-10"}).status_code == 403


def test_map_shows_where_banned_devices_played_and_tried(client):
    from datetime import UTC, datetime

    from app.db import session_scope
    from app.models import BannedDevice, EnforcementLog, History, IpLocation
    from app.services import enforcer

    claim(client)
    with session_scope() as db:
        db.add(IpLocation(ip="203.0.113.1", lat=39.1, lon=-94.6, city="Kansas City"))
        db.add(History(row_id=1, machine_id="bad", ip_address="203.0.113.1", started=1700000000))
        db.add(History(row_id=2, machine_id="fine", ip_address="203.0.113.1", started=1700000001))
        db.add(BannedDevice(machine_id="bad", label="Bad TV"))
        db.add(
            EnforcementLog(
                machine_id="bad", rule_name=enforcer.BAN_RULE_NAME, lat=51.5, lon=-0.1,
                city="London", dry_run=False, acted_at=datetime.now(UTC),
            )
        )

    features = client.get("/api/map/banned").json()["features"]
    kinds = sorted((f["properties"]["kind"], f["properties"]["city"]) for f in features)
    assert kinds == [("attempt", "London"), ("seen", "Kansas City")]
    # A device that is not banned never appears, even at the same place.
    assert all(f["properties"]["machine_id"] == "bad" for f in features)


def test_only_device_only_rules_convert_into_the_ban_list(client):
    claim(client)
    device_only = {"type": "group", "op": "and", "items": [{"type": "condition", "field": "device", "op": "any", "value": ["dev-a", "dev-b"]}]}
    with_time = {"type": "group", "op": "and", "items": [
        {"type": "condition", "field": "device", "op": "any", "value": ["dev-c"]},
        {"type": "condition", "field": "time", "op": "between", "value": ["22:00", "06:00"]},
    ]}
    stop = [{"name": "terminate", "params": {}}]
    a = client.post("/api/rules", json={"name": "Block two", "conditions": device_only, "actions": stop}).json()
    b = client.post("/api/rules", json={"name": "Night only", "conditions": with_time, "actions": stop}).json()
    c = client.post("/api/rules", json={"name": "Just log", "conditions": device_only, "actions": [{"name": "log_only"}]}).json()

    assert [r["id"] for r in client.get("/api/bans/convertible").json()] == [a["id"]]
    # A rule that does more than ban is refused, not flattened into a ban.
    assert client.post("/api/bans/convert", json={"rule_ids": [b["id"]]}).status_code == 400

    result = client.post("/api/bans/convert", json={"rule_ids": [a["id"]]}).json()
    assert result == {"rules_removed": 1, "devices_banned": 2}
    assert sorted(x["machine_id"] for x in client.get("/api/bans").json()) == ["dev-a", "dev-b"]
    assert sorted(r["id"] for r in client.get("/api/rules").json()) == sorted([b["id"], c["id"]])

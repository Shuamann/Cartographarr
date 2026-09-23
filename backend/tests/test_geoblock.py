"""Blocked countries: flag, warn or stop, through the same path as any rule."""

import json

from tests.test_auth import claim

NOW = 1789570000


def seed(client):
    from app.db import session_scope
    from app.models import History, IpLocation

    claim(client)
    with session_scope() as db:
        db.add(IpLocation(ip="1.2.3.4", city="Pyongyang", country="North Korea", country_code="KP", lat=39, lon=125))
        db.add(IpLocation(ip="5.6.7.8", city="Denver", country="United States", country_code="US", lat=39.7, lon=-104.9))
        for row_id, ip, user in ((1, "1.2.3.4", 7), (2, "5.6.7.8", 7), (3, "5.6.7.8", 8)):
            db.add(History(row_id=row_id, reference_id=row_id, user_id=user, ip_address=ip, started=NOW,
                           media_type="movie", full_title="Film"))


def test_countries_are_listed_with_what_has_been_watched(client):
    seed(client)
    seen = {c["code"]: c for c in client.get("/api/geoblocks/countries").json()}
    assert seen["US"]["plays"] == 2 and seen["KP"]["name"] == "North Korea" and seen["KP"]["blocked"] is False

    listing = client.post("/api/geoblocks", json={"code": "kp", "mode": "stop", "reason": "Nobody is there"}).json()
    row = listing["items"][0]
    assert row["code"] == "KP" and row["name"] == "North Korea" and row["mode"] == "stop"
    assert row["plays"] == 1 and row["reason"] == "Nobody is there"
    assert client.get("/api/geoblocks/countries").json()[0]["code"] == "US"
    assert [c["code"] for c in client.get("/api/geoblocks/countries").json() if c["blocked"]] == ["KP"]

    actions = [e["action"] for e in client.get("/api/log?kind=changes").json()]
    assert "country.block" in actions
    assert client.post("/api/geoblocks", json={"code": "nope", "mode": "flag"}).status_code == 400
    assert client.post("/api/geoblocks", json={"code": "US", "mode": "sideways"}).status_code == 400


def test_each_mode_becomes_a_rule_and_a_ban_still_wins(client):
    from app.services import enforcer

    seed(client)
    client.post("/api/geoblocks", json={"code": "KP", "mode": "stop"})
    client.post("/api/geoblocks", json={"code": "RU", "mode": "flag"})
    client.post("/api/geoblocks", json={"code": "CN", "mode": "warn"})

    rules = enforcer.country_rules()
    by_action = {r.action: json.loads(r.conditions)["items"][0]["value"] for r in rules}
    assert by_action == {"log_only": ["RU"], "message_viewer": ["CN"], "terminate": ["KP"]}
    assert all(r.name == enforcer.COUNTRY_RULE_NAME and r.id < 0 for r in rules)
    # Every id is distinct, or two modes would share one cooldown.
    assert len({r.id for r in rules}) == 3


def test_an_allow_list_flags_everywhere_else(client):
    from app.services import enforcer

    seed(client)
    client.post("/api/geoblocks", json={"code": "US", "mode": "flag"})
    client.put("/api/geoblocks/settings", json={"allow_list": True})

    rule = enforcer.country_rules()[0]
    leaf = json.loads(rule.conditions)["items"][0]
    assert leaf["op"] == "none" and leaf["value"] == ["US"] and rule.action == "log_only"

    preview = client.get("/api/geoblocks/preview").json()
    assert preview["plays"] == 1 and preview["countries"][0]["code"] == "KP"


def test_preview_counts_what_the_list_would_have_caught(client):
    seed(client)
    assert client.get("/api/geoblocks/preview").json()["plays"] == 0  # nothing listed yet
    client.post("/api/geoblocks", json={"code": "US", "mode": "stop"})
    preview = client.get("/api/geoblocks/preview").json()
    assert preview["plays"] == 2 and preview["users"] == 2
    assert preview["countries"][0]["name"] == "United States"


def test_the_list_starts_recording_only_and_can_be_removed(client):
    seed(client)
    listing = client.post("/api/geoblocks", json={"code": "KP", "mode": "stop"}).json()
    # Follows the global dry run, which is on by default: nothing is stopped
    # until someone decides it should be.
    assert listing["record_only"] is True
    assert client.put("/api/geoblocks/settings", json={"record_only": False}).json()["record_only"] is False

    assert client.delete("/api/geoblocks/kp").json()["blocked"] is False
    assert client.get("/api/geoblocks").json()["items"] == []
    assert client.delete("/api/geoblocks/kp").status_code == 404


def test_viewers_cannot_see_or_change_the_list(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "all")
    assert client.get("/api/geoblocks").status_code == 403
    assert client.post("/api/geoblocks", json={"code": "KP"}).status_code == 403
    assert client.delete("/api/geoblocks/KP").status_code == 403


def test_a_country_can_act_differently_over_a_vpn(client):
    """An address in a country says where somebody is. A VPN exit there says
    where their provider is, which is a weaker claim and can be treated as one."""
    import json

    from app.services import enforcer

    seed(client)
    listing = client.post("/api/geoblocks", json={"code": "KP", "mode": "stop", "vpn_mode": "flag"}).json()
    assert listing["items"][0]["vpn_mode"] == "flag"

    rules = enforcer.country_rules()
    by_action = {}
    for rule in rules:
        items = json.loads(rule.conditions)["items"]
        vpn = next((i["value"] for i in items if i["field"] == "vpn"), None)
        by_action[rule.action] = vpn
    # Stopped when it is not a VPN, recorded when it is.
    assert by_action == {"terminate": False, "log_only": True}
    assert len({r.id for r in rules}) == 2


def test_a_vpn_can_be_left_alone_entirely(client):
    import json

    from app.services import enforcer

    seed(client)
    client.post("/api/geoblocks", json={"code": "KP", "mode": "stop", "vpn_mode": "ignore"})
    rules = enforcer.country_rules()
    assert len(rules) == 1 and rules[0].action == "terminate"
    items = json.loads(rules[0].conditions)["items"]
    assert {"type": "condition", "field": "vpn", "op": "is", "value": False} in items


def test_without_a_vpn_answer_the_rule_does_not_ask(client):
    import json

    from app.services import enforcer

    seed(client)
    client.post("/api/geoblocks", json={"code": "KP", "mode": "warn"})
    rules = enforcer.country_rules()
    assert len(rules) == 1
    assert [i["field"] for i in json.loads(rules[0].conditions)["items"]] == ["country"]

    assert client.post("/api/geoblocks", json={"code": "KP", "mode": "warn", "vpn_mode": "sideways"}).status_code == 400

from datetime import UTC, datetime, timedelta

from tests.test_auth import claim


def test_a_timed_ban_applies_then_ends_with_a_log_entry(client):
    from app.db import session_scope
    from app.models import BannedDevice
    from app.services import enforcer

    claim(client)
    assert client.post("/api/bans", json={"machine_id": "dev-1", "reason": "cool off", "hours": 24}).status_code == 200
    ban = client.get("/api/bans").json()[0]
    assert ban["expires_at"] is not None
    assert enforcer.ban_rule() is not None

    with session_scope() as db:
        db.get(BannedDevice, "dev-1").expires_at = datetime.now(UTC) - timedelta(minutes=1)
    assert enforcer.ban_rule() is None  # ignored as soon as it is over
    assert enforcer.expire_bans() == 1
    assert client.get("/api/bans").json() == []
    summaries = [e["summary"] for e in client.get("/api/log?kind=changes").json()]
    assert any("for 1 day: cool off" in s for s in summaries)
    assert any(s.startswith("Ban on") and s.endswith("ended") for s in summaries)
    assert client.post("/api/bans", json={"machine_id": "dev-3", "hours": 99999}).status_code == 400


def test_earlier_matches_ignore_the_stream_being_checked(client):
    from app.db import session_scope
    from app.models import EnforcementLog
    from app.services import enforcer

    with session_scope() as db:
        db.add(EnforcementLog(user_id=7, machine_id="tv", session_key="old", rule_name="Warn", acted_at=datetime.now(UTC) - timedelta(hours=2)))
        db.add(EnforcementLog(user_id=7, machine_id="tv", session_key="now", rule_name="Warn", acted_at=datetime.now(UTC)))
    count = enforcer.window_counter()
    current = {"session_key": "now", "user_id": 7, "machine_id": "tv"}
    assert count("user_matches_window", current, 24) == 1
    assert count("device_matches_window", current, 24) == 1
    assert count("user_matches_window", {**current, "session_key": "other"}, 24) == 2
    assert count("user_matches_window", current, 1) == 0


def test_new_places_need_history():
    from app.services.enforcer import _newness

    known = {"countries": {"US"}, "cities": {("Springfield", "US")}, "networks": {"Home ISP"}}
    here = {"country_code": "US", "city": "Springfield", "asn_org": "Home ISP"}
    abroad = {"country_code": "FR", "city": "Paris", "asn_org": "Cloud VPN"}
    assert _newness(here, known, 50) == {"new_country": False, "new_city": False, "new_network": False}
    assert _newness(abroad, known, 50) == {"new_country": True, "new_city": True, "new_network": True}
    assert _newness(abroad, known, 3) == {"new_country": False, "new_city": False, "new_network": False}
    assert _newness(None, known, 50)["new_country"] is False


def test_viewer_message_address_cannot_be_bent():
    from app.actions.registry import viewer_address

    template = "mailtos://me:pw@smtp.example.com?to={email}"
    assert viewer_address(template, "pat@example.com", "pat") == "mailtos://me:pw@smtp.example.com?to=pat@example.com"
    # An address with URL syntax in it stays one value.
    sneaky = viewer_address(template, "x@example.com&bcc=evil@example.com", None)
    assert "&bcc=" not in sneaky and "%26bcc%3Devil" in sneaky
    try:
        viewer_address(template, None, "pat")
    except RuntimeError:
        pass
    else:
        raise AssertionError("no email should refuse")


def test_message_viewer_is_refused_until_configured(client):
    from app.actions import registry

    action = registry.get("message_viewer")
    assert action is not None and registry.unmet(action) == ["viewer_messaging"]


def test_urls_with_credentials_are_masked_and_not_logged(client):
    claim(client)
    secret = "discord://1234/very-secret-token"
    assert client.put("/api/settings", json={"apprise_urls": secret}).status_code == 200
    shown = {s["key"]: s["value"] for s in client.get("/api/settings").json()}
    assert "very-secret-token" not in shown["apprise_urls"] and "****" in shown["apprise_urls"]
    log = client.get("/api/log?kind=changes").json()
    assert all("very-secret-token" not in str(entry) for entry in log)

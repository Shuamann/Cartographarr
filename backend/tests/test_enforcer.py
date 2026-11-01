from app.models import Rule
from app.services.enforcer import matches

SESSION = {
    "session_key": "42",
    "user_id": 123,
    "username": "someone",
    "machine_id": "00000000-1111-2222-3333-444444444444",
    "player": "Apple TV",
    "platform": "tvOS",
    "product": "Plex for Apple TV",
    "ip_address": "203.0.113.9",  # RFC 5737 documentation range
    "transcode_decision": "direct play",
    "video_full_resolution": "1080p",
    "location": "wan",
    "state": "playing",
}
CONTEXT = {"user_stream_count": 1, "is_hosting": False, "paused_minutes": None}


def rule(**kwargs) -> Rule:
    return Rule(name="r", action="terminate", **kwargs)


def test_rule_with_no_conditions_matches_nothing():
    # The single most important case here. An empty rule that matched
    # everything would take the whole server down on save.
    assert matches(rule(), SESSION, CONTEXT) is False


def test_machine_id_match():
    assert matches(rule(match_machine_id=SESSION["machine_id"]), SESSION, CONTEXT) is True
    assert matches(rule(match_machine_id="someone-else"), SESSION, CONTEXT) is False


def test_machine_id_survives_a_player_rename():
    # Why rules key on machine_id: the viewer can rename the player freely.
    renamed = {**SESSION, "player": "Totally Different Name"}
    assert matches(rule(match_machine_id=SESSION["machine_id"]), renamed, CONTEXT) is True
    assert matches(rule(match_player="Apple TV"), renamed, CONTEXT) is False


def test_matchers_are_anded_not_ored():
    both_right = rule(match_machine_id=SESSION["machine_id"], match_platform="tvOS")
    one_wrong = rule(match_machine_id=SESSION["machine_id"], match_platform="Roku")
    assert matches(both_right, SESSION, CONTEXT) is True
    assert matches(one_wrong, SESSION, CONTEXT) is False


def test_case_and_whitespace_insensitive():
    assert matches(rule(match_platform="  TVOS "), SESSION, CONTEXT) is True


def test_transcode_and_resolution():
    transcoding = {**SESSION, "transcode_decision": "transcode"}
    assert matches(rule(match_transcode_decision="transcode"), transcoding, CONTEXT) is True
    assert matches(rule(match_transcode_decision="transcode"), SESSION, CONTEXT) is False
    assert matches(rule(match_video_resolution="1080p"), SESSION, CONTEXT) is True
    assert matches(rule(match_video_resolution="4k"), SESSION, CONTEXT) is False


def test_ip_cidr_and_bare_address():
    assert matches(rule(match_ip_cidr="203.0.113.0/24"), SESSION, CONTEXT) is True
    assert matches(rule(match_ip_cidr="10.0.0.0/8"), SESSION, CONTEXT) is False
    # A bare address is a valid /32, so "this one IP" needs no special case.
    assert matches(rule(match_ip_cidr="203.0.113.9"), SESSION, CONTEXT) is True


def test_malformed_cidr_does_not_match_rather_than_crashing():
    assert matches(rule(match_ip_cidr="not-a-network"), SESSION, CONTEXT) is False


def test_concurrent_streams_is_strictly_greater_than():
    busy = {"user_stream_count": 3, "is_hosting": False, "paused_minutes": None}
    assert matches(rule(match_concurrent_streams_gt=2), SESSION, busy) is True
    # Exactly at the limit is allowed, so "more than 3" must not fire on the 3rd.
    at_limit = {"user_stream_count": 3, "is_hosting": False, "paused_minutes": None}
    assert matches(rule(match_concurrent_streams_gt=3), SESSION, at_limit) is False


def test_hosting_flag_matches_both_directions():
    vpn = {**CONTEXT, "is_hosting": True}
    assert matches(rule(match_is_hosting=True), SESSION, vpn) is True
    assert matches(rule(match_is_hosting=True), SESSION, CONTEXT) is False
    assert matches(rule(match_is_hosting=False), SESSION, CONTEXT) is True


def test_paused_minutes_ignores_playing_sessions():
    paused = {**CONTEXT, "paused_minutes": 45.0}
    assert matches(rule(match_paused_minutes_gt=30), SESSION, paused) is True
    # None means "not paused" and must never satisfy a paused-longer-than rule.
    assert matches(rule(match_paused_minutes_gt=30), SESSION, CONTEXT) is False


def test_missing_session_field_does_not_match():
    # Tautulli omits fields on some session types (live TV, for one).
    sparse = {"session_key": "1"}
    assert matches(rule(match_machine_id="anything"), sparse, CONTEXT) is False
    assert matches(rule(match_player="anything"), sparse, CONTEXT) is False


def test_a_rule_can_act_on_who_is_filling_the_upload(client):
    from app.services import enforcer, streams
    from tests.test_auth import claim

    claim(client)
    client.put("/api/settings", json={"upload_capacity_mbps": 100})

    sessions = [
        {"session_key": "1", "user_id": 7, "bandwidth": "30000", "location": "wan", "ip_address": "203.0.113.1"},
        {"session_key": "2", "user_id": 7, "bandwidth": "25000", "location": "wan", "ip_address": "203.0.113.1"},
        {"session_key": "3", "user_id": 8, "bandwidth": "10000", "location": "wan", "ip_address": "203.0.113.2"},
        {"session_key": "4", "user_id": 9, "bandwidth": "5000", "location": "lan", "ip_address": "10.0.0.5"},
    ]
    context = enforcer._build_context(sessions)

    hog = context["1"]
    assert hog["user_upload_mbps"] == 55.0 and hog["user_upload_percent"] == 55
    assert context["3"]["user_upload_percent"] == 10
    # Everything remote added up, so a rule can wait until the pipe is full.
    assert hog["server_upload_percent"] == 65
    assert streams.upload_capacity()[0] == 100

from datetime import datetime

import pytest

from app.services import conditions as c

SESSION = {
    "session_key": "1",
    "user_id": 7,
    "platform": "Roku",
    "location": "wan",
    "ip_address": "203.0.113.9",  # RFC 5737
    "transcode_decision": "transcode",
    "video_full_resolution": "4k",
}
CTX = {"geo": {"country_code": "US", "is_hosting": False}, "user_stream_count": 2, "now": datetime(2026, 1, 5, 23, 30)}


def cond(field, op, value):
    return {"type": "condition", "field": field, "op": op, "value": value}


def group(op, *items, negate=False):
    return {"type": "group", "op": op, "negate": negate, "items": list(items)}


def test_empty_tree_matches_nothing():
    assert c.evaluate(group("and"), SESSION, CTX) is False
    assert c.evaluate(group("or", group("and")), SESSION, CTX) is False


def test_and_inside_or():
    remote_4k = group("and", cond("location", "any", ["wan"]), cond("resolution", "any", ["4k"]))
    tree = group("or", cond("platform", "any", ["iOS"]), remote_4k)
    assert c.evaluate(tree, SESSION, CTX) is True
    assert c.evaluate(tree, {**SESSION, "location": "lan"}, CTX) is False


def test_negated_group():
    tree = group("and", cond("platform", "any", ["Roku"]), group("or", cond("country", "any", ["US"]), negate=True))
    assert c.evaluate(tree, SESSION, CTX) is False
    assert c.evaluate(tree, SESSION, {**CTX, "geo": {"country_code": "DE"}}) is True


def test_none_of_an_unknown_value_does_not_match():
    # No location known is not evidence of being outside the US.
    tree = group("and", cond("country", "none", ["US"]))
    assert c.evaluate(tree, SESSION, {**CTX, "geo": None}) is False


def test_time_window_across_midnight():
    tree = group("and", cond("time", "between", ["23:00", "06:00"]))
    assert c.evaluate(tree, SESSION, CTX) is True
    assert c.evaluate(tree, SESSION, {**CTX, "now": datetime(2026, 1, 5, 12, 0)}) is False


def test_numbers_and_cidr_lists():
    assert c.evaluate(group("and", cond("user_streams", "gt", 1)), SESSION, CTX) is True
    tree = group("and", cond("ip", "not_in", "10.0.0.0/8, 192.168.0.0/16"))
    assert c.evaluate(tree, SESSION, CTX) is True


def test_validation_refuses_what_it_cannot_evaluate():
    with pytest.raises(ValueError):
        c.validate(group("and", cond("nope", "any", ["x"])))
    with pytest.raises(ValueError):
        c.validate(group("and", cond("platform", "any", [])))
    with pytest.raises(ValueError):
        c.validate(group("and", cond("ip", "in", "not-a-range")))
    with pytest.raises(ValueError):
        c.validate(group("and", cond("time", "between", ["23:00"])))


def test_rule_api_refuses_an_empty_rule(client):
    from tests.test_auth import claim

    claim(client)
    empty = client.post("/api/rules", json={"name": "x", "conditions": group("and"), "actions": [{"name": "log_only"}]})
    assert empty.status_code == 400


def test_rule_api_saves_a_tree_and_reads_it_back(client):
    from tests.test_auth import claim

    claim(client)
    tree = group("and", cond("platform", "any", ["Roku"]), group("or", cond("location", "any", ["wan"])))
    saved = client.post("/api/rules", json={"name": "Remote Roku", "conditions": tree, "actions": [{"name": "log_only"}]})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["conditions"]["items"][1]["op"] == "or"
    assert body["actions"] == [{"name": "log_only", "params": {}}]

"""Timing streams across polls, and the conditions built on it.

A rule acting on "buffering for 20 seconds" stops or reports on a real
person's stream, so the counts must not drift: a stall is counted once, its
length comes from the polls, and it is saved when it ends.
"""

from app.services import conditions as c
from app.services import tracker


def s(state, key="1", user=7, machine="dev-1"):
    return {"session_key": key, "state": state, "user_id": user, "machine_id": machine, "full_title": "A Film"}


def test_buffering_is_timed_and_counted_across_polls(client):
    from app.db import session_scope
    from app.models import StreamEvent

    tracker.reset()
    tracker.observe([s("playing")], now=0)
    tracker.observe([s("buffering")], now=10)
    assert tracker.metrics("1", now=35)["buffering_seconds"] == 25
    tracker.observe([s("playing")], now=40)
    tracker.observe([s("buffering")], now=100)
    tracker.observe([s("buffering")], now=105)  # still the same stall
    m = tracker.metrics("1", now=110)
    assert m["buffer_count"] == 2
    assert m["buffer_total_seconds"] == 40  # 30 finished, plus 10 so far
    assert m["tracked_seconds"] == 110

    # The stream ends mid stall: that stall is closed and saved too.
    tracker.observe([], now=120)
    with session_scope() as db:
        events = db.query(StreamEvent).order_by(StreamEvent.id).all()
        assert [e.seconds for e in events] == [30, 5]
    assert tracker.metrics("1") == {}


def tree(field, op, value):
    return {"type": "group", "op": "and", "items": [{"type": "condition", "field": field, "op": op, "value": value}]}


def test_buffering_conditions_take_any_n():
    ctx = {"buffering_seconds": 25, "buffer_count": 3}
    assert c.evaluate(tree("buffering_seconds", "gt", 20), s("buffering"), ctx) is True
    assert c.evaluate(tree("buffering_seconds", "gt", 30), s("buffering"), ctx) is False
    assert c.evaluate(tree("buffer_count", "gte", 3), s("buffering"), ctx) is True
    # Not buffering at all is never "buffering for less than 30 seconds".
    assert c.evaluate(tree("buffering_seconds", "lt", 30), s("playing"), {"buffering_seconds": None}) is False


def test_window_conditions_count_over_the_hours_given():
    asked = []

    def counter(kind, session, hours):
        asked.append((kind, hours))
        return 4

    ctx = {"window_count": counter}
    assert c.evaluate(tree("user_devices_window", "gt", [3, 24]), s("playing"), ctx) is True
    assert c.evaluate(tree("user_devices_window", "gt", [4, 24]), s("playing"), ctx) is False
    assert asked[0] == ("user_devices_window", 24.0)
    # Without a counter (or an unknown user) it never matches.
    assert c.evaluate(tree("user_devices_window", "lt", [9, 24]), s("playing"), {}) is False


def test_window_values_are_validated():
    import pytest

    with pytest.raises(ValueError):
        c.validate(tree("user_plays_window", "gt", [3]))
    with pytest.raises(ValueError):
        c.validate(tree("user_plays_window", "gt", [3, 0]))
    c.validate(tree("user_plays_window", "gt", [3, 24]))


def test_real_window_counts_from_history_and_events(client):
    import time

    from app.db import session_scope
    from app.models import History, StreamEvent
    from app.services import enforcer
    from datetime import UTC, datetime

    now = int(time.time())
    with session_scope() as db:
        db.add(History(row_id=1, user_id=7, machine_id="a", ip_address="203.0.113.1", started=now - 3600))
        db.add(History(row_id=2, user_id=7, machine_id="b", ip_address="203.0.113.2", started=now - 7200))
        db.add(History(row_id=3, user_id=7, machine_id="c", ip_address="203.0.113.3", started=now - 5 * 86400))
        db.add(StreamEvent(kind="buffering", user_id=7, machine_id="a", started_at=datetime.now(UTC), seconds=4))
    count = enforcer.window_counter()
    assert count("user_devices_window", s("playing"), 24) == 2
    assert count("user_devices_window", s("playing"), 24 * 7) == 3
    assert count("user_buffering_window", s("playing"), 24) == 1
    assert count("device_buffering_window", s("playing", machine="a"), 24) == 1

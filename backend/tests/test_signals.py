"""Sharing signals: the detail view, and what Reviewed and Ignore each do.

Reviewed closes one signal. Ignore records that a person moving between two
places is expected, and closes matching signals past and future. The cases
that matter are that Ignore does not swallow anything else.
"""

from tests.test_auth import claim


def seed():
    from app.db import session_scope
    from app.models import History, IpLocation, TravelFlag, User

    with session_scope() as db:
        db.add(User(user_id=7, username="viewer7"))
        db.add(User(user_id=8, username="viewer8"))
        db.add(IpLocation(ip="203.0.113.1", city="Kansas City", lat=39.1, lon=-94.6, is_hosting=False))
        db.add(IpLocation(ip="203.0.113.2", city="Miami", lat=25.8, lon=-80.2, is_hosting=False))
        db.add(IpLocation(ip="203.0.113.3", city="Denver", lat=39.7, lon=-105.0, is_hosting=False))
        plays = [
            (1, 7, "203.0.113.1", 1000, 2000, "A Film"),
            (2, 7, "203.0.113.2", 2050, 3000, "A Show - Pilot"),
            (3, 7, "203.0.113.2", 5000, 6000, "Another"),
            (4, 7, "203.0.113.1", 6050, 7000, "Another 2"),
            (5, 7, "203.0.113.3", 7050, 8000, "Elsewhere"),
            (6, 8, "203.0.113.1", 1000, 2000, "Theirs"),
            (7, 8, "203.0.113.2", 2050, 3000, "Theirs 2"),
        ]
        for row, user, ip, start, stop, title in plays:
            db.add(History(row_id=row, user_id=user, ip_address=ip, started=start, stopped=stop, full_title=title))

        def flag(fid, user, a, b, a_ip, b_ip, a_city, b_city):
            db.add(TravelFlag(id=fid, user_id=user, from_history_id=a, to_history_id=b, from_ip=a_ip, to_ip=b_ip,
                              from_city=a_city, to_city=b_city, kind="concurrent", km=2000, status="new"))

        flag(1, 7, 1, 2, "203.0.113.1", "203.0.113.2", "Kansas City", "Miami")
        flag(2, 7, 3, 4, "203.0.113.2", "203.0.113.1", "Miami", "Kansas City")  # same pair, reversed
        flag(3, 7, 4, 5, "203.0.113.1", "203.0.113.3", "Kansas City", "Denver")  # different pair
        flag(4, 8, 6, 7, "203.0.113.1", "203.0.113.2", "Kansas City", "Miami")  # same pair, other user


def statuses(client):
    return {f["id"]: f["status"] for f in client.get("/api/travel-flags").json()}


def test_detail_shows_both_plays_and_the_gap(client):
    claim(client)
    seed()
    d = client.get("/api/travel-flags/1").json()
    assert d["from"]["play"]["full_title"] == "A Film"
    assert d["to"]["place"]["city"] == "Miami"
    assert d["gap_seconds"] == 50
    assert d["similar"] == 1  # flag 2 is the same pair reversed


def test_reviewed_closes_only_that_signal(client):
    claim(client)
    seed()
    client.patch("/api/travel-flags/1", json={"status": "reviewed"})
    assert statuses(client) == {1: "reviewed", 2: "new", 3: "new", 4: "new"}


def test_ignore_closes_the_same_pattern_for_that_user_only_and_undo_reopens(client):
    claim(client)
    seed()
    result = client.patch("/api/travel-flags/1", json={"status": "ignored", "reason": "second home"}).json()
    assert result["closed_too"] == 1
    # The reversed pair closes; a different pair and another user do not.
    assert statuses(client) == {1: "ignored", 2: "ignored", 3: "new", 4: "new"}

    patterns = client.get("/api/signal-ignores").json()
    assert len(patterns) == 1 and patterns[0]["closed"] == 2 and patterns[0]["reason"] == "second home"

    client.delete(f"/api/signal-ignores/{patterns[0]['id']}")
    assert statuses(client) == {1: "new", 2: "new", 3: "new", 4: "new"}


def test_new_signals_matching_an_ignore_are_recorded_as_ignored(client):
    from app.db import session_scope
    from app.models import History
    from app.services import travel
    from app.settings_store import current

    claim(client)
    seed()
    client.patch("/api/travel-flags/1", json={"status": "ignored"})
    with session_scope() as db:
        db.add(History(row_id=20, user_id=7, ip_address="203.0.113.3", started=9000, stopped=9500, full_title="x"))
        db.add(History(row_id=21, user_id=7, ip_address="203.0.113.1", started=9550, stopped=9900, full_title="y"))
        db.add(History(row_id=22, user_id=7, ip_address="203.0.113.2", started=9950, stopped=10500, full_title="z"))
    travel.find_flags(current())
    found = {f["to_history_id"]: f["status"] for f in client.get("/api/travel-flags").json()}
    assert found[22] == "ignored"  # Kansas City to Miami, the ignored pair
    assert found[21] == "new"  # Denver to Kansas City, not ignored


def test_a_play_left_paused_is_not_two_places_at_once(client):
    """A phone paused in one city, and the TV used 115 km away hours later.

    The phone's session stays open for days, so measuring from when it closed
    made this look like one account in two places at once. What matters is
    when anyone was last watching it."""
    from app.db import session_scope
    from app.models import History, IpLocation, TravelFlag
    from app.services import travel
    from app.settings_store import current

    claim(client)
    with session_scope() as db:
        db.add(IpLocation(ip="203.0.113.10", city="Kansas City", lat=39.1, lon=-94.58, accuracy_radius=20, is_hosting=False))
        db.add(IpLocation(ip="203.0.113.11", city="Holton", lat=39.47, lon=-95.74, accuracy_radius=20, is_hosting=False))
        # 36 minutes watched, then left paused for two days.
        db.add(History(row_id=30, user_id=9, ip_address="203.0.113.10", started=100_000,
                       stopped=100_000 + 2 * 86400, play_duration=36 * 60, full_title="phone"))
        # Three hours later, on the TV at home.
        db.add(History(row_id=31, user_id=9, ip_address="203.0.113.11", started=100_000 + 3 * 3600,
                       stopped=100_000 + 4 * 3600, play_duration=3600, full_title="tv"))
    travel.find_flags(current())
    with session_scope() as db:
        assert db.query(TravelFlag).filter(TravelFlag.user_id == 9).count() == 0


def test_open_signals_that_no_longer_qualify_are_cleared_but_decisions_are_kept(client):
    from app.db import session_scope
    from app.models import TravelFlag
    from app.services import travel
    from app.settings_store import current

    claim(client)
    with session_scope() as db:
        # Neither pair has plays behind it any more, so neither qualifies.
        db.add(TravelFlag(id=50, user_id=1, from_history_id=900, to_history_id=901, status="new"))
        db.add(TravelFlag(id=51, user_id=1, from_history_id=902, to_history_id=903, status="reviewed"))
    travel.find_flags(current())
    with session_scope() as db:
        assert db.get(TravelFlag, 50) is None
        assert db.get(TravelFlag, 51) is not None

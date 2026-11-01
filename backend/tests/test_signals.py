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
    """A phone paused in one city, and the TV used 115 km away hours later."""
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


# ---- one viewing carried from one network or device to another ---------------

def places():
    """Two cities far enough apart that any jump between them is impossible."""
    from app.db import session_scope
    from app.models import IpLocation, User

    with session_scope() as db:
        db.add(User(user_id=11, username="wanderer"))
        db.add(IpLocation(ip="198.51.100.1", city="Topeka", lat=39.05, lon=-95.68,
                          accuracy_radius=20, is_hosting=False, is_private=False))
        db.add(IpLocation(ip="198.51.100.2", city="Chicago", lat=41.88, lon=-87.63,
                          accuracy_radius=20, is_hosting=False, is_private=False))


def flags_for(user_id=11):
    from app.db import session_scope
    from app.models import TravelFlag
    from app.services import travel
    from app.settings_store import current
    from sqlalchemy import select

    travel.find_flags(current())
    with session_scope() as db:
        return db.execute(select(TravelFlag).where(TravelFlag.user_id == user_id)).scalars().all()


def test_one_phone_changing_network_is_not_two_people(client):
    """A phone that leaves mobile data for the wifi at home is recorded against two addresses."""
    from app.db import session_scope
    from app.models import History

    claim(client)
    places()
    with session_scope() as db:
        db.add(History(row_id=100, user_id=11, machine_id="the-phone", rating_key=1, ip_address="198.51.100.1",
                       started=200_000, stopped=201_000, play_duration=1000, full_title="On the way"))
        db.add(History(row_id=101, user_id=11, machine_id="the-phone", rating_key=2, ip_address="198.51.100.2",
                       started=201_100, stopped=202_000, play_duration=900, full_title="Once home"))
    assert flags_for() == []


def test_the_same_thing_picked_up_on_another_device_is_not_two_people(client):
    """The phone on the way home, the television once there: one viewing."""
    from app.db import session_scope
    from app.models import History

    claim(client)
    places()
    with session_scope() as db:
        db.add(History(row_id=110, user_id=11, machine_id="the-phone", rating_key=55, ip_address="198.51.100.1",
                       started=300_000, stopped=301_800, play_duration=1800, full_title="A Film"))
        # Twelve minutes later, same film, different box, other side of the map.
        db.add(History(row_id=111, user_id=11, machine_id="the-telly", rating_key=55, ip_address="198.51.100.2",
                       started=303_300, stopped=307_000, play_duration=3700, full_title="A Film"))
    assert flags_for() == []


def test_two_people_watching_the_same_film_at_once_is_still_a_signal(client):
    """The excuse only covers a viewing continuing."""
    from app.db import session_scope
    from app.models import History

    claim(client)
    places()
    with session_scope() as db:
        db.add(History(row_id=120, user_id=11, machine_id="a-box", rating_key=77, ip_address="198.51.100.1",
                       started=400_000, stopped=407_200, play_duration=7200, full_title="A Film"))
        # Starts an hour into the first, not near the end of it.
        db.add(History(row_id=121, user_id=11, machine_id="another-box", rating_key=77, ip_address="198.51.100.2",
                       started=403_600, stopped=410_800, play_duration=7200, full_title="A Film"))
    found = flags_for()
    assert [f.kind for f in found] == ["concurrent"]


def test_a_different_title_elsewhere_is_still_a_signal(client):
    from app.db import session_scope
    from app.models import History

    claim(client)
    places()
    with session_scope() as db:
        db.add(History(row_id=130, user_id=11, machine_id="a-box", rating_key=1, ip_address="198.51.100.1",
                       started=500_000, stopped=503_600, play_duration=3600, full_title="One Thing"))
        db.add(History(row_id=131, user_id=11, machine_id="another-box", rating_key=2, ip_address="198.51.100.2",
                       started=503_700, stopped=507_000, play_duration=3300, full_title="Another Thing"))
    assert len(flags_for()) == 1


def test_a_network_that_keeps_moving_is_pointed_out(client):
    from app.db import session_scope
    from app.models import History, IpLocation, TravelFlag, User

    claim(client)
    now = 1_790_000_000
    with session_scope() as db:
        db.add(User(user_id=12, username="phone-user"))
        for n, (city, lat, lon) in enumerate([("Akron", 41.08, -81.52), ("Columbus", 39.96, -82.99),
                                              ("Dallas", 32.78, -96.8), ("Indianapolis", 39.77, -86.16)]):
            db.add(IpLocation(ip=f"198.51.100.2{n}", city=city, lat=lat, lon=lon, accuracy_radius=20,
                              is_hosting=False, is_private=False, asn_org="A Mobile Network"))
            db.add(History(row_id=200 + n, user_id=12, machine_id=f"box{n}", rating_key=n,
                           ip_address=f"198.51.100.2{n}", started=now - n * 4000, stopped=now - n * 4000 + 1200,
                           play_duration=1200, full_title=f"Thing {n}"))
        db.add(TravelFlag(id=80, user_id=12, kind="concurrent", from_history_id=200, to_history_id=201,
                          from_ip="198.51.100.20", to_ip="198.51.100.21", from_city="Akron", to_city="Columbus",
                          km=311, status="new"))

    detail = client.get("/api/travel-flags/80").json()
    roaming = detail["roaming"]
    assert "A Mobile Network" in roaming
    assert roaming["A Mobile Network"]["count"] == 4
    assert "Dallas" in roaming["A Mobile Network"]["cities"]


def test_a_network_that_stays_put_is_not_mentioned(client):
    from app.db import session_scope
    from app.models import History, IpLocation, TravelFlag, User

    claim(client)
    now = 1_790_000_000
    with session_scope() as db:
        db.add(User(user_id=13, username="settled"))
        db.add(IpLocation(ip="198.51.100.30", city="Topeka", lat=39.05, lon=-95.68, accuracy_radius=20,
                          is_hosting=False, is_private=False, asn_org="A Home Line"))
        db.add(IpLocation(ip="198.51.100.31", city="Chicago", lat=41.88, lon=-87.63, accuracy_radius=20,
                          is_hosting=False, is_private=False, asn_org="Another Line"))
        db.add(History(row_id=220, user_id=13, machine_id="a", rating_key=1, ip_address="198.51.100.30",
                       started=now, stopped=now + 1200, play_duration=1200, full_title="One"))
        db.add(History(row_id=221, user_id=13, machine_id="b", rating_key=2, ip_address="198.51.100.31",
                       started=now + 1300, stopped=now + 2500, play_duration=1200, full_title="Two"))
        db.add(TravelFlag(id=81, user_id=13, kind="concurrent", from_history_id=220, to_history_id=221,
                          from_ip="198.51.100.30", to_ip="198.51.100.31", from_city="Topeka", to_city="Chicago",
                          km=800, status="new"))

    assert client.get("/api/travel-flags/81").json()["roaming"] == {}

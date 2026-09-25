"""Which storage each file is on, worked out from the paths Plex reports."""

from datetime import UTC, datetime, timedelta

from tests.test_auth import claim

NOW = int(datetime.now(UTC).timestamp())


def seed():
    from app.db import session_scope
    from app.models import History, MediaItem, StreamEvent

    files = [
        (1, "/movies/Film (2020)/film.mkv", 20_000_000_000, 9000),
        (2, "/movies/Other (2021)/other.mkv", 10_000_000_000, 7000),
        (3, "/nas-movies/Third (2022)/third.mkv", 5_000_000_000, 5000),
        (4, "/nas-tv/Show/S01E01.mkv", 1_000_000_000, 3000),
        (5, None, 0, None),
    ]
    with session_scope() as db:
        for key, path, size, bitrate in files:
            db.add(MediaItem(rating_key=key, title=f"Item {key}", media_type="movie",
                             file_path=path, file_size=size, file_bitrate=bitrate))
        # Two plays from the array, one stalling; one clean play from the NAS.
        db.add(History(row_id=1, reference_id=1, rating_key=1, user_id=7, started=NOW - 3600,
                       media_type="movie", location="wan", transcode_decision="transcode"))
        db.add(History(row_id=2, reference_id=2, rating_key=2, user_id=7, started=NOW - 7200,
                       media_type="movie", location="lan", transcode_decision="direct play"))
        db.add(History(row_id=3, reference_id=3, rating_key=3, user_id=8, started=NOW - 7200,
                       media_type="movie", location="wan", transcode_decision="direct play"))
        db.add(StreamEvent(kind="buffering", user_id=7, rating_key=1, seconds=12, cause="file",
                           started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
                           ended_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)))


def test_each_mount_is_found_with_how_watching_from_it_goes(client):
    claim(client)
    seed()
    stores = {s["store"]: s for s in client.get("/api/library/stores?days=30").json()["stores"]}
    assert set(stores) == {"/movies", "/nas-movies", "/nas-tv"}

    array = stores["/movies"]
    assert array["files"] == 2 and array["size"] == 30_000_000_000 and array["average_bitrate"] == 8000
    assert array["plays"] == 2 and array["remote_plays"] == 1 and array["transcode_percent"] == 50
    assert array["stalls"] == 1 and array["stalls_per_100"] == 50.0

    nas = stores["/nas-movies"]
    assert nas["plays"] == 1 and nas["stalls_per_100"] == 0.0
    # A file with no path is not guessed at.
    assert "Not known" not in stores


def test_two_mounts_with_one_name_are_one_store(client):
    claim(client)
    seed()
    for root in ("/nas-movies", "/nas-tv"):
        assert client.put(f"/api/library/stores{root}", json={"label": "SSD NAS"}).status_code == 200
    stores = {s["store"]: s for s in client.get("/api/library/stores").json()["stores"]}
    assert set(stores) == {"/movies", "SSD NAS"}
    assert stores["SSD NAS"]["files"] == 2 and stores["SSD NAS"]["roots"] == ["/nas-movies", "/nas-tv"]

    assert client.put("/api/library/stores/nowhere", json={"label": "x"}).status_code == 404
    actions = [e["action"] for e in client.get("/api/log?kind=changes").json()]
    assert "library.store" in actions


def test_a_deeper_mount_can_be_used_where_libraries_share_one(client):
    from app.db import session_scope
    from app.models import MediaItem

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=9, title="Deep", media_type="movie",
                         file_path="/mnt/user/movies/Film/film.mkv", file_size=1, file_bitrate=100))
    assert [s["store"] for s in client.get("/api/library/stores").json()["stores"]] == ["/mnt"]
    client.put("/api/settings", json={"library_store_depth": 3})
    assert [s["store"] for s in client.get("/api/library/stores").json()["stores"]] == ["/mnt/user/movies"]


def test_the_file_card_says_where_the_file_lives(client):
    claim(client)
    seed()
    client.put("/api/library/stores/movies", json={"label": "Array"})
    assert client.get("/api/library/file/1").json()["store"] == "Array"
    assert client.get("/api/library/file/3").json()["store"] == "/nas-movies"


def test_viewers_cannot_see_storage(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "all")
    assert client.get("/api/library/stores").status_code == 403
    assert client.put("/api/library/stores/movies", json={"label": "x"}).status_code == 403


def seed_weeks():
    """Two weeks of watching from one mount: a quiet one, then a bad one where
    a single stream rebuffered all evening."""
    from app.db import session_scope
    from app.models import History, MediaItem, StreamEvent

    now = datetime.now(UTC)
    last_week = now - timedelta(days=7)
    with session_scope() as db:
        db.add(MediaItem(rating_key=1, title="Film", media_type="movie",
                         file_path="/movies/Film (2020)/film.mkv", file_size=1, file_bitrate=9000))
        row = 0
        for when in (last_week, now):
            for _ in range(12):
                row += 1
                db.add(History(row_id=row, reference_id=row, rating_key=1, user_id=7,
                               started=int(when.timestamp()) - row * 60, media_type="movie"))
        # Last week: one stream that stalled once. This week: one stream that
        # stalled six times, which is still one stream that went badly.
        db.add(StreamEvent(kind="buffering", user_id=7, rating_key=1, session_key="a", seconds=9,
                           started_at=last_week.replace(tzinfo=None), ended_at=last_week.replace(tzinfo=None)))
        for _ in range(6):
            db.add(StreamEvent(kind="buffering", user_id=7, rating_key=1, session_key="b", seconds=9,
                               started_at=now.replace(tzinfo=None) - timedelta(minutes=30),
                               ended_at=now.replace(tzinfo=None) - timedelta(minutes=30)))


def test_a_store_is_judged_by_the_streams_that_went_badly_not_the_stalls(client):
    claim(client)
    seed_weeks()
    answer = client.get("/api/library/stores/trend?weeks=8").json()
    store = next(s for s in answer["stores"] if s["store"] == "/movies")
    counted = [p for p in store["points"] if p["stalled_percent"] is not None]
    assert len(counted) == 2, counted
    # Six rebuffers in one stream is one stream out of twelve plays, not six.
    assert counted[-1]["stalls"] == 6 and counted[-1]["stalled_streams"] == 1
    assert counted[-1]["stalled_percent"] == round(1 / 12 * 100, 1)
    assert counted[-1]["partial"] is True
    assert counted[0]["stalled_percent"] == round(1 / 12 * 100, 1)


def test_weeks_from_before_anything_was_counted_are_a_gap_not_a_good_week(client):
    claim(client)
    seed_weeks()
    answer = client.get("/api/library/stores/trend?weeks=8").json()
    store = next(s for s in answer["stores"] if s["store"] == "/movies")
    early = store["points"][0]
    assert early["stalled_percent"] is None and early["stalls"] is None
    assert answer["recording_from"] is not None


def test_which_way_a_store_is_heading():
    from app.services.stores import _direction

    assert _direction([1.0, 1.2]) is None  # not enough weeks to say anything
    assert _direction([1.0, 1.1, 1.0, 1.2]) == "steady"
    assert _direction([1.0, 1.2, 4.0, 6.0]) == "worse"
    assert _direction([6.0, 4.0, 1.2, 1.0]) == "better"
    # A store where almost nothing ever goes wrong is steady, not swinging
    # wildly between nought and a tenth of a percent.
    assert _direction([0.0, 0.1, 0.0, 0.3]) == "steady"


def test_viewers_cannot_see_the_trend(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "all")
    assert client.get("/api/library/stores/trend").status_code == 403


def seed_trouble():
    """Stalls at one mount: nearly all of them one remote viewer, on one title."""
    from app.db import session_scope
    from app.models import History, MediaItem, StreamEvent

    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as db:
        db.add(MediaItem(rating_key=1, title="Big Film", media_type="movie",
                         file_path="/movies/Big Film (2026)/big.mkv", file_size=1, file_bitrate=20000))
        db.add(MediaItem(rating_key=2, title="Small Film", media_type="movie",
                         file_path="/movies/Small Film (2020)/small.mkv", file_size=1, file_bitrate=4000))
        for row in range(1, 13):
            db.add(History(row_id=row, reference_id=row, rating_key=1 if row % 2 else 2, user_id=7,
                           started=NOW - row * 600, media_type="movie"))
        for n in range(8):
            db.add(StreamEvent(kind="buffering", user_id=7, username="faraway", player="Their Roku",
                               platform="Roku", rating_key=1, full_title="Big Film", location="wan",
                               transcode_decision="direct play", cause="viewer", session_key=f"s{n // 4}",
                               seconds=6, started_at=now - timedelta(hours=n), ended_at=now - timedelta(hours=n)))
        for n in range(2):
            db.add(StreamEvent(kind="buffering", user_id=8, username="athome", player="Living room",
                               platform="Roku", rating_key=2, full_title="Small Film", location="lan",
                               transcode_decision="transcode", cause="one_off", session_key=f"h{n}",
                               seconds=4, started_at=now - timedelta(hours=n), ended_at=now - timedelta(hours=n)))


def test_a_stores_trouble_says_who_and_what_it_was(client):
    claim(client)
    seed_trouble()
    answer = client.get("/api/library/stores/trouble?store=/movies&days=30").json()
    assert answer["events"] == 10 and answer["streams"] == 4
    assert answer["remote"] == 8 and answer["local"] == 2 and answer["transcoded"] == 2
    assert answer["people"][0] == {"name": "faraway", "events": 8, "streams": 2}
    assert answer["devices"][0]["name"] == "Their Roku"
    assert answer["titles"][0]["name"] == "Big Film"
    # The point of the panel: say it is probably not the disk.
    notes = " ".join(answer["notes"])
    assert "outside the house" in notes and "rather than at this storage" in notes
    assert "faraway" in notes


def test_trouble_says_nothing_about_a_handful_of_stalls(client):
    from app.db import session_scope
    from app.models import MediaItem, StreamEvent

    claim(client)
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as db:
        db.add(MediaItem(rating_key=1, title="Film", media_type="movie", file_path="/movies/Film/f.mkv",
                         file_size=1, file_bitrate=9000))
        db.add(StreamEvent(kind="buffering", user_id=7, username="someone", rating_key=1, location="wan",
                           session_key="a", seconds=5, started_at=now, ended_at=now))
    answer = client.get("/api/library/stores/trouble?store=/movies&days=30").json()
    assert answer["events"] == 1
    assert answer["notes"] == []  # one bad stream is a night, not a pattern


def test_trouble_of_a_store_with_no_files_is_empty(client):
    claim(client)
    seed_trouble()
    answer = client.get("/api/library/stores/trouble?store=/nowhere&days=30").json()
    assert answer["events"] == 0 and answer["notes"] == []


def test_viewers_cannot_see_a_stores_trouble(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "all")
    assert client.get("/api/library/stores/trouble?store=/movies").status_code == 403

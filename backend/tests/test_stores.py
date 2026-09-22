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

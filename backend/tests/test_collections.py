"""A collection's health, added up from what the scan and the history keep."""

from datetime import UTC, datetime

from tests.test_auth import claim

NOW = int(datetime(2026, 10, 7, 21, 0).timestamp())
DAY = 86400


def seed():
    from app.db import session_scope
    from app.models import History, MediaItem, MediaTag

    seen = datetime.now(UTC)
    with session_scope() as db:
        # A film collection of two, one watched last month, one never.
        db.add(MediaItem(rating_key=1, title="Lamp One", media_type="movie", file_size=4_000, library_seen_at=seen))
        db.add(MediaItem(rating_key=2, title="Lamp Two", media_type="movie", file_size=6_000, library_seen_at=seen))
        db.add(MediaTag(rating_key=1, kind="collection", value="Lighthouses"))
        db.add(MediaTag(rating_key=2, kind="collection", value="Lighthouses"))
        db.add(History(row_id=1, user_id=1, rating_key=1, started=NOW - 30 * DAY, media_type="movie"))
        # A show in a collection: its files are its episodes.
        db.add(MediaItem(rating_key=500, title="Quiet Harbour", media_type="show", library_seen_at=seen))
        for key in (501, 502):
            db.add(MediaItem(rating_key=key, title=f"Part {key}", media_type="episode", parent_rating_key=50,
                             grandparent_rating_key=500, file_size=1_000, library_seen_at=seen))
        db.add(MediaTag(rating_key=500, kind="collection", value="Coastal"))
        db.add(History(row_id=2, user_id=1, rating_key=502, grandparent_rating_key=500,
                       started=NOW - 2 * DAY, media_type="episode"))
        # Watched, but too long ago to count.
        db.add(MediaItem(rating_key=3, title="Old Lamp", media_type="movie", file_size=1, library_seen_at=seen))
        db.add(MediaTag(rating_key=3, kind="collection", value="Old"))
        db.add(History(row_id=3, user_id=1, rating_key=3, started=NOW - 500 * DAY, media_type="movie"))


def health(monkeypatch=None):
    from app.db import session_scope
    from app.services import collections

    with session_scope() as db:
        return {c["name"]: c for c in collections.health(db, now=NOW)}


def test_a_collection_adds_up_its_films(client):
    claim(client)
    seed()
    c = health()["Lighthouses"]
    assert (c["titles"], c["files"], c["bytes"], c["watched"]) == (2, 2, 10_000, 1)
    assert c["last_play"] == NOW - 30 * DAY


def test_a_show_counts_its_episodes_as_its_files(client):
    claim(client)
    seed()
    c = health()["Coastal"]
    assert (c["titles"], c["files"], c["bytes"], c["watched"]) == (1, 2, 2_000, 1)


def test_a_title_last_played_long_ago_is_not_watched(client):
    claim(client)
    seed()
    assert health()["Old"]["watched"] == 0


def test_problem_files_are_counted_in_their_collection(client, monkeypatch):
    from app.services import library

    claim(client)
    seed()
    monkeypatch.setattr(library, "problem_files", lambda db, t, d, limit=100: [{"rating_key": 2}, {"rating_key": 501}])
    found = health()
    assert found["Lighthouses"]["problems"] == 1 and found["Coastal"]["problems"] == 1


def test_largest_first(client):
    claim(client)
    seed()
    names = [c["name"] for c in client.get("/api/library/collections").json()]
    assert names[0] == "Lighthouses"


def test_only_an_admin_reads_it(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "own")
    assert client.get("/api/library/collections").status_code == 403

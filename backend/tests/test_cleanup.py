"""Deletion review: what takes room without earning it, and what was kept."""

from datetime import UTC, datetime, timedelta

from tests.test_auth import claim

NOW = int(datetime.now(UTC).timestamp())
GB = 1024**3


def item(key, title, size_gb, **over):
    from app.models import MediaItem

    fields = {"file_bitrate": 9000, "file_path": f"/movies/{title}/f.mkv", **over}
    return MediaItem(rating_key=key, title=title, full_title=title, media_type="movie",
                     file_size=int(size_gb * GB), **fields)


def seed():
    from app.db import session_scope
    from app.models import History, StreamSession

    with session_scope() as db:
        db.add(item(1, "Never watched", 40))
        db.add(item(2, "Watched last week", 40))
        db.add(item(3, "Watched years ago", 60))
        db.add(item(4, "Small and unwatched", 2))
        db.add(item(5, "4K nobody sees in 4K", 70, video_resolution="4k"))
        db.add(History(row_id=1, reference_id=1, rating_key=2, user_id=7, started=NOW - 5 * 86400, media_type="movie"))
        db.add(History(row_id=2, reference_id=2, rating_key=3, user_id=7, started=NOW - 1200 * 86400, media_type="movie"))
        for n in range(3):
            db.add(History(row_id=10 + n, reference_id=10 + n, rating_key=5, user_id=7,
                           started=NOW - (n + 1) * 86400, media_type="movie"))
            db.add(StreamSession(rating_key=5, user_id=7, stream_video_resolution="1080p", platform="Roku",
                                 started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=n + 1)))


def test_the_review_says_what_stands_out_and_why(client):
    claim(client)
    seed()
    answer = client.get("/api/library/cleanup").json()
    rows = {r["title"]: r for r in answer["items"]}

    assert set(rows) == {"Never watched", "Watched years ago", "4K nobody sees in 4K"}
    assert rows["Never watched"]["reason"] == "never_played"
    assert "Nothing has ever played it" in rows["Never watched"]["why"]
    assert rows["Watched years ago"]["reason"] == "not_played_in_years"
    assert rows["4K nobody sees in 4K"]["reason"] == "never_seen_in_4k"
    assert "never reached a screen as 4K" in rows["4K nobody sees in 4K"]["why"]
    # Biggest first, and the saving adds up.
    assert [r["title"] for r in answer["items"]][0] == "4K nobody sees in 4K"
    assert answer["reclaimable"] == int((70 + 60 + 40) * GB)
    # Which storage it is on, for deciding what is actually short of room.
    assert rows["Never watched"]["store"] == "/movies"


def test_something_kept_stops_being_suggested(client):
    claim(client)
    seed()
    assert client.post("/api/library/cleanup/1/keep", json={"reason": "Keeping it for my dad"}).json()["kept"] is True

    answer = client.get("/api/library/cleanup").json()
    assert "Never watched" not in [r["title"] for r in answer["items"]] and answer["kept"] == 1
    kept = client.get("/api/library/cleanup/kept").json()
    assert kept[0]["title"] == "Never watched" and kept[0]["reason"] == "Keeping it for my dad"

    assert client.delete("/api/library/cleanup/1/keep").json()["kept"] is False
    assert "Never watched" in [r["title"] for r in client.get("/api/library/cleanup").json()["items"]]
    assert client.delete("/api/library/cleanup/1/keep").status_code == 404

    actions = [e["action"] for e in client.get("/api/log?kind=changes").json()]
    assert "library.keep" in actions and "library.keep_undone" in actions


def test_viewers_cannot_see_the_review(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "all")
    assert client.get("/api/library/cleanup").status_code == 403
    assert client.post("/api/library/cleanup/1/keep", json={"reason": "x"}).status_code == 403


def seed_attention():
    """One file that stalls, one that is awkward to play, one that is unused."""
    from datetime import timedelta

    from app.db import session_scope
    from app.models import History, MediaItem, StreamEvent

    with session_scope() as db:
        db.add(item(10, "Stalls for people", 12, file_bitrate=30000, file_checked_at=datetime.now(UTC),
                    video_resolution="1080p"))
        db.add(item(11, "Only TrueHD", 12, file_bitrate=9000, file_checked_at=datetime.now(UTC),
                    audio_tracks='[{"codec": "truehd", "channels": 8, "language": "eng"}]'))
        db.add(item(12, "Nobody watches", 45))
        for n, key in enumerate([10, 10, 11]):
            db.add(History(row_id=50 + n, reference_id=50 + n, rating_key=key, user_id=7 + n, started=NOW - 3600,
                           media_type="movie", location="wan", transcode_decision="transcode"))
        for n in range(2):
            db.add(StreamEvent(kind="buffering", user_id=7 + n, rating_key=10, seconds=10, cause="file",
                               started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=n + 1),
                               ended_at=datetime.now(UTC).replace(tzinfo=None)))


def test_one_list_asked_three_ways(client):
    claim(client)
    seed_attention()

    trouble = client.get("/api/library/attention?kind=trouble").json()
    assert [i["title"] for i in trouble["items"]] == ["Stalls for people"]
    assert "stalled 2 times for 2 people" in trouble["items"][0]["why"].lower()

    messy = client.get("/api/library/attention?kind=messy").json()
    assert "Only TrueHD" in [i["title"] for i in messy["items"]]
    assert "audio" in messy["items"][0]["why"].lower()

    room = client.get("/api/library/attention?kind=room").json()
    assert [i["title"] for i in room["items"]] == ["Nobody watches"]
    assert room["reclaimable"] > 0

    # Every row carries the same things, whichever question found it.
    for view in (trouble, messy, room):
        row = view["items"][0]
        assert {"rating_key", "title", "kind", "why", "store", "findings"} <= set(row)

    assert client.get("/api/library/attention?kind=sideways").status_code == 422


def test_keeping_a_file_takes_it_out_of_every_list(client):
    claim(client)
    seed_attention()
    assert client.post("/api/library/cleanup/10/keep", json={"reason": "It is fine"}).status_code == 200

    assert client.get("/api/library/attention?kind=trouble").json()["items"] == []
    assert client.get("/api/library/attention?kind=trouble").json()["kept"] == 1

"""Files that are large for what they are.

Bitrate alone cannot be compared across a 45 minute cartoon and a three hour
film, so the list is sorted on size per hour. These check the filters narrow
the way the page says they do, and that one press cannot tag the library.
"""

import json

from tests.test_auth import claim


def seed():
    from app.db import session_scope
    from app.models import Library, MediaItem

    hour = 3_600_000
    files = [
        # key, title, GB, hours, resolution, section, languages, type
        (1, "Enormous Cartoon", 20, 1.0, "1080p", 5, ["eng"], "movie"),
        (2, "Long Film", 24, 3.0, "1080p", 1, ["eng", "spa"], "movie"),
        (3, "Tidy Film", 4, 2.0, "1080p", 1, ["eng"], "movie"),
        (4, "Big 4K", 60, 4.0, "4k", 1, ["eng"], "movie"),
        (5, "Anime Episode", 6, 0.4, "1080p", 4, ["jpn"], "episode"),
    ]
    with session_scope() as db:
        db.add(Library(section_id=1, name="Movies", type="movie"))
        db.add(Library(section_id=4, name="Anime Series", type="show"))
        db.add(Library(section_id=5, name="Kids Movies", type="movie"))
        for key, title, gb, hours, resolution, section, languages, kind in files:
            db.add(MediaItem(
                rating_key=key, title=title, full_title=title, media_type=kind, section_id=section,
                file_path=f"/movies/{title}/{title}.mkv", file_size=int(gb * 1e9), duration=int(hours * hour),
                file_bitrate=int(gb * 1e9 * 8 / (hours * 3600) / 1000), video_resolution=resolution,
                file_checked_at=None,
                audio_tracks=json.dumps([{"codec": "eac3", "channels": 6, "language": lang} for lang in languages]),
            ))


def listed(client, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    answer = client.get(f"/api/library/big?{query}").json()
    return [row["title"] for row in answer["items"]], answer


def test_sorted_by_size_per_hour_not_by_size(client):
    claim(client)
    seed()
    titles, answer = listed(client, min_gb_per_hour=0)
    # The 4K film is three times the size, and still the better behaved of the
    # two: 15 GB an hour against the cartoon's 20 for a single hour.
    assert titles[0] == "Enormous Cartoon"
    assert answer["items"][0]["gb_per_hour"] == 20.0
    assert "Big 4K" in titles


def test_the_floor_is_per_hour(client):
    claim(client)
    seed()
    titles, _ = listed(client, min_gb_per_hour=10)
    assert set(titles) == {"Enormous Cartoon", "Anime Episode", "Big 4K"}
    assert "Long Film" not in titles  # 8 GB an hour, under the floor


def test_narrowed_by_resolution_library_language_and_kind(client):
    claim(client)
    seed()
    assert listed(client, min_gb_per_hour=0, resolution="4k")[0] == ["Big 4K"]
    assert listed(client, min_gb_per_hour=0, section_id=5)[0] == ["Enormous Cartoon"]
    assert listed(client, min_gb_per_hour=0, language="spa")[0] == ["Long Film"]
    assert listed(client, min_gb_per_hour=0, media_type="episode")[0] == ["Anime Episode"]


def test_the_filters_it_offers_come_from_what_is_there(client):
    claim(client)
    seed()
    _, answer = listed(client, min_gb_per_hour=0)
    assert sorted(answer["languages"]) == ["eng", "jpn", "spa"]
    assert "4k" in answer["resolutions"] and "1080p" in answer["resolutions"]
    assert {s["name"] for s in answer["sections"]} == {"Movies", "Anime Series", "Kids Movies"}


def test_a_file_with_no_length_cannot_be_judged(client):
    from app.db import session_scope
    from app.models import MediaItem

    claim(client)
    seed()
    with session_scope() as db:
        db.add(MediaItem(rating_key=9, title="Length Unknown", media_type="movie",
                         file_path="/movies/x/x.mkv", file_size=int(30e9), duration=None))
    titles, _ = listed(client, min_gb_per_hour=0)
    assert "Length Unknown" not in titles


def test_one_press_cannot_tag_the_whole_library(client):
    claim(client)
    seed()
    answer = client.post("/api/library/big/tag", json={"keys": list(range(1, 200))})
    assert answer.status_code == 400 and "at a time" in answer.json()["detail"]
    assert client.post("/api/library/big/tag", json={"keys": []}).status_code == 400


def test_viewers_cannot_browse_or_tag(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "all")
    assert client.get("/api/library/big").status_code == 403
    assert client.post("/api/library/big/tag", json={"keys": [1]}).status_code == 403


# ---- browsing the library ----------------------------------------------------

def test_browse_sorts_by_what_is_asked(client):
    claim(client)
    seed()
    def titles(sort):
        return [r["title"] for r in client.get(f"/api/library/browse?sort={sort}&media_type=&limit=50").json()["items"]]

    assert titles("per_hour")[0] == "Enormous Cartoon"
    assert titles("size")[0] == "Big 4K"
    assert titles("title")[0] == "Anime Episode"


def test_a_tile_carries_what_can_be_proved(client):
    from datetime import UTC, datetime, timedelta

    from app.db import session_scope
    from app.models import History, StreamEvent

    claim(client)
    seed()
    now = datetime.now(UTC)
    with session_scope() as db:
        # Watched remotely twice, transcoded both times, and it stalled once.
        for row in (1, 2):
            db.add(History(row_id=row, reference_id=row, rating_key=2, user_id=7, location="wan",
                           transcode_decision="transcode", started=int(now.timestamp()) - row * 600,
                           media_type="movie"))
        db.add(StreamEvent(kind="buffering", user_id=7, rating_key=2, session_key="s", seconds=9,
                           started_at=now.replace(tzinfo=None) - timedelta(hours=1),
                           ended_at=now.replace(tzinfo=None) - timedelta(hours=1)))

    tiles = {t["title"]: t for t in client.get("/api/library/browse?media_type=movie&limit=50").json()["items"]}
    watched = tiles["Long Film"]
    assert watched["stalls"] == 1 and watched["transcode_percent"] == 100
    assert "stalls" in watched["marks"] and "transcoded" in watched["marks"]
    assert "unwatched" not in watched["marks"]
    # Nothing has ever played the others.
    assert "unwatched" in tiles["Tidy Film"]["marks"]


def test_browse_can_be_narrowed_to_one_problem(client):
    claim(client)
    seed()
    answer = client.get("/api/library/browse?media_type=movie&problem=unwatched&limit=50").json()
    assert answer["total"] == 4 and all("unwatched" in t["marks"] for t in answer["items"])


def test_browse_searches_by_title(client):
    claim(client)
    seed()
    answer = client.get("/api/library/browse?media_type=&search=cartoon&limit=50").json()
    assert [t["title"] for t in answer["items"]] == ["Enormous Cartoon"]


def test_viewers_cannot_browse(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "all")
    assert client.get("/api/library/browse").status_code == 403

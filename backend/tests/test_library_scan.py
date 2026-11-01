import asyncio
from datetime import UTC, datetime

from tests.test_auth import claim


class FakeTautulli:
    def __init__(self, movies, shows):
        self.movies = movies
        self.shows = shows
        self.calls = []

    async def call(self, cmd, **params):
        self.calls.append((cmd, params))
        if cmd == "get_libraries":
            return [{"section_id": "1", "section_type": "movie"}, {"section_id": "2", "section_type": "show"},
                    {"section_id": "3", "section_type": "artist"}]
        if cmd == "get_library_media_info":
            if params.get("section_id") == 1:
                rows = self.movies
            elif params.get("section_id") == 2:
                rows = [{"media_type": "show", "rating_key": key, "title": title} for key, title in self.shows]
            elif params.get("rating_key") == 500:
                rows = [{"media_type": "season", "rating_key": 501}]
            elif params.get("rating_key") == 501:
                rows = [ep(70001, 1), ep(70002, 2)]
            else:
                rows = []
            start, length = params["start"], params["length"]
            return {"recordsFiltered": len(rows), "data": rows[start : start + length]}
        if cmd == "get_metadata":
            key = params["rating_key"]
            return {"title": f"T{key}", "media_type": "movie", "media_info": [{"parts": [{"file": "/m/x.mkv", "streams": [
                {"type": "2", "codec": "eac3", "channels": "6", "language_code": "eng"}]}]}]}
        raise AssertionError(cmd)


def movie(key, size=1000, resolution="1080"):
    return {"media_type": "movie", "rating_key": key, "title": f"Movie {key}", "year": "2001", "bitrate": "9000",
            "video_codec": "hevc", "video_resolution": resolution, "audio_codec": "eac3", "audio_channels": "6",
            "container": "mkv", "file_size": str(size), "section_id": "1"}


def ep(key, index):
    return {"media_type": "episode", "rating_key": key, "title": f"Ep {index}", "media_index": str(index),
            "parent_media_index": "1", "bitrate": "3000", "video_resolution": "720", "file_size": "500"}


def test_scan_lists_everything_and_details_follow(client):
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import library_scan

    claim(client)
    fake = FakeTautulli([movie(k) for k in range(1, 1204)] + [movie(9000, resolution="4k")], [(500, "A Show")])
    result = asyncio.run(library_scan.scan(fake))
    assert result["movies"] == 1204 and result["episodes"] == 2 and result["new"] == 1206
    # Movie pages were fetched 1000 at a time.
    assert sum(1 for c, p in fake.calls if c == "get_library_media_info" and p.get("section_id") == 1) == 2

    with session_scope() as db:
        e = db.get(MediaItem, 70002)
        assert (e.grandparent_title, e.parent_media_index, e.media_index, e.video_resolution) == ("A Show", 1, 2, "720p")
        assert e.grandparent_rating_key == 500 and e.file_checked_at is None
        assert db.get(MediaItem, 9000).video_resolution == "4k"

    overview = client.get("/api/library/overview").json()
    assert overview["titles"] == 1206 and overview["scanned_at"]
    assert any(i["title"] == "Movie 9000" for i in client.get("/api/library/four-k").json())

    first = asyncio.run(library_scan.read_details(fake, chunk=1000))
    assert first == {"read": 1000, "left": 206}
    assert asyncio.run(library_scan.read_details(fake, chunk=1000)) == {"read": 206, "left": 0}
    assert asyncio.run(library_scan.read_details(fake)) == {"read": 0, "left": 0}
    with session_scope() as db:
        m = db.get(MediaItem, 5)
        assert m.file_checked_at is not None and m.title == "T5"


def test_changed_files_are_read_again_and_removed_ones_drop_out(client):
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import library_scan

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=1, title="Movie 1", media_type="movie", file_size=1000, file_bitrate=9000,
                         file_checked_at=datetime.now(UTC), video_resolution="4k", audio_tracks='[{"codec": "aac"}]'))
        db.add(MediaItem(rating_key=2, title="Movie 2", media_type="movie", file_size=1000, file_bitrate=9000,
                         file_checked_at=datetime.now(UTC), video_resolution="4k"))
    # Movie 1 was replaced with a bigger file; Movie 2 is gone.
    fake = FakeTautulli([movie(1, size=2000, resolution="4k")], [])
    result = asyncio.run(library_scan.scan(fake))
    assert result["changed"] == 1 and result["new"] == 0

    with session_scope() as db:
        m = db.get(MediaItem, 1)
        assert m.file_checked_at is None and m.file_size == 2000
        assert m.audio_tracks == '[{"codec": "aac"}]'  # kept until read again
    titles = [i["title"] for i in client.get("/api/library/four-k").json()]
    assert titles == ["Movie 1"]
    assert client.get("/api/library/overview").json()["titles"] == 1


def test_scan_and_details_are_scheduled(scheduled_client):
    from app import tasks

    for key in ("library_scan", "file_details"):
        job = tasks.scheduler.get_job(key)
        assert job is not None and job.next_run_time is not None, key

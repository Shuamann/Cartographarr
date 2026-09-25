"""Library health.

Each list recommends work (re-encode, remux, delete a 4K copy, chase a
request), so what gets listed, and why, is tested case by case.
"""

import json
import time
from datetime import UTC, datetime, timedelta

from tests.test_auth import claim
from tests.test_privacy import as_viewer

NOW = int(time.time())


def item(key, title, **over):
    from app.models import MediaItem

    base = dict(rating_key=key, title=title, full_title=title, media_type="movie", file_checked_at=datetime.now(UTC),
                file_bitrate=8000, file_container="mkv", video_resolution="1080p", video_codec="h264",
                audio_tracks=json.dumps([{"codec": "eac3", "channels": 6, "language": "eng"}]),
                subtitle_tracks=json.dumps([{"codec": "srt", "language": "eng", "forced": False}]))
    base.update(over)
    return MediaItem(**base)


def play(row_id, key, user=1, location="wan", decision="direct play", days_ago=1):
    from app.models import History

    return History(row_id=row_id, rating_key=key, user_id=user, location=location, transcode_decision=decision,
                   started=NOW - days_ago * 86400, media_type="movie")


def seed():
    from app.db import session_scope
    from app.models import StreamEvent, StreamSession

    with session_scope() as db:
        db.add(item(1, "Remux", file_bitrate=60000, file_size=60_000_000_000))
        db.add(item(2, "Small", file_bitrate=4000))
        db.add(item(3, "Stalls", file_bitrate=6000))
        db.add(item(4, "Transcoded everywhere", file_bitrate=9000,
                    audio_tracks=json.dumps([{"codec": "truehd", "channels": 8, "language": "eng"}])))
        db.add(item(5, "Anime", subtitle_tracks=json.dumps(
            [{"codec": "ass", "language": "eng", "forced": False}] + [{"codec": "srt", "language": "eng", "forced": False}] * 6)))
        db.add(item(6, "Old", file_container="avi", audio_tracks=json.dumps([{"codec": "mp3", "channels": 2, "language": None}, {"codec": "aac", "channels": 2, "language": "eng"}])))
        db.add(item(10, "Big 4K", video_resolution="4k", file_size=80_000_000_000))
        db.add(item(11, "Loved 4K", video_resolution="4k", file_size=50_000_000_000))
        db.add(item(12, "Unwatched 4K", video_resolution="4k", file_size=70_000_000_000))
        rid = 100
        for key, location, decision in [(1, "wan", "direct play"), (2, "wan", "direct play"), (2, "lan", "direct play"),
                                        (4, "wan", "transcode"), (4, "wan", "transcode"), (4, "wan", "direct play"),
                                        (10, "wan", "transcode"), (10, "wan", "transcode"), (11, "lan", "direct play"),
                                        (5, "lan", "direct play")]:
            rid += 1
            db.add(play(rid, key, location=location, decision=decision))
        db.add(StreamEvent(kind="buffering", user_id=2, rating_key=3, started_at=datetime.now(UTC) - timedelta(days=2),
                           ended_at=datetime.now(UTC) - timedelta(days=2), seconds=12, cause="file"))
        db.add(StreamSession(rating_key=4, primary_cause="audio_codec", causes="audio_codec", platform="Roku",
                             player="The bedroom stick",
                             started_at=datetime.now(UTC) - timedelta(days=1), transcode_decision="transcode"))
        db.add(StreamSession(rating_key=11, stream_video_resolution="4k", started_at=datetime.now(UTC) - timedelta(days=1)))


def test_problem_files(client):
    claim(client)
    seed()
    rows = {r["title"]: r for r in client.get("/api/library/problems?threshold_mbps=20").json()}
    assert set(rows) == {"Remux", "Stalls", "Transcoded everywhere", "Big 4K"}
    assert rows["Remux"]["reasons"] == ["over_threshold"]
    assert rows["Stalls"]["reasons"] == ["stalls"] and rows["Stalls"]["stalls"] == 1
    assert rows["Transcoded everywhere"]["reasons"] == ["mostly_transcoded"]
    assert rows["Transcoded everywhere"]["causes"] == ["audio_codec"]
    # A higher threshold drops the remux, nothing else changes.
    assert "Remux" not in {r["title"] for r in client.get("/api/library/problems?threshold_mbps=80").json()}


def test_messy_files(client):
    claim(client)
    seed()
    data = client.get("/api/library/messy").json()
    issues = {f["title"]: f["issues"] for f in data["files"]}
    assert issues["Transcoded everywhere"] == ["no_compatible_audio"]
    assert set(issues["Anime"]) == {"styled_subtitles", "subtitle_clutter"}
    assert set(issues["Old"]) == {"untagged_audio", "legacy_container"}
    assert "Small" not in issues
    only = client.get("/api/library/messy?issue=legacy_container").json()
    assert [f["title"] for f in only["files"]] == ["Old"]
    assert client.get("/api/library/messy?issue=nope").status_code == 400


def test_four_k_verdicts(client):
    claim(client)
    seed()
    verdicts = {r["title"]: r["verdict"] for r in client.get("/api/library/four-k").json()}
    assert verdicts == {"Big 4K": "mostly_downscaled", "Loved 4K": "benefits", "Unwatched 4K": "unwatched"}


def test_transcode_causes_and_file_detail(client):
    claim(client)
    seed()
    causes = client.get("/api/library/transcodes").json()
    assert causes["causes"][0]["cause"] == "audio_codec" and causes["causes"][0]["platforms"][0]["name"] == "Roku"
    # Which box, not just which kind of box: a platform cannot be taken out of
    # a cupboard and looked at.
    assert causes["causes"][0]["players"][0] == {"name": "The bedroom stick", "streams": 1}
    detail = client.get("/api/library/file/4").json()
    assert detail["plays"] == 3 and detail["transcodes"] == 2 and detail["transcode_causes"] == [{"cause": "audio_codec", "streams": 1}]
    assert client.get("/api/library/file/999").status_code == 404
    overview = client.get("/api/library/overview").json()
    assert overview["checked"] == 9 and overview["threshold_mbps"] == 20


def test_unwatched_requests(client, monkeypatch):
    from app.db import session_scope
    from app.integrations.seerr import seerr
    from app.models import User

    claim(client)
    seed()
    with session_scope() as db:
        db.add(User(user_id=1, username="alice", email="alice@example.com"))
        db.add(User(user_id=9, username="carol"))

    async def fake_requests(limit=2000):
        added = (datetime.now(UTC) - timedelta(days=40)).isoformat()
        return [
            # carol asked for Small and never watched it; alice watched it.
            {"is4k": False, "createdAt": added, "media": {"status": 5, "ratingKey": "2", "mediaType": "movie", "mediaAddedAt": added},
             "requestedBy": {"plexUsername": "carol"}},
            # alice asked for Remux and watched it: not listed.
            {"is4k": False, "media": {"status": 5, "ratingKey": "1", "mediaType": "movie"}, "requestedBy": {"email": "ALICE@example.com"}},
            # Still processing: not listed.
            {"is4k": False, "media": {"status": 3, "ratingKey": "6", "mediaType": "movie"}, "requestedBy": {"plexUsername": "carol"}},
        ]

    monkeypatch.setattr(type(seerr), "configured", lambda self: True)
    monkeypatch.setattr(seerr, "all_requests", fake_requests)
    data = client.get("/api/library/requests").json()
    assert data["configured"] is True
    assert [(r["title"], r["requested_by"], r["user_id"], r["watched_by_others"]) for r in data["requests"]] == [("Small", "carol", 9, 1)]
    assert data["requests"][0]["available_days"] in (39, 40)


def test_library_is_admin_only(client):
    as_viewer(client, "all")
    for path in ("overview", "problems", "transcodes", "messy", "four-k", "requests", "file/1"):
        assert client.get(f"/api/library/{path}").status_code == 403, path


def test_many_requests_do_not_freeze_the_app(client, monkeypatch):
    """Matching once ran two queries per request on the event loop, and a few
    thousand requests froze every page. Now bulk, in a thread, and cached."""
    import time as clock

    from app.integrations.seerr import seerr

    claim(client)
    seed()
    calls = {"n": 0}

    async def many(limit=2000):
        calls["n"] += 1
        return [
            {"is4k": False, "media": {"status": 5, "ratingKey": str(1000 + i), "mediaType": "movie"},
             "requestedBy": {"plexUsername": f"user{i % 40}"}}
            for i in range(2000)
        ]

    monkeypatch.setattr(type(seerr), "configured", lambda self: True)
    monkeypatch.setattr(seerr, "all_requests", many)
    started = clock.perf_counter()
    data = client.get("/api/library/requests?fresh=true").json()
    assert len(data["requests"]) == 2000
    assert clock.perf_counter() - started < 5
    client.get("/api/library/requests")
    assert calls["n"] == 1  # the second came from the cache


def test_playback_summary_for_a_user_and_a_device(client):
    from app.db import session_scope
    from app.models import StreamEvent, StreamSession

    claim(client)
    seed()
    with session_scope() as db:
        db.add(StreamSession(user_id=1, machine_id="tv", causes="subtitle_burn,audio_codec", transcode_hw=True,
                             started_at=datetime.now(UTC) - timedelta(days=1)))
        db.add(StreamEvent(kind="buffering", user_id=1, machine_id="tv", rating_key=4, full_title="Transcoded everywhere",
                           started_at=datetime.now(UTC) - timedelta(days=1), ended_at=datetime.now(UTC), seconds=30, cause="viewer"))
    user = client.get("/api/users/1/playback").json()
    assert user["plays"] == 10 and user["transcoded"] == 4
    assert [c["cause"] for c in user["transcode_causes"]] == ["subtitle_burn", "audio_codec"]
    assert user["stalls"] == 1 and user["stall_causes"][0]["label"] == "Viewer's device or connection"
    assert user["stalled_titles"][0]["title"] == "Transcoded everywhere"
    device = client.get("/api/devices/tv/playback").json()
    assert device["streams_recorded"] == 1 and device["hardware"] == 1


def test_health_summary(client):
    from app.db import session_scope
    from app.models import BandwidthSample, StreamEvent, StreamSession, User

    claim(client)
    seed()
    now = datetime.now(UTC)
    with session_scope() as db:
        db.add(User(user_id=1, username="alpha"))
        db.add(User(user_id=2, username="quiet"))
        db.add(StreamEvent(kind="buffering", user_id=1, started_at=now - timedelta(days=1), ended_at=now, seconds=5, cause="upload"))
        db.add(StreamEvent(kind="buffering", user_id=1, started_at=now - timedelta(days=2), ended_at=now, seconds=5, cause="upload"))
        db.add(StreamEvent(kind="buffering", user_id=1, started_at=now - timedelta(days=30), ended_at=now, seconds=5, cause="file"))
        db.add(BandwidthSample(minute=int(now.timestamp()) // 60 * 60 - 3600, wan_kbps=38500))
        db.add(StreamSession(transcode_decision="transcode", started_at=now - timedelta(days=1)))
    h = client.get("/api/library/health").json()
    # The shared seed has one stall of its own this week, caused by the file.
    assert h["stalls_week"] == 3 and h["top_stall_cause"] == "Server upload nearly full"
    assert h["peak_upload_mbps"] == 38.5 and h["streams_week"] == 3 and h["transcoded_week"] == 2
    assert h["not_watching"] == 1 and h["people"] == 2

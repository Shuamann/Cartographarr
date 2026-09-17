"""Reported issues: read from Seerr, landed on the right file, and shown with
the evidence this app already holds."""

import asyncio
from datetime import UTC, datetime, timedelta

from tests.test_auth import claim
from tests.test_privacy import as_viewer

NOW = int(datetime.now(UTC).timestamp())


def issue(seerr_id, *, kind=2, status=1, rating_key=500, media_type="tv", season=8, episode=23, message="Audio is out of sync"):
    return {
        "id": seerr_id,
        "issueType": kind,
        "status": status,
        "createdAt": "2026-09-16T10:00:00.000Z",
        "updatedAt": "2026-09-16T11:00:00.000Z",
        "media": {"mediaType": media_type, "tmdbId": 2316, "tvdbId": 73244, "ratingKey": str(rating_key)},
        "problemSeason": season,
        "problemEpisode": episode,
        "createdBy": {"displayName": "Watcher", "plexId": 7, "email": "someone@example.test"},
        "comments": [{"message": message, "user": {"displayName": "Watcher", "plexId": 7}, "createdAt": "2026-09-16T10:00:00.000Z"}],
    }


def seed_library():
    from app.db import session_scope
    from app.models import History, MediaItem, StreamEvent, User

    with session_scope() as db:
        db.add(User(user_id=7, username="watcher", friendly_name="Watcher"))
        db.add(MediaItem(rating_key=500, title="The Office (US)", media_type="show"))
        db.add(MediaItem(rating_key=880, title="Turf War", full_title="The Office (US) - Turf War", media_type="episode",
                         grandparent_rating_key=500, grandparent_title="The Office (US)", parent_media_index=8,
                         media_index=23, file_bitrate=9000, video_resolution="1080p", file_checked_at=datetime.now(UTC),
                         audio_tracks='[{"codec": "truehd", "channels": 8, "language": "eng"}]'))
        db.add(History(row_id=1, reference_id=1, rating_key=880, user_id=7, started=NOW - 7200, stopped=NOW - 4000,
                       media_type="episode", full_title="The Office (US) - Turf War", platform="iOS", player="iPhone",
                       location="wan", transcode_decision="transcode", percent_complete=96))
        db.add(History(row_id=2, reference_id=2, rating_key=880, user_id=9, started=NOW - 200000, stopped=NOW - 197000,
                       media_type="episode", full_title="The Office (US) - Turf War", platform="Roku", player="TV",
                       location="lan", transcode_decision="direct play", percent_complete=100))
        # A stall inside the reporter's play, and one from another day.
        db.add(StreamEvent(kind="buffering", user_id=7, rating_key=880, seconds=14, cause="bandwidth",
                           started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=6000),
                           ended_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=5980)))
        db.add(StreamEvent(kind="buffering", user_id=7, rating_key=880, seconds=9, cause="file",
                           started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=9),
                           ended_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=9)))


def fake_seerr(monkeypatch, listed, details=None):
    from app.services import issues as service

    async def fetch(limit=500):
        return listed

    async def detail(seerr_id):
        return (details or {}).get(seerr_id) or next(r for r in listed if r["id"] == seerr_id)

    monkeypatch.setattr(service, "fetch", fetch)
    monkeypatch.setattr(service, "detail", detail)


def test_an_episode_report_lands_on_the_episode_with_its_evidence(client, monkeypatch):
    from app.services import issues as service

    claim(client)
    seed_library()
    fake_seerr(monkeypatch, [issue(11)])
    assert asyncio.run(service.sync())["issues"] == 1

    listing = client.get("/api/issues").json()
    assert listing["open"] == 1 and listing["by_type"] == {"audio": 1}
    row = listing["items"][0]
    assert row["title"] == "The Office (US) - Turf War" and row["rating_key"] == 880
    assert row["reporter_name"] == "Watcher" and row["issue_type"] == "audio"
    assert row["message"] == "Audio is out of sync"

    detail = client.get(f"/api/issues/{row['id']}").json()
    assert detail["file"]["file_bitrate"] == 9000
    assert any(f["key"] == "no_compatible_audio" for f in detail["file"]["findings"])
    # The reporter's own play comes first, with the stall that happened during it.
    first = detail["plays"][0]
    assert first["mine"] and first["user_name"] == "Watcher" and first["transcode_decision"] == "transcode"
    assert first["stalls"] == 1 and first["stall_seconds"] == 14
    assert detail["plays"][1]["mine"] is False


def test_resolved_and_deleted_issues_and_filters(client, monkeypatch):
    from app.services import issues as service

    claim(client)
    seed_library()
    fake_seerr(monkeypatch, [issue(11), issue(12, kind=3, status=2, message="No subtitles")])
    asyncio.run(service.sync())
    assert client.get("/api/issues").json()["items"] and client.get("/api/issues").json()["resolved"] == 1
    assert [i["issue_type"] for i in client.get("/api/issues?status=all").json()["items"]] == ["subtitles", "audio"]  # newest first
    assert len(client.get("/api/issues?status=all&issue_type=subtitles").json()["items"]) == 1

    # Deleted in Seerr: gone here on the next sync.
    fake_seerr(monkeypatch, [issue(11)])
    asyncio.run(service.sync())
    assert len(client.get("/api/issues?status=all").json()["items"]) == 1


def test_a_movie_report_and_one_with_no_match(client, monkeypatch):
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import issues as service

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=40, title="Annabelle", full_title="Annabelle", media_type="movie", file_bitrate=4000))
    fake_seerr(monkeypatch, [
        issue(20, kind=1, rating_key=40, media_type="movie", season=None, episode=None, message="Picture stutters"),
        issue(21, kind=4, rating_key=999, media_type="movie", season=None, episode=None, message="Wrong film"),
    ])
    asyncio.run(service.sync())

    items = {i["seerr_id"]: i for i in client.get("/api/issues").json()["items"]}
    assert items[20]["title"] == "Annabelle" and items[20]["issue_type"] == "video"
    # A file this server does not have is still listed, with nothing attached.
    unmatched = client.get(f"/api/issues/{items[21]['id']}").json()
    assert unmatched["rating_key"] == 999 and unmatched["file"] is None and unmatched["plays"] == []


def test_viewers_cannot_see_issues(client):
    as_viewer(client, "all")
    assert client.get("/api/issues").status_code == 403
    assert client.get("/api/issues/1").status_code == 403


def test_the_sync_is_skipped_without_seerr(client):
    from app import tasks

    claim(client)
    asyncio.run(tasks.run("issues"))
    assert tasks.TASKS["issues"].last["status"] == "skipped"

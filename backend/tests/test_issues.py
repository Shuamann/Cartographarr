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


def test_an_issue_can_be_raised_here_without_seerr(client):
    from app.db import session_scope
    from app.models import MediaItem

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=880, title="Turf War", full_title="The Office (US) - Turf War",
                         media_type="episode", grandparent_rating_key=500, parent_media_index=8, media_index=23))

    assert client.post("/api/issues", json={"rating_key": 880, "issue_type": "audio", "message": ""}).status_code == 400
    assert client.post("/api/issues", json={"rating_key": 880, "issue_type": "smell", "message": "x"}).status_code == 400
    assert client.post("/api/issues", json={"rating_key": 4, "message": "gone"}).status_code == 404

    made = client.post("/api/issues", json={"rating_key": 880, "issue_type": "audio", "message": "Out of sync"}).json()
    row = client.get("/api/issues").json()["items"][0]
    assert row["id"] == made["id"] and row["source"] == "local" and row["seerr_id"] is None
    assert row["title"] == "The Office (US) - Turf War" and row["season"] == 8 and row["episode"] == 23

    assert client.post(f"/api/issues/{made['id']}/comment", json={"message": "Only on the Roku"}).json()["comments"] == 2
    assert client.post(f"/api/issues/{made['id']}/status", json={"status": "resolved"}).json()["status"] == "resolved"
    assert client.get("/api/issues").json()["open"] == 0
    detail = client.get(f"/api/issues/{made['id']}").json()
    assert [c["message"] for c in detail["comment_list"]] == ["Out of sync", "Only on the Roku"]

    actions = [e["action"] for e in client.get("/api/log?kind=changes").json()]
    assert {"issue.create", "issue.comment", "issue.status"} <= set(actions)


def test_an_issue_from_seerr_is_acted_on_here_without_seerr_configured(client, monkeypatch):
    """Seerr may have been turned off since a report came in. The decision
    still stands here, and nothing is posted to a service that is not there."""
    from app.services import issues as service

    claim(client)
    seed_library()
    fake_seerr(monkeypatch, [issue(11)])
    asyncio.run(service.sync())
    made = client.get("/api/issues").json()["items"][0]["id"]

    assert client.post(f"/api/issues/{made}/comment", json={"message": "hi"}).json()["warning"] is None
    assert client.post(f"/api/issues/{made}/status", json={"status": "resolved"}).json()["status"] == "resolved"


def test_a_local_issue_survives_a_seerr_sync(client, monkeypatch):
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import issues as service

    claim(client)
    seed_library()
    with session_scope() as db:
        db.add(MediaItem(rating_key=41, title="Annabelle", full_title="Annabelle", media_type="movie"))
    client.post("/api/issues", json={"rating_key": 41, "message": "Stutters"})
    fake_seerr(monkeypatch, [issue(11)])
    asyncio.run(service.sync())
    sources = sorted(i["source"] for i in client.get("/api/issues").json()["items"])
    assert sources == ["local", "seerr"]


def fake_seerr_writes(monkeypatch):
    """Catch what would be posted to Seerr, without posting anything."""
    from app.services import issues as service

    posted: list[tuple[str, dict]] = []

    async def post(path, body=None):
        posted.append((path, body or {}))

    monkeypatch.setattr(service, "_post", post)
    monkeypatch.setattr("app.integrations.seerr.SeerrIntegration.configured", lambda self: True)
    return posted


def test_a_comment_and_a_resolution_reach_seerr_with_who_said_it(client, monkeypatch):
    from app.services import issues as service

    claim(client)
    seed_library()
    fake_seerr(monkeypatch, [issue(11)])
    asyncio.run(service.sync())
    issue_id = client.get("/api/issues").json()["items"][0]["id"]
    posted = fake_seerr_writes(monkeypatch)

    assert client.post(f"/api/issues/{issue_id}/comment", json={"message": "Only on the Roku"}).json()["warning"] is None
    assert posted[0][0] == "/issue/11/comment"
    # The API key acts as the admin in Seerr, so the message says who it is from.
    assert posted[0][1]["message"].startswith("Only on the Roku") and "via Cartographarr" in posted[0][1]["message"]

    assert client.post(f"/api/issues/{issue_id}/status", json={"status": "resolved"}).json()["status"] == "resolved"
    assert posted[-1][0] == "/issue/11/resolved"
    assert client.get("/api/issues").json()["open"] == 0
    assert client.post(f"/api/issues/{issue_id}/status", json={"status": "open"}).status_code == 200
    assert posted[-1][0] == "/issue/11/open"


def test_a_local_issue_never_calls_seerr(client, monkeypatch):
    from app.db import session_scope
    from app.models import MediaItem

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=5, title="Film", full_title="Film", media_type="movie"))
    made = client.post("/api/issues", json={"rating_key": 5, "message": "Stutters"}).json()["id"]
    posted = fake_seerr_writes(monkeypatch)
    client.post(f"/api/issues/{made}/comment", json={"message": "Only at night"})
    client.post(f"/api/issues/{made}/status", json={"status": "resolved"})
    assert posted == []


def test_a_failing_seerr_still_records_the_decision_here(client, monkeypatch):
    from app.services import issues as service

    claim(client)
    seed_library()
    fake_seerr(monkeypatch, [issue(11)])
    asyncio.run(service.sync())
    issue_id = client.get("/api/issues").json()["items"][0]["id"]

    async def boom(path, body=None):
        raise RuntimeError("Seerr is down")

    monkeypatch.setattr(service, "_post", boom)
    monkeypatch.setattr("app.integrations.seerr.SeerrIntegration.configured", lambda self: True)
    answer = client.post(f"/api/issues/{issue_id}/status", json={"status": "resolved"}).json()
    assert answer["status"] == "resolved" and "Seerr was not updated" in answer["warning"]
    assert client.get("/api/issues").json()["open"] == 0


def test_a_replacement_landing_closes_what_was_reported(client, monkeypatch):
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import issues as service
    from app.services import replacements

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=5, title="Film", full_title="Film", media_type="movie", file_checked_at=datetime.now(UTC)))
    made = client.post("/api/issues", json={"rating_key": 5, "issue_type": "audio", "message": "No English track"}).json()["id"]

    class FakeService:
        label = "Radarr"

        async def current_file(self, arr_id, episode_id):
            return {"relativePath": "Film (2020) Bluray-1080p.mkv", "quality": {"quality": {"name": "Bluray-1080p"}}}

    class Row:
        rating_key, arr_id, episode_id, status, candidate = 5, 1, None, "importing", "{}"

    asyncio.run(replacements._imported(Row(), FakeService()))

    detail = client.get(f"/api/issues/{made}").json()
    assert detail["status"] == "resolved"
    assert "Replaced through Radarr" in detail["comment_list"][-1]["message"]
    assert detail["comment_list"][-1]["author"] == "Cartographarr"
    # The new file's details are read again, so the findings describe what landed.
    with session_scope() as db:
        assert db.get(MediaItem, 5).file_checked_at is None
    assert service.LABELS["audio"] == "Audio"

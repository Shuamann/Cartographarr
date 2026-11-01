import asyncio
from datetime import UTC, datetime, timedelta

from tests.test_auth import claim
from tests.test_privacy import PASSWORD, as_viewer

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


def test_a_row_says_whose_problem_it_looks_like(client, monkeypatch):
    """The question behind most reports is whether it is the file or the person."""
    from app.services import issues as service

    claim(client)
    seed_library()
    fake_seerr(monkeypatch, [issue(11)])
    asyncio.run(service.sync())

    row = client.get("/api/issues").json()["items"][0]
    assert (row["reporter_plays"], row["reporter_stalls"]) == (1, 2)
    assert (row["other_people"], row["other_plays"], row["other_stalls"]) == (1, 1, 0)
    assert row["in_library"] is True


def test_a_row_can_shorten_its_title_without_losing_the_episode(client, monkeypatch):
    """A report keeps one string, "Show - Episode"."""
    from app.services import issues as service

    claim(client)
    seed_library()
    fake_seerr(monkeypatch, [issue(11)])
    asyncio.run(service.sync())

    row = client.get("/api/issues").json()["items"][0]
    assert (row["show_title"], row["episode_title"], row["season"], row["episode"]) == ("The Office (US)", "Turf War", 8, 23)
    detail = client.get(f"/api/issues/{row['id']}").json()
    assert (detail["show_title"], detail["episode_title"]) == ("The Office (US)", "Turf War")


def test_resolved_and_deleted_issues_and_filters(client, monkeypatch):
    from app.services import issues as service

    claim(client)
    seed_library()
    fake_seerr(monkeypatch, [issue(11), issue(12, kind=3, status=2, message="No subtitles")])
    asyncio.run(service.sync())
    assert client.get("/api/issues").json()["items"] and client.get("/api/issues").json()["resolved"] == 1
    assert [i["issue_type"] for i in client.get("/api/issues?status=all").json()["items"]] == ["subtitles", "audio"]  # newest first
    assert len(client.get("/api/issues?status=all&issue_type=subtitles").json()["items"]) == 1

    # Deleted in Seerr: kept here, and marked, because this app is where
    # reports live. Seerr forgetting one is not somebody taking it back.
    fake_seerr(monkeypatch, [issue(11)])
    assert asyncio.run(service.sync())["no_longer_in_seerr"] == 1
    assert len(client.get("/api/issues?status=all").json()["items"]) == 2


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
    assert items[20]["in_library"] is True and items[21]["in_library"] is False


def test_a_placeholder_row_does_not_put_a_title_back_in_the_library(client, monkeypatch):
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import issues as service

    claim(client)
    fake_seerr(monkeypatch, [issue(21, kind=4, rating_key=999, media_type="movie", season=None, episode=None)])
    asyncio.run(service.sync())
    with session_scope() as db:
        db.add(MediaItem(rating_key=999, synced_at=datetime.now(UTC)))

    row = client.get("/api/issues").json()["items"][0]
    assert row["in_library"] is False
    assert client.get(f"/api/issues/{row['id']}").json()["in_library"] is False


def test_a_viewer_sees_and_reports_only_their_own(client):
    """Somebody who watches here can say what went wrong, and sees what they said."""
    from app.db import session_scope
    from app.models import History, MediaItem

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=5, title="Film", full_title="Film", media_type="movie", file_path="/movies/Film/f.mkv"))
    theirs = client.post("/api/issues", json={"rating_key": 5, "message": "The admin's own report"}).json()["id"]

    as_viewer(client, "all")  # viewer7, linked to Plex user 7
    with session_scope() as db:
        db.add(History(row_id=40, reference_id=40, rating_key=5, user_id=7, started=1000, stopped=2000,
                       media_type="movie", full_title="Film", player="iPhone", platform="iOS",
                       location="wan", transcode_decision="transcode", percent_complete=80))

    assert client.get("/api/issues?status=all").json()["items"] == []
    assert client.get(f"/api/issues/{theirs}").status_code == 404

    made = client.post("/api/issues", json={"rating_key": 5, "issue_type": "video", "message": "Picture stutters", "row_id": 40})
    assert made.status_code == 200
    listing = client.get("/api/issues").json()
    assert [i["id"] for i in listing["items"]] == [made.json()["id"]] and listing["mine_only"] is True
    # Their own plays of it, and nothing about anybody else's.
    assert listing["items"][0]["reporter_plays"] == 1 and "other_people" not in listing["items"][0]

    detail = client.get(f"/api/issues/{made.json()['id']}").json()
    assert detail["other_reports"] == [] and detail["streams"] == []
    assert all(p["user_id"] == 7 for p in detail["plays"])
    assert "file_path" not in (detail["file"] or {})
    # Whether the file is there answers their report; where it is kept does not.
    assert detail["whereis"]["state"] != "unknown" and detail["whereis"]["path"] is None
    # The play it was reported from is kept with it.
    assert detail["context"]["player"] == "iPhone" and detail["context"]["transcode_decision"] == "transcode"

    # Only an admin decides when something is closed.
    assert client.post(f"/api/issues/{made.json()['id']}/status", json={"status": "resolved"}).status_code == 403
    # A comment on their own is fine; on somebody else's it does not exist.
    assert client.post(f"/api/issues/{made.json()['id']}/comment", json={"message": "Still bad"}).status_code == 200
    assert client.post(f"/api/issues/{theirs}/comment", json={"message": "Nosy"}).status_code == 404


def test_a_viewer_only_sees_their_own_watching_when_choosing(client):
    from app.db import session_scope
    from app.models import History, MediaItem

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=5, title="Mine", full_title="Mine", media_type="movie"))
        db.add(MediaItem(rating_key=6, title="Theirs", full_title="Theirs", media_type="movie"))
    as_viewer(client, "all")
    with session_scope() as db:
        db.add(History(row_id=41, reference_id=41, rating_key=5, user_id=7, started=1000, media_type="movie"))
        db.add(History(row_id=42, reference_id=42, rating_key=6, user_id=8, started=2000, media_type="movie"))

    assert [c["rating_key"] for c in client.get("/api/issues/recent").json()["items"]] == [5]


def test_reporting_can_be_switched_off_for_viewers(client):
    claim(client)
    client.put("/api/settings", json={"viewer_reports_issues": False})
    as_viewer(client, "all")
    assert client.get("/api/issues").status_code == 403
    assert client.post("/api/issues", json={"rating_key": 5, "message": "x"}).status_code == 403


def test_an_unlinked_viewer_is_told_what_is_missing(client):
    claim(client)
    client.post("/api/auth/users", json={"username": "nobody", "password": PASSWORD, "role": "viewer"})
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "nobody", "password": PASSWORD})
    answer = client.get("/api/issues")
    assert answer.status_code == 409 and "not linked" in answer.json()["detail"]


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
    """Seerr may have been turned off since a report came in."""
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
    # The row says a new file closed it, not just that it is resolved.
    row = next(r for r in client.get("/api/issues?status=all").json()["items"] if r["id"] == made)
    assert row["replaced"] is True
    # Resolved by a person, it is resolved and nothing more.
    by_hand = client.post("/api/issues", json={"rating_key": 5, "issue_type": "video", "message": "Blocky"}).json()["id"]
    client.post(f"/api/issues/{by_hand}/status", json={"status": "resolved"})
    row = next(r for r in client.get("/api/issues?status=all").json()["items"] if r["id"] == by_hand)
    assert row["status"] == "resolved" and row["replaced"] is False
    # The new file's details are read again, so the findings describe what landed.
    with session_scope() as db:
        assert db.get(MediaItem, 5).file_checked_at is None
    assert service.LABELS["audio"] == "Audio"


def test_a_report_on_something_no_longer_in_plex_still_opens(client, monkeypatch):
    """Plex loses the item, Seerr stops naming a rating key, and the report stands."""
    from app.services import issues as service

    claim(client)
    raw = issue(30, kind=4, message="Is cam. Just fyi.")
    raw["media"] = {"mediaType": "tv", "tmdbId": 2316}
    fake_seerr(monkeypatch, [raw])
    asyncio.run(service.sync())

    row = client.get("/api/issues").json()["items"][0]
    assert row["rating_key"] is None and row["title"] is None
    detail = client.get(f"/api/issues/{row['id']}").json()
    assert detail["file"] is None and detail["plays"] == [] and detail["other_reports"] == []
    assert detail["comment_list"][0]["message"] == "Is cam. Just fyi."


def test_a_title_learned_once_is_not_forgotten(client, monkeypatch):
    """The file leaves the library; the report keeps the name it had."""
    from app.services import issues as service

    claim(client)
    seed_library()
    fake_seerr(monkeypatch, [issue(11)])
    asyncio.run(service.sync())
    assert client.get("/api/issues").json()["items"][0]["title"] == "The Office (US) - Turf War"

    gone = issue(11)
    gone["media"] = {"mediaType": "tv", "tmdbId": 2316}
    fake_seerr(monkeypatch, [gone])
    asyncio.run(service.sync())
    kept = client.get("/api/issues").json()["items"][0]
    assert kept["title"] == "The Office (US) - Turf War" and kept["rating_key"] == 880


def test_choosing_what_to_report_starts_with_what_was_watched(client, monkeypatch):
    """A text box asks someone to name a file. This offers what they watched."""
    claim(client)
    seed_library()

    recent = client.get("/api/issues/recent").json()["items"]
    assert [i["rating_key"] for i in recent] == [880]
    assert recent[0]["show"] == "The Office (US)" and recent[0]["season"] == 8 and recent[0]["episode"] == 23

    found = client.get("/api/issues/search?q=office").json()
    assert [s["title"] for s in found["shows"]] == ["The Office (US)"]
    assert found["shows"][0]["rating_key"] == 500 and found["shows"][0]["episodes"] == 1
    assert found["films"] == []

    listing = client.get("/api/issues/shows/500/episodes").json()
    assert listing["show"] == "The Office (US)"
    assert [e["rating_key"] for e in listing["episodes"]] == [880]
    assert client.get("/api/issues/shows/4/episodes").status_code == 404


def test_films_are_found_by_name(client):
    from app.db import session_scope
    from app.models import MediaItem

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=40, title="Annabelle", full_title="Annabelle", media_type="movie",
                         year=2014, summary="A doll."))
    found = client.get("/api/issues/search?q=annab").json()
    assert [f["title"] for f in found["films"]] == ["Annabelle"]
    assert found["films"][0]["year"] == 2014 and found["films"][0]["summary"] == "A doll."
    assert found["shows"] == []


def fake_notifier(monkeypatch):
    """Catch what would be sent, without sending it."""
    from app.integrations.notify import apprise_notifier

    sent: list[tuple[str, str]] = []

    async def send(self, title, body):
        sent.append((title, body))
        return True

    monkeypatch.setattr(type(apprise_notifier), "send", send)
    monkeypatch.setattr(type(apprise_notifier), "configured", lambda self: True)
    return sent


def test_a_new_report_says_what_this_app_already_knew(client, monkeypatch):
    from app.db import session_scope
    from app.models import MediaItem

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=5, title="Film", full_title="Film", media_type="movie", file_bitrate=9000,
                         file_checked_at=datetime.now(UTC),
                         audio_tracks='[{"codec": "truehd", "channels": 8, "language": "eng"}]'))
    sent = fake_notifier(monkeypatch)
    client.post("/api/issues", json={"rating_key": 5, "issue_type": "audio", "message": "No sound on the TV"})

    assert len(sent) == 1
    title, body = sent[0]
    assert title == "Film: something is wrong"
    assert "No sound on the TV" in body and "audio" in body
    # The point of sending it from here rather than Seerr: the file's own faults.
    assert "Already known about this file" in body and "TrueHD" in body


def test_reports_from_seerr_are_announced_once_they_are_known(client, monkeypatch):
    from app.services import issues as service

    claim(client)
    seed_library()
    sent = fake_notifier(monkeypatch)

    # The first sync is everything Seerr already had, which is not news.
    fake_seerr(monkeypatch, [issue(11)])
    assert asyncio.run(service.sync())["issues"] == 1
    assert sent == []

    fake_seerr(monkeypatch, [issue(11), issue(12, kind=3, message="No subtitles")])
    assert asyncio.run(service.sync())["told"] == 1
    assert len(sent) == 1 and "No subtitles" in sent[0][1]


def test_alerts_can_be_switched_off(client, monkeypatch):
    from app.db import session_scope
    from app.models import MediaItem

    claim(client)
    client.put("/api/settings", json={"issue_alerts": False})
    with session_scope() as db:
        db.add(MediaItem(rating_key=5, title="Film", full_title="Film", media_type="movie"))
    sent = fake_notifier(monkeypatch)
    client.post("/api/issues", json={"rating_key": 5, "message": "Quiet please"})
    assert sent == []


def test_a_comment_from_seerr_is_signed_by_who_wrote_it(client, monkeypatch):
    """Seerr's users are Plex logins, but a comment does not always carry the whole user."""
    from app.services import issues as service

    claim(client)
    seed_library()
    raw = issue(11)
    raw["createdBy"] = {"id": 3, "displayName": "Watcher", "plexId": 7}
    raw["comments"] = [
        {"message": "Audio is out of sync", "user": {"plexId": 7}, "createdAt": "2026-09-16T10:00:00.000Z"},
        {"message": "Still is", "user": 3, "createdAt": "2026-09-16T12:00:00.000Z"},
    ]
    fake_seerr(monkeypatch, [raw])
    asyncio.run(service.sync())

    row = client.get("/api/issues").json()["items"][0]
    thread = client.get(f"/api/issues/{row['id']}").json()["comment_list"]
    assert [c["author"] for c in thread] == ["Watcher", "Watcher"]


def test_a_quiet_sync_does_not_unsay_a_name(client, monkeypatch):
    """The issue is read in full when it changes and from Seerr's list the rest of the time."""
    from app.services import issues as service

    claim(client)
    seed_library()

    def full():
        raw = issue(11)
        raw["comments"].append({"message": "Replaced it", "user": {"displayName": "Keeper", "plexId": 1},
                                "createdAt": "2026-09-16T12:00:00.000Z"})
        return raw

    fake_seerr(monkeypatch, [full()])
    asyncio.run(service.sync())

    thin = full()
    for c in thin["comments"]:
        c["user"] = {}
    # Same updatedAt, so the list copy is the one stored this time.
    fake_seerr(monkeypatch, [thin], details={11: thin})
    asyncio.run(service.sync())

    row = client.get("/api/issues").json()["items"][0]
    thread = client.get(f"/api/issues/{row['id']}").json()["comment_list"]
    assert [c["author"] for c in thread] == ["Watcher", "Keeper"]


def test_an_unsigned_first_comment_is_the_reporters(client):
    """Seerr opens every issue with the reporter's own message."""
    import json

    from app.db import session_scope
    from app.models import Issue

    claim(client)
    with session_scope() as db:
        db.add(Issue(source="seerr", seerr_id=40, issue_type="other", status="open", message="Bad copy",
                     media_type="movie", reporter_name="Watcher", reporter_user_id=7,
                     comments=json.dumps([{"message": "Bad copy", "author": None, "created_at": "2026-09-16T10:00:00"},
                                          {"message": "Thanks", "author": None, "created_at": "2026-09-16T11:00:00"}])))
    row = client.get("/api/issues").json()["items"][0]
    thread = client.get(f"/api/issues/{row['id']}").json()["comment_list"]
    assert thread[0]["author"] == "Watcher" and thread[1]["author"] is None


def test_a_film_is_not_a_special(client, monkeypatch):
    """Seerr sends season 0 and episode 0 for a film."""
    from app.services import issues as service

    claim(client)
    fake_seerr(monkeypatch, [issue(20, kind=4, rating_key=40, media_type="movie", season=0, episode=0)])
    asyncio.run(service.sync())
    row = client.get("/api/issues").json()["items"][0]
    assert row["season"] is None and row["episode"] is None

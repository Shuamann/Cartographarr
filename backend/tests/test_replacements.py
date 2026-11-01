import asyncio
import json
from datetime import UTC, datetime, timedelta

from tests.test_auth import claim


def test_release_names_are_read():
    from app.services.replacements import parse_release

    p = parse_release("Movie.2019.1080p.BluRay.x264.DD5.1-GROUP")
    assert p == {"resolution": "1080p", "video_codec": "h264", "audio_codec": "ac3", "audio_channels": 6, "source": "Blu-ray"}
    q = parse_release("Movie 2019 2160p UHD BluRay REMUX HDR10 HEVC TrueHD Atmos 7.1-X")
    assert q["resolution"] == "2160p" and q["video_codec"] == "hevc" and q["hdr"] == "HDR10"
    assert q["audio_codec"] == "truehd" and q["audio_channels"] == 8 and q["source"] == "Remux"
    assert parse_release("Show.S01E02.720p.WEB-DL.DDP5.1.H.264")["audio_codec"] == "eac3"


def test_releases_are_compared_with_the_current_file():
    from app.services.replacements import compare_releases

    current = {"findings": [{"key": "no_compatible_audio"}, {"key": "over_threshold"}]}
    releases = [
        {"guid": "a", "indexerId": 1, "title": "Film.1080p.BluRay.x264.TrueHD.7.1", "size": 40_000_000_000,
         "approved": False, "rejections": ["Not an upgrade for existing movie file"]},
        {"guid": "b", "indexerId": 1, "title": "Film.1080p.WEB-DL.DDP5.1.H.264", "size": 6_000_000_000,
         "approved": False, "rejections": ["Not an upgrade for existing movie file"]},
        {"guid": "c", "indexerId": 2, "title": "Film.1080p.WEB-DL.AAC.2.0.x264", "size": 3_000_000_000,
         "approved": False, "rejections": ["Release is blocklisted"]},
    ]
    out = compare_releases(releases, current, duration_ms=2 * 3600 * 1000, threshold_kbps=20000)
    assert [r["guid"] for r in out] == ["b", "a", "c"]
    assert out[0]["fixes"] == ["Playable audio (EAC3)", "About 7 Mbps, under your limit"] and out[0]["held"] is True
    assert out[-1]["blocked"] is True


class FakeRadarr:
    name, label, path = "radarr", "Radarr", "movie"

    def __init__(self):
        self.queue_records = []
        self.history_records = []
        self.file_id = 10
        self.sent = []

    def configured(self):
        return True

    # alt_id is the second id tried where the service filters on one, so a
    async def find(self, external_id, alt_id=None):
        return {"id": 7, "title": "Film"}

    async def locate(self, external_id, season, episode, alt_id=None):
        return {"id": 7, "title": "Film"}, None

    async def releases(self, arr_id, episode_id):
        return [{"guid": "g1", "indexerId": 3, "title": "Film.1080p.WEB-DL.DDP5.1.H.264", "size": 5_000_000_000,
                 "approved": False, "rejections": ["Not an upgrade for existing movie file"]}]

    async def grab(self, guid, indexer_id):
        self.sent.append(("grab", guid, indexer_id))
        return {}

    async def queue(self):
        return self.queue_records

    async def history(self, arr_id, episode_id):
        return self.history_records

    async def manual_import_candidates(self, download_id):
        return [{"path": "/downloads/Film/film.mkv", "name": "Film.1080p.WEB-DL.DDP5.1.H.264.mkv", "size": 5_000_000_000,
                 "quality": {"quality": {"name": "WEBDL-1080p"}}, "rejections": [{"reason": "Not an upgrade"}]},
                {"path": "/downloads/Film/sample.mkv", "name": "sample.mkv", "size": 20_000_000}]

    async def manual_import(self, files, arr_id, episode_id, download_id):
        self.sent.append(("import", [f["path"] for f in files], arr_id, download_id))

    async def remove_from_queue(self, queue_id):
        self.sent.append(("remove", queue_id))

    async def current_file(self, arr_id, episode_id):
        return {"id": self.file_id, "relativePath": "Film.mkv", "size": 5_000_000_000,
                "mediaInfo": {"audioCodec": "EAC3", "videoCodec": "x264"}}


def _setup(client, monkeypatch):
    from app.db import session_scope
    from app.integrations import arr
    from app.models import MediaItem
    from app.services import replacements

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=1, title="Film", full_title="Film", media_type="movie", tmdb_id="603",
                         duration=7200000, file_bitrate=30000,
                         audio_tracks=json.dumps([{"codec": "truehd", "channels": 8, "language": "eng"}])))
    fake = FakeRadarr()
    monkeypatch.setattr(arr, "radarr", fake)
    monkeypatch.setattr(arr, "for_media_type", lambda media_type: fake)
    monkeypatch.setattr(replacements, "_service", lambda name: fake)
    return fake


def _poll():
    from app.services import replacements

    return asyncio.run(replacements.poll())


def test_find_queue_hold_and_confirm(client, monkeypatch):
    fake = _setup(client, monkeypatch)
    found = client.get("/api/library/file/1/releases").json()
    assert found["service"] == "Radarr" and found["releases"][0]["fixes"][0] == "Playable audio (EAC3)"

    queued = client.post("/api/library/file/1/replace", json={"release": found["releases"][0]}).json()
    assert queued["status"] == "queued" and fake.sent == [("grab", "g1", 3)]

    fake.queue_records = [{"id": 55, "movieId": 7, "title": "Film.1080p.WEB-DL.DDP5.1.H.264", "downloadId": "abc",
                           "size": 100, "sizeleft": 40, "status": "downloading", "trackedDownloadState": "downloading"}]
    _poll()
    row = client.get("/api/library/replacements").json()[0]
    assert row["status"] == "downloading" and row["progress"] == 0.6

    fake.queue_records[0].update(sizeleft=0, status="completed", trackedDownloadState="importBlocked",
                                 statusMessages=[{"messages": ["Not an upgrade for existing movie file"]}])
    _poll()
    row = client.get("/api/library/replacements").json()[0]
    assert row["status"] == "ready" and row["candidate"]["name"].startswith("Film.1080p")
    assert "Not an upgrade" in row["message"]

    confirmed = client.post(f"/api/library/replacements/{row['id']}/confirm").json()
    assert confirmed["status"] == "importing"
    assert fake.sent[-1] == ("import", ["/downloads/Film/film.mkv"], 7, "abc")

    fake.queue_records = []
    fake.file_id = 11
    _poll()
    row = client.get("/api/library/replacements").json()[0]
    assert row["status"] == "imported" and row["candidate"]["imported"]["audio_codec"] == "EAC3"
    actions = [e["action"] for e in client.get("/api/log?kind=changes").json()]
    assert "library.replace" in actions and "library.replace_confirm" in actions


def test_deny_removes_and_blocks(client, monkeypatch):
    fake = _setup(client, monkeypatch)
    release = client.get("/api/library/file/1/releases").json()["releases"][0]
    queued = client.post("/api/library/file/1/replace", json={"release": release}).json()
    fake.queue_records = [{"id": 56, "movieId": 7, "title": release["title"], "downloadId": "d2", "size": 1,
                           "sizeleft": 0, "status": "completed", "trackedDownloadState": "importPending"}]
    _poll()
    assert client.post(f"/api/library/replacements/{queued['id']}/deny").json()["status"] == "denied"
    assert fake.sent[-1] == ("remove", 56)
    assert client.post(f"/api/library/replacements/{queued['id']}/confirm").status_code == 409


def test_an_upgrade_imported_by_radarr_is_recorded(client, monkeypatch):
    from app.db import session_scope
    from app.models import Replacement

    fake = _setup(client, monkeypatch)
    release = client.get("/api/library/file/1/releases").json()["releases"][0]
    queued = client.post("/api/library/file/1/replace", json={"release": release}).json()
    fake.queue_records = [{"id": 57, "movieId": 7, "title": release["title"], "downloadId": "d3", "size": 1,
                           "sizeleft": 1, "status": "downloading", "trackedDownloadState": "downloading"}]
    _poll()
    fake.queue_records, fake.file_id = [], 99
    with session_scope() as db:
        db.get(Replacement, queued["id"]).created_at = datetime.now(UTC) - timedelta(hours=1)
    _poll()
    assert client.get("/api/library/replacements").json()[0]["status"] == "imported_automatically"



def test_a_download_that_fails_before_reaching_the_queue_is_caught(client, monkeypatch):
    """Sonarr's history says Download failed; the queue never showed it."""
    fake = _setup(client, monkeypatch)
    release = client.get("/api/library/file/1/releases").json()["releases"][0]
    queued = client.post("/api/library/file/1/replace", json={"release": release}).json()
    now = datetime.now(UTC).isoformat()
    fake.history_records = [
        {"eventType": "downloadFailed", "sourceTitle": release["title"], "downloadId": "zz", "date": now,
         "data": {"message": "PAR Status: NONE - Delete Status: HEALTH"}},
        {"eventType": "grabbed", "sourceTitle": release["title"], "downloadId": "zz", "date": now, "data": {}},
        # From before this replacement: ignored.
        {"eventType": "downloadFailed", "sourceTitle": release["title"], "downloadId": "old",
         "date": (datetime.now(UTC) - timedelta(days=3)).isoformat(), "data": {"message": "old"}},
    ]
    live = client.get(f"/api/library/replacements/{queued['id']}/live").json()
    assert live["status"] == "failed" and "Delete Status: HEALTH" in live["message"]
    assert [e["label"] for e in live["live"]["events"]] == ["Download failed", "Sent to the download client"]
    assert live["checked_at"] is not None


def test_live_shows_the_queue_entry(client, monkeypatch):
    fake = _setup(client, monkeypatch)
    release = client.get("/api/library/file/1/replace".replace("/replace", "/releases")).json()["releases"][0]
    queued = client.post("/api/library/file/1/replace", json={"release": release}).json()
    fake.queue_records = [{"id": 60, "movieId": 7, "title": release["title"], "downloadId": "q1", "size": 200, "sizeleft": 50,
                           "status": "downloading", "trackedDownloadState": "downloading", "timeleft": "00:04:10",
                           "downloadClient": "NZBGet"}]
    live = client.get(f"/api/library/replacements/{queued['id']}/live").json()
    assert live["status"] == "downloading" and live["live"]["queue"]["progress"] == 0.75
    assert live["live"]["queue"]["time_left"] == "00:04:10" and live["live"]["queue"]["client"] == "NZBGet"


def test_what_it_fixes_comes_first_then_the_profile_score():
    from app.services.replacements import compare_releases

    current = {"findings": [{"key": "no_compatible_audio"}]}
    releases = [
        {"guid": "well-rated", "indexerId": 1, "title": "Film.1080p.WEB-DL.x264", "size": 5_000_000_000,
         "approved": True, "customFormatScore": 500},
        {"guid": "fixes-it", "indexerId": 1, "title": "Film.1080p.WEB-DL.DDP5.1.x264", "size": 6_000_000_000,
         "approved": True, "customFormatScore": 0},
        {"guid": "fixes-it-too", "indexerId": 1, "title": "Film.1080p.WEB-DL.DDP5.1.H.264", "size": 7_000_000_000,
         "approved": True, "customFormatScore": 90},
    ]
    out = compare_releases(releases, current, duration_ms=2 * 3600 * 1000, threshold_kbps=20000)
    # Both the ones that fix the audio come first; between them, the profile
    # decides; the highly rated one that fixes nothing is last.
    assert [r["guid"] for r in out] == ["fixes-it-too", "fixes-it", "well-rated"]
    assert out[0]["custom_format_score"] == 90 and out[0]["fixes"]

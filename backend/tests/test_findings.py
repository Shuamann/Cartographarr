"""What is wrong with a file and how to fix it, and handing it to Radarr or
Sonarr. The Radarr and Sonarr APIs are faked; nothing real is searched."""

import json

from tests.test_auth import claim


def file(**over):
    base = {
        "file_bitrate": 8000, "file_container": "mkv", "video_codec": "h264", "video_bit_depth": 8,
        "video_dynamic_range": "SDR", "plays": 0, "remote_plays": 0, "transcodes": 0,
        "audio_tracks": [{"codec": "eac3", "channels": 6, "language": "eng"}],
        "subtitle_tracks": [{"codec": "srt", "language": "eng", "forced": False}],
    }
    base.update(over)
    return base


def keys(findings):
    return [f["key"] for f in findings]


def test_a_clean_file_has_nothing_to_say():
    from app.services.findings import explain

    assert explain(file(), 20000) == []


def test_audio_and_subtitle_findings_name_the_tracks():
    from app.services.findings import explain

    out = explain(file(audio_tracks=[{"codec": "truehd", "channels": 8, "language": "eng"},
                                     {"codec": "dca-ma", "channels": 6, "language": None}]), 20000, arr_label="Radarr")
    assert keys(out) == ["no_compatible_audio", "untagged_audio"]
    assert "Dolby TrueHD 7.1 (eng)" in out[0]["detail"] and "DTS-HD MA 5.1" in out[0]["detail"]
    assert "Radarr" in out[0]["arr"]

    anime = explain(file(subtitle_tracks=[{"codec": "ass", "language": "eng"}] * 2 + [{"codec": "srt", "language": "eng"}] * 5),
                    20000, transcode_causes=[{"cause": "subtitle_burn", "streams": 3}])
    assert keys(anime) == ["styled_subtitles", "subtitle_clutter"]
    assert anime[0]["severity"] == "medium" and "3 recorded streams" in anime[0]["detail"]

    pgs = explain(file(subtitle_tracks=[{"codec": "pgs", "language": "eng"}]), 20000)
    assert keys(pgs) == ["image_subtitles_only"]


def test_bitrate_codec_and_stall_findings_use_how_it_was_watched():
    from app.services.findings import explain

    big = explain(file(file_bitrate=45000, remote_plays=4, plays=4, transcodes=3), 20000)
    assert "over_threshold" in keys(big) and "45.0 Mbps" in big[0]["detail"]
    # Watched only at home: the bitrate is not a problem.
    assert "over_threshold" not in keys(explain(file(file_bitrate=45000, plays=4), 20000))

    hevc = explain(file(video_codec="hevc", video_bit_depth=10, plays=6, remote_plays=6, transcodes=5), 20000)
    assert keys(hevc) == ["video_codec"] and "HEVC 10-bit" in hevc[0]["detail"]

    stalls = explain(file(), 20000, stall_causes=[{"cause": "viewer", "stalls": 4}])
    assert keys(stalls) == ["stalls"] and "their device or connection" in stalls[0]["detail"]

    old = explain(file(file_container="avi"), 20000)
    assert keys(old) == ["legacy_container"] and "-c copy" in old[0]["fix"]


def _seed_movie_and_episode():
    from app.db import session_scope
    from app.models import MediaItem

    with session_scope() as db:
        db.add(MediaItem(rating_key=1, title="Film", full_title="Film", media_type="movie", tmdb_id="603",
                         audio_tracks=json.dumps([{"codec": "truehd", "channels": 8, "language": "eng"}])))
        db.add(MediaItem(rating_key=20, title="Show", media_type="show", tvdb_id="81189"))
        db.add(MediaItem(rating_key=21, title="Pilot", full_title="Show - Pilot", media_type="episode",
                         grandparent_rating_key=20, parent_media_index=1, media_index=1))


def test_file_detail_includes_findings_and_arr(client):
    claim(client)
    _seed_movie_and_episode()
    detail = client.get("/api/library/file/1").json()
    assert detail["findings"][0]["key"] == "no_compatible_audio"
    assert detail["arr"] == {"name": "radarr", "label": "Radarr", "configured": False}
    res = client.post("/api/library/file/1/arr", json={"action": "search"})
    assert res.status_code == 409 and "Connect Radarr" in res.json()["detail"]
    assert client.post("/api/library/file/1/arr", json={"action": "delete"}).status_code == 400


def test_search_and_tag_go_to_the_right_app(client, monkeypatch):
    from app.integrations import arr

    claim(client)
    _seed_movie_and_episode()
    sent = []

    async def fake_get(url, headers=None, params=None, timeout=15.0):
        if url.endswith("/api/v3/movie"):
            return [{"id": 7, "title": "Film"}] if params == {"tmdbId": "603"} else []
        if url.endswith("/api/v3/series"):
            return [{"id": 9, "title": "Show"}] if params == {"tvdbId": "81189"} else []
        if url.endswith("/api/v3/episode"):
            return [{"id": 100, "episodeNumber": 1}, {"id": 101, "episodeNumber": 2}]
        if url.endswith("/api/v3/tag"):
            return [{"id": 3, "label": "cartographarr-replace"}]
        raise AssertionError(url)

    async def fake_send(self, method, path, body):
        sent.append((self.name, method, path, body))
        return {"id": 3}

    monkeypatch.setattr(arr, "get_json", fake_get)
    monkeypatch.setattr(arr.ArrIntegration, "_send", fake_send)
    monkeypatch.setattr(arr.ArrIntegration, "configured", lambda self: True)

    assert client.post("/api/library/file/1/arr", json={"action": "search"}).json()["message"] == "Radarr is searching for Film"
    assert client.post("/api/library/file/21/arr", json={"action": "search"}).json()["message"] == "Sonarr is searching for Show S01E01"
    assert client.post("/api/library/file/1/arr", json={"action": "tag"}).status_code == 200
    assert sent == [
        ("radarr", "POST", "/api/v3/command", {"name": "MoviesSearch", "movieIds": [7]}),
        ("sonarr", "POST", "/api/v3/command", {"name": "EpisodeSearch", "episodeIds": [100]}),
        ("radarr", "PUT", "/api/v3/movie/editor", {"movieIds": [7], "tags": [3], "applyTags": "add"}),
    ]
    actions = [e["action"] for e in client.get("/api/log?kind=changes").json()]
    assert actions.count("library.search") == 2 and "library.tag" in actions


def test_reasons_for_older_plays_are_read_from_tautulli(client, monkeypatch):
    """Plays from before live recording have no reasons; Tautulli's per-play
    stream details supply them."""
    import time

    from app.db import session_scope
    from app.models import History, MediaItem
    from app.tautulli import client as tautulli

    claim(client)
    now = int(time.time())
    with session_scope() as db:
        db.add(MediaItem(rating_key=5, title="Frozen", full_title="Frozen", media_type="movie", file_bitrate=2700,
                         audio_tracks=json.dumps([{"codec": "aac", "channels": 6, "language": "eng"}]),
                         subtitle_tracks="[]"))
        for i in range(4):
            db.add(History(row_id=50 + i, rating_key=5, user_id=1, location="wan", transcode_decision="transcode",
                           started=now - i * 3600, platform="Roku"))

    asked = []

    async def fake_call(self, cmd, **params):
        asked.append((cmd, params.get("row_id")))
        return {"video_decision": "direct play", "audio_decision": "transcode", "audio_codec": "aac", "stream_audio_codec": "aac"}

    monkeypatch.setattr(tautulli.TautulliClient, "call", fake_call)
    detail = client.get("/api/library/file/5?days=30").json()
    assert detail["transcode_causes"] == [{"cause": "audio_channels", "streams": 3, "from_history": True}]
    assert [f["key"] for f in detail["findings"]] == ["aac_surround"]
    assert "Roku" in detail["findings"][0]["detail"] and "recent plays" in detail["findings"][0]["detail"]
    assert len(asked) == 3  # only the latest three

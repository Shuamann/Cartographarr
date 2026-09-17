"""Coercion checks. Tautulli types everything loosely, so this is where the
bugs are. The upsert itself is SQLAlchemy's problem, not ours.
"""

from app.services.sync import _bool, _int, _map_history, _split_guids


def test_int_survives_tautullis_stringly_typed_numbers():
    assert _int("1") == 1
    assert _int(1) == 1
    assert _int("") is None
    assert _int(None) is None
    assert _int("not a number") is None


def test_bool_distinguishes_false_from_unknown():
    # secure/relayed are tri-state: True, False, or "Tautulli didn't say".
    assert _bool("1") is True
    assert _bool("0") is False
    assert _bool("") is None
    assert _bool(None) is None


def test_map_history_coerces_a_real_row():
    row = {
        "row_id": "42",
        "user_id": "122693376",
        "machine_id": "abc123",
        "ip_address": "1.2.3.4",
        "started": "1740268263",
        "watched_status": "0.5",
        "secure": "1",
        "relayed": "0",
        "live": "0",
        "title": "",
    }
    out = _map_history(row)
    assert out["row_id"] == 42
    assert out["started"] == 1740268263
    assert out["watched_status"] == 0.5
    assert out["secure"] is True
    assert out["relayed"] is False
    assert out["live"] is False
    assert out["title"] is None  # empty string is absence, not a title


def test_split_guids():
    guids = ["imdb://tt32333324", "tmdb://1560520", "tvdb://373216"]
    assert _split_guids(guids) == {
        "imdb_id": "tt32333324",
        "tmdb_id": "1560520",
        "tvdb_id": "373216",
    }


def test_split_guids_tolerates_missing_and_partial():
    assert _split_guids(None) == {"imdb_id": None, "tmdb_id": None, "tvdb_id": None}
    assert _split_guids(["tmdb://99"])["tmdb_id"] == "99"
    assert _split_guids(["tmdb://99"])["imdb_id"] is None


def test_map_history_keeps_episode_numbers():
    out = _map_history({
        "row_id": "7", "media_type": "episode", "grandparent_title": "ER",
        "parent_media_index": "12", "media_index": 21, "title": "The Gallant Hero",
    })
    assert (out["grandparent_title"], out["parent_media_index"], out["media_index"]) == ("ER", 12, 21)
    movie = _map_history({"row_id": "8", "media_type": "movie", "parent_media_index": "", "media_index": ""})
    assert movie["parent_media_index"] is None and movie["media_index"] is None


def test_file_details_from_metadata():
    import json

    from app.services.sync import file_details

    meta = {"media_info": [{
        "bitrate": "12236", "container": "mkv", "video_codec": "h264", "video_full_resolution": "1080p",
        "audio_codec": "eac3", "audio_channels": "6",
        "parts": [{"file": "/movies/Film (2012)/Film.mkv", "file_size": "8647859556", "streams": [
            {"type": "1", "video_codec": "h264", "video_bit_depth": "8", "video_dynamic_range": "SDR"},
            {"type": "2", "audio_codec": "eac3", "audio_channels": "6", "audio_language_code": "eng", "audio_bitrate": "1019"},
            {"type": "2", "audio_codec": "aac", "audio_channels": "2", "audio_language_code": "eng", "audio_bitrate": "80"},
            {"type": "3", "subtitle_codec": "srt", "subtitle_language_code": "eng", "subtitle_forced": 0, "subtitle_location": "embedded"},
        ]}],
    }]}
    d = file_details(meta)
    assert d["file_bitrate"] == 12236 and d["file_size"] == 8647859556 and d["video_bit_depth"] == 8
    assert [a["codec"] for a in json.loads(d["audio_tracks"])] == ["eac3", "aac"]
    assert json.loads(d["subtitle_tracks"])[0] == {"codec": "srt", "language": "eng", "forced": False, "location": "embedded"}
    assert d["versions"] == 1 and d["file_checked_at"] is not None

    # A show has no file, but is still marked checked so it is not asked again.
    empty = file_details({"title": "A Show"})
    assert empty["file_bitrate"] is None and empty["audio_tracks"] is None and empty["file_checked_at"] is not None


def test_metadata_upsert_accepts_a_tombstone_beside_a_full_row(client):
    """A deleted item's tombstone has far fewer columns than a real row, and
    both arrive in one batch."""
    from datetime import UTC, datetime

    from app.db import session_scope
    from app.models import MediaItem
    from app.services.sync import _tombstone, _upsert

    full = {"rating_key": 1, "title": "Film", "media_type": "movie", "synced_at": datetime.now(UTC), "file_bitrate": 5000}
    with session_scope() as db:
        _upsert(db, MediaItem, [full, _tombstone(2)])
    with session_scope() as db:
        assert db.get(MediaItem, 1).file_bitrate == 5000
        assert db.get(MediaItem, 2).title is None


def test_episode_numbers_are_copied_from_history_to_cached_titles(client):
    from app.db import session_scope
    from app.models import History, MediaItem
    from app.services.sync import _copy_episode_numbers

    with session_scope() as db:
        db.add(MediaItem(rating_key=5, title="Pilot", media_type="episode"))
        db.add(MediaItem(rating_key=6, title="Film", media_type="movie"))
        db.add(History(row_id=1, rating_key=5, media_type="episode", grandparent_title="Show", parent_media_index=1, media_index=1))
    _copy_episode_numbers()
    with session_scope() as db:
        ep = db.get(MediaItem, 5)
        assert (ep.grandparent_title, ep.parent_media_index, ep.media_index) == ("Show", 1, 1)
        assert db.get(MediaItem, 6).media_index is None


def test_user_sync_keeps_shared_libraries(client):
    import asyncio
    import json

    from app.db import session_scope
    from app.models import User
    from app.services.sync import sync_users

    class Fake:
        async def call(self, cmd, **params):
            if cmd == "get_users_table":
                return {"data": [{"user_id": "5", "username": "pat", "is_active": 1}]}
            if cmd == "get_users":
                return [{"user_id": "5", "shared_libraries": ["3", "1"], "is_allow_sync": 0}]
            return None

    asyncio.run(sync_users(Fake()))
    with session_scope() as db:
        pat = db.get(User, 5)
        assert json.loads(pat.shared_libraries) == ["3", "1"] and pat.allow_sync is False


def test_history_is_synced_one_row_per_session(client):
    """Merged plays keep only the last device, so a play carried from a phone
    to a TV lost where it started. Every session is its own row."""
    import asyncio

    from sqlalchemy import select

    from app.db import session_scope
    from app.models import History
    from app.services.sync import sync_history
    from app.settings_store import current

    sessions = [
        {"row_id": "10", "reference_id": "10", "user_id": "1", "rating_key": "5", "started": "100", "stopped": "200",
         "media_type": "episode", "full_title": "Show - Ep", "media_index": "23", "parent_media_index": "8",
         "grandparent_title": "Show", "machine_id": "phone", "ip_address": "1.2.3.4", "platform": "iOS"},
        {"row_id": "13", "reference_id": "10", "user_id": "1", "rating_key": "5", "started": "900", "stopped": "1500",
         "media_type": "episode", "full_title": "Show - Ep", "media_index": "23", "parent_media_index": "8",
         "grandparent_title": "Show", "machine_id": "tv", "ip_address": "5.6.7.8", "platform": "Roku"},
    ]
    asked = []

    class Fake:
        async def call(self, cmd, **params):
            asked.append(params)
            if params["start"]:
                return {"data": [], "recordsFiltered": len(sessions)}
            return {"data": sessions, "recordsFiltered": len(sessions)}

    assert asyncio.run(sync_history(Fake(), current(), full=True)) == 2
    assert all(p["grouping"] == 0 for p in asked)
    with session_scope() as db:
        rows = db.execute(select(History).order_by(History.row_id)).scalars().all()
        assert [(r.row_id, r.machine_id, r.started, r.media_index) for r in rows] == [
            (10, "phone", 100, 23), (13, "tv", 900, 23),
        ]

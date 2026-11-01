import asyncio
import json
import xml.etree.ElementTree as ElementTree
from types import SimpleNamespace

from app.plex import library
from tests.test_auth import claim

TAUTULLI_KEYS = {
    "rating_key", "parent_rating_key", "grandparent_rating_key", "section_id", "media_type", "title",
    "full_title", "grandparent_title", "media_index", "parent_media_index", "year", "thumb", "file_bitrate",
    "file_container", "video_codec", "video_resolution", "audio_codec", "audio_channels", "file_size",
}


def guids(*ids):
    return [SimpleNamespace(id=i) for i in ids]


def a_media(**over):
    part = SimpleNamespace(file="/media/movies/Paul (2011)/Paul.mkv", size=8_123_456_789, container="mkv")
    base = dict(
        container="mkv", bitrate=9816, width=1920, height=816, videoResolution="1080", videoCodec="hevc",
        audioCodec="eac3", audioChannels=6, videoProfile="main 10", videoFrameRate="24p", parts=[part],
    )
    return SimpleNamespace(**{**base, **over})


def a_film(**over):
    base = dict(
        ratingKey=4101, type="movie", title="Paul", year=2011, thumb="/library/metadata/4101/thumb/1",
        duration=6250000, media=[a_media()],
        guids=guids("imdb://tt1092026", "tmdb://39513", "tvdb://1361"),
    )
    return SimpleNamespace(**{**base, **over})


def an_episode(**over):
    base = dict(
        ratingKey=63424, type="episode", title="Indescribable Compassion", year=2019, thumb=None,
        duration=3114112, grandparentRatingKey=63000, grandparentTitle="The Chosen",
        parentRatingKey=63001, parentIndex=1, index=3,
        media=[a_media(parts=[SimpleNamespace(file="/media/tv/The Chosen/S01E03.mkv", size=900_000_000)])],
        guids=guids("imdb://tt9900001", "tmdb://1868842", "tvdb://7121397"),
    )
    return SimpleNamespace(**{**base, **over})


def test_the_row_has_every_field_the_tautulli_scan_writes():
    row = library.row(a_film(), 1)
    assert TAUTULLI_KEYS <= set(row)


def test_a_film_carries_its_file_and_all_three_ids():
    row = library.row(a_film(), 1)
    assert row["rating_key"] == 4101 and row["section_id"] == 1 and row["media_type"] == "movie"
    assert row["title"] == row["full_title"] == "Paul" and row["year"] == 2011
    # What the on-disk check and tidying are built on, and what Tautulli's
    # listing never gave.
    assert row["file_path"] == "/media/movies/Paul (2011)/Paul.mkv"
    assert row["file_size"] == 8_123_456_789
    assert row["file_container"] == "mkv" and row["file_bitrate"] == 9816
    assert row["video_codec"] == "hevc" and row["audio_codec"] == "eac3" and row["audio_channels"] == 6
    # Through the same helper as the Tautulli scan, so 4K copies and Problem
    # files compare like with like.
    assert row["video_resolution"] == "1080p"
    assert (row["imdb_id"], row["tmdb_id"], row["tvdb_id"]) == ("tt1092026", "39513", "1361")
    assert row["grandparent_title"] is None and row["media_index"] is None


def test_an_episode_carries_its_show_and_season():
    row = library.row(an_episode(), 2)
    assert row["full_title"] == "The Chosen - Indescribable Compassion"
    assert row["grandparent_title"] == "The Chosen"
    assert row["grandparent_rating_key"] == 63000 and row["parent_rating_key"] == 63001
    assert row["parent_media_index"] == 1 and row["media_index"] == 3
    assert row["file_path"] == "/media/tv/The Chosen/S01E03.mkv"


def test_an_episode_without_its_show_named_borrows_the_show_it_was_listed_under():
    show = SimpleNamespace(ratingKey=63000, title="The Chosen")
    row = library.row(an_episode(grandparentTitle=None, grandparentRatingKey=None), 2, show)
    assert row["grandparent_rating_key"] == 63000
    assert row["full_title"] == "The Chosen - Indescribable Compassion"


def test_shows_seasons_and_tracks_are_not_stored_as_files():
    """Only films and episodes are files."""
    for kind in ("show", "season", "track", "artist", "photo", None):
        assert library.row(a_film(type=kind), 1) is None, kind
    assert library.row(a_film(ratingKey=None), 1) is None


def test_an_item_with_no_media_or_no_parts_is_stored_without_file_details():
    """Kept rather than skipped."""
    for bare in (a_film(media=[]), a_film(media=None), a_film(media=[a_media(parts=[])])):
        row = library.row(bare, 1)
        assert row["rating_key"] == 4101 and row["title"] == "Paul"
        assert row["file_path"] is None and row["file_size"] is None
    no_parts = library.row(a_film(media=[a_media(parts=[])]), 1)
    assert no_parts["file_container"] == "mkv" and no_parts["file_bitrate"] == 9816


def test_a_missing_id_leaves_only_that_one_empty():
    row = library.row(an_episode(guids=guids("imdb://tt9900001", "tvdb://7121397")), 2)
    assert (row["imdb_id"], row["tmdb_id"], row["tvdb_id"]) == ("tt9900001", None, "7121397")
    assert library.row(a_film(guids=[]), 1)["tmdb_id"] is None
    # Plex's own agent ids and anything unreadable are ignored, not stored.
    odd = library.row(a_film(guids=guids("plex://movie/5d776", None, "tmdb://")), 1)
    assert (odd["imdb_id"], odd["tmdb_id"], odd["tvdb_id"]) == (None, None, None)


def test_a_blank_on_a_listed_item_does_not_fetch_it_again():
    """plexapi reloads a listed item from the server whenever something read from it is empty."""
    from plexapi.video import Movie

    asked = []

    def query(key, *args, **kwargs):
        asked.append(key)
        raise AssertionError(f"fetched {key}")

    data = ElementTree.fromstring(
        '<Video ratingKey="77" key="/library/metadata/77" type="movie" title="Home Movie">'
        '<Media container="mp4" bitrate="2000" videoResolution="720" videoCodec="h264" audioCodec="aac" audioChannels="2">'
        '<Part file="/media/movies/home.mp4" size="1234" /></Media></Video>'
    )
    film = Movie(SimpleNamespace(query=query), data, initpath="/library/sections/1/all")
    assert film.isPartialObject()
    row = library.row(film, 1)
    assert asked == []
    assert row["year"] is None and row["tmdb_id"] is None and row["thumb"] is None
    assert row["file_path"] == "/media/movies/home.mp4" and row["file_size"] == 1234
    assert row["video_resolution"] == "720p"


def a_server():
    paged = []

    def films(**kwargs):
        paged.append(kwargs.get("container_size"))
        return [a_film(), a_film(ratingKey=4102, title="Hot Fuzz", media=[])]

    show = SimpleNamespace(ratingKey=63000, title="The Chosen", type="show",
                           episodes=lambda **kwargs: [an_episode(), an_episode(ratingKey=63425, index=4)])
    sections = [
        SimpleNamespace(key=1, type="movie", title="Films", all=films),
        SimpleNamespace(key=2, type="show", title="TV", all=lambda **kwargs: [show]),
        SimpleNamespace(key=3, type="artist", title="Music", all=lambda **kwargs: [a_film(type="track")]),
    ]
    return SimpleNamespace(library=SimpleNamespace(sections=lambda: sections)), paged


def test_every_library_is_read_and_large_ones_are_paged():
    plex, paged = a_server()
    rows = [r for s in plex.library.sections() for r in library.section_rows(s)]
    assert [(r["rating_key"], r["section_id"]) for r in rows] == [(4101, 1), (4102, 1), (63424, 2), (63425, 2)]
    # Not plexapi's default of a hundred at a time.
    assert paged == [library.PAGE]


def test_the_setting_sends_the_scan_to_plex_and_the_rows_are_stored(client, monkeypatch):
    """The setting was offered and read by nothing."""
    from app import settings_store
    from app.db import session_scope
    from app.models import LibrarySize, MediaItem
    from app.plex import server
    from app.services import library_scan

    claim(client)
    settings_store.save({"library_source": "plex"})
    plex, _ = a_server()
    monkeypatch.setattr(server, "server", lambda fresh=False: plex)

    class NoTautulli:
        async def call(self, cmd, **params):
            raise AssertionError(f"asked Tautulli for {cmd}")

    result = asyncio.run(library_scan.scan(NoTautulli()))
    assert result["movies"] == 2 and result["episodes"] == 2 and result["new"] == 4
    with session_scope() as db:
        film = db.get(MediaItem, 4101)
        assert film.file_path == "/media/movies/Paul (2011)/Paul.mkv"
        assert (film.imdb_id, film.tmdb_id, film.tvdb_id) == ("tt1092026", "39513", "1361")
        assert film.library_seen_at is not None and film.duration == 6250000
        assert db.get(MediaItem, 4102).file_size is None
        sizes = {s.section_id: (s.files, s.bytes) for s in db.query(LibrarySize).all()}
    assert sizes == {1: (2, 8_123_456_789), 2: (2, 1_800_000_000)}


def test_a_request_is_never_matched_to_an_episode_by_tmdb_id(client):
    from app.db import session_scope
    from app.models import MediaItem
    from app.services.library import match_requests

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=63424, title="An Episode", media_type="episode", tmdb_id="39513"))
    request = {"is4k": False, "media": {"status": 5, "ratingKey": "999", "mediaType": "movie", "tmdbId": 39513},
               "requestedBy": {"plexUsername": "carol"}}
    missing = match_requests([request])["missing"]
    assert len(missing) == 1 and missing[0]["matched_by_id"] is False and missing[0]["title"] is None
    with session_scope() as db:
        db.add(MediaItem(rating_key=4101, title="Paul", media_type="movie", tmdb_id="39513"))
    assert match_requests([request])["missing"][0]["title"] == "Paul"

# ---- the tracks in a file ----------------------------------------------------


DETAIL_KEYS = {
    "rating_key", "parent_rating_key", "grandparent_rating_key", "section_id", "media_type", "title",
    "full_title", "grandparent_title", "parent_media_index", "media_index", "year", "thumb",
    "grandparent_thumb", "parent_thumb", "art", "duration", "content_rating", "summary", "file_bitrate",
    "file_container", "file_size", "file_path", "versions", "video_codec", "video_resolution",
    "video_bit_depth", "video_dynamic_range", "audio_codec", "audio_channels", "audio_tracks",
    "subtitle_tracks", "imdb_id", "tmdb_id", "tvdb_id",
}


def a_stream(kind, **over):
    base = dict(streamType=kind, codec=None, language=None, languageCode=None, key=None, forced=None)
    return SimpleNamespace(**{**base, **over})


def a_file(streams, **over):
    part = SimpleNamespace(
        file="/media/movies/Paul (2011)/Paul.mkv", size=8_123_456_789, container="mkv", streams=streams,
    )
    return a_media(parts=[part], **over)


def with_tracks(**over):
    streams = [
        a_stream(1, codec="hevc", bitDepth=10, colorTrc="smpte2084", DOVIPresent=None),
        a_stream(2, codec="eac3", channels=6, languageCode="eng", bitrate=768),
        a_stream(2, codec="aac", channels=2, languageCode="spa", bitrate=None),
        a_stream(3, codec="srt", languageCode="eng", key="/library/streams/9001"),
        a_stream(3, codec="pgs", languageCode="jpn", forced=True),
    ]
    return a_film(media=[a_file(streams)], **over)


def test_a_detail_row_has_every_field_the_tautulli_one_writes():
    assert DETAIL_KEYS <= set(library.detail_row(with_tracks()))


def test_the_audio_tracks_come_back_in_order_with_what_is_kept_about_them():
    row = library.detail_row(with_tracks())
    assert json.loads(row["audio_tracks"]) == [
        {"codec": "eac3", "channels": 6, "language": "eng", "bitrate": 768},
        {"codec": "aac", "channels": 2, "language": "spa", "bitrate": None},
    ]


def test_everything_else_plex_says_about_a_track_is_kept_too():
    """Tautulli passes on four things about a track."""
    streams = [
        a_stream(2, codec="eac3", channels=6, languageCode="eng", bitrate=768,
                 audioChannelLayout="5.1(side)", samplingRate=48000, profile="lc",
                 bitDepth=24, default=True, title="Commentary"),
        a_stream(3, codec="subrip", languageCode="eng", hearingImpaired=True, dub=True, default=True,
                 title="English (SDH)", key="/library/streams/9001"),
    ]
    row = library.detail_row(a_film(media=[a_file(streams)]))
    assert json.loads(row["audio_tracks"]) == [{
        "codec": "eac3", "channels": 6, "language": "eng", "bitrate": 768,
        "layout": "5.1(side)", "profile": "lc", "sample_rate": 48000, "bit_depth": 24,
        "default": True, "title": "Commentary",
    }]
    assert json.loads(row["subtitle_tracks"]) == [{
        "codec": "subrip", "language": "eng", "forced": False, "location": "external",
        "sdh": True, "dub": True, "default": True, "title": "English (SDH)",
    }]


def test_what_plex_did_not_say_is_left_out_rather_than_written_down_as_no():
    """Plex leaves these out instead of sending a no, and leaving them out keeps that meaning."""
    row = library.detail_row(with_tracks())
    plain = json.loads(row["subtitle_tracks"])[1]
    assert set(plain) == {"codec", "language", "forced", "location"}
    quiet = json.loads(row["audio_tracks"])[1]
    assert set(quiet) == {"codec", "channels", "language", "bitrate"}


def test_a_subtitle_beside_the_file_is_external_and_one_inside_it_is_not():
    """Plex does not say which it is."""
    row = library.detail_row(with_tracks())
    assert json.loads(row["subtitle_tracks"]) == [
        {"codec": "srt", "language": "eng", "forced": False, "location": "external"},
        {"codec": "pgs", "language": "jpn", "forced": True, "location": "embedded"},
    ]


def test_the_dynamic_range_is_said_the_way_four_years_of_rows_say_it():
    """SDR, HDR10, Dolby Vision and Dolby Vision/HDR10 are Tautulli's words."""
    sdr = a_stream(1, bitDepth=8)
    assert library._range(sdr) == "SDR"
    assert library._range(a_stream(1, colorTrc="smpte2084", bitDepth=10)) == "HDR10"
    assert library._range(a_stream(1, colorTrc="arib-std-b67", bitDepth=10)) == "HLG"
    assert library._range(a_stream(1, DOVIPresent="1", bitDepth=10)) == "Dolby Vision"
    assert library._range(a_stream(1, DOVIPresent="1", colorTrc="smpte2084")) == "Dolby Vision/HDR10"
    assert library._range(None) is None


def test_bt709_is_not_hdr():
    """It is a transfer characteristic like any other and most files carry it."""
    assert library._range(a_stream(1, colorTrc="bt709", bitDepth=8)) == "SDR"


def test_an_item_with_no_file_still_gives_a_row():
    row = library.detail_row(a_film(media=[]))
    assert row["rating_key"] == 4101 and row["title"] == "Paul"
    assert row["audio_tracks"] is None and row["subtitle_tracks"] is None
    assert row["video_dynamic_range"] is None


def test_several_versions_are_counted_and_the_first_is_described():
    row = library.detail_row(a_film(media=[a_file([a_stream(2, codec="eac3", channels=6)]), a_media()]))
    assert row["versions"] == 2
    assert row["file_container"] == "mkv"


class FakeServer:
    """Records what it was asked for, because the point is how many requests."""

    def __init__(self, items):
        self.items = {i.ratingKey: i for i in items}
        self.asked = []

    def fetchItems(self, path):
        self.asked.append(path)
        keys = path.rsplit("/", 1)[-1].split(",")
        return [self.items[int(k)] for k in keys if int(k) in self.items]


def test_the_keys_go_up_in_batches_rather_than_one_at_a_time(monkeypatch):
    """The whole reason for reading these from Plex."""
    items = [with_tracks(ratingKey=k) for k in range(1, 251)]
    fake = FakeServer(items)
    monkeypatch.setattr("app.plex.server.server", lambda: fake)
    rows = library.details([i.ratingKey for i in items])
    assert len(rows) == 250
    assert len(fake.asked) == 3, fake.asked
    assert all(len(path.rsplit("/", 1)[-1].split(",")) <= library.DETAIL_BATCH for path in fake.asked)


def test_a_key_plex_no_longer_knows_gets_an_empty_row(monkeypatch):
    fake = FakeServer([with_tracks(ratingKey=1)])
    monkeypatch.setattr("app.plex.server.server", lambda: fake)
    rows = library.details([1, 2])
    gone = [r for r in rows if r["rating_key"] == 2][0]
    assert set(gone) == {"rating_key"}, "nothing is claimed about it, but it is accounted for"


def test_a_batch_that_fails_does_not_take_the_rest_with_it(monkeypatch):
    class Grumpy(FakeServer):
        def fetchItems(self, path):
            self.asked.append(path)
            if len(self.asked) == 1:
                raise RuntimeError("Plex said no")
            return super().fetchItems(path)

    items = [with_tracks(ratingKey=k) for k in range(1, 151)]
    fake = Grumpy(items)
    monkeypatch.setattr("app.plex.server.server", lambda: fake)
    rows = library.details([i.ratingKey for i in items])
    described = [r for r in rows if "title" in r]
    assert len(described) == 50, "the second batch still arrived"
    assert len(rows) == 150, "and the first batch's keys are accounted for"


def test_the_setting_sends_the_file_details_to_plex_too(client, monkeypatch):
    """The scan knowing which source to use was only half of it."""
    from app import settings_store
    from app.db import session_scope
    from app.models import MediaItem
    from app.plex import server
    from app.services import library_scan

    claim(client)
    settings_store.save({"library_source": "plex"})
    plex, _ = a_server()
    monkeypatch.setattr(server, "server", lambda fresh=False: plex)
    asyncio.run(library_scan.scan(None))

    fake = FakeServer([with_tracks(ratingKey=4101)])
    monkeypatch.setattr(server, "server", lambda fresh=False: fake)

    class NoTautulli:
        async def call(self, cmd, **params):
            raise AssertionError(f"asked Tautulli for {cmd}")

    result = asyncio.run(library_scan.read_details(NoTautulli()))
    assert result["read"] > 0
    with session_scope() as db:
        film = db.get(MediaItem, 4101)
        assert json.loads(film.audio_tracks)[0]["codec"] == "eac3"
        assert json.loads(film.subtitle_tracks)[0]["location"] == "external"
        assert film.video_dynamic_range == "HDR10" and film.video_bit_depth == 10

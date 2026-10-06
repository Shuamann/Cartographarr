"""The library read from Plex instead of from Tautulli.

The rows have to match the Tautulli scan's field for field, because the upsert,
the size history and every list built on media_items read that shape. The two
things Plex adds are the reason to switch: the file path, which the on-disk
check and tidying need, and the external ids, which deep links and request
matching need for titles nobody has played yet.
"""

import asyncio
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
    """A field quietly missing would be a blank on a page rather than an
    error, so the keys are compared rather than trusted."""
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
    """Only films and episodes are files. A show or a season stored as a row
    would count in a library's size and turn up in lists of files."""
    for kind in ("show", "season", "track", "artist", "photo", None):
        assert library.row(a_film(type=kind), 1) is None, kind
    assert library.row(a_film(ratingKey=None), 1) is None


def test_an_item_with_no_media_or_no_parts_is_stored_without_file_details():
    """Kept rather than skipped. The scan's sighting is what counts an item as
    still in the library, so skipping one with no file listed would mark a
    title as gone that Plex still has."""
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
    """plexapi reloads a listed item from the server whenever something read
    from it is empty. A film with no year and no ids is common, and across a
    library that would be thousands of quiet requests. A real plexapi object,
    with a stand-in server that writes down anything asked of it, proves none
    is made. The stand-in fails loudly as well, but that alone would prove
    nothing: reading with getattr and a default swallows the failure."""
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
    """The setting was offered and read by nothing. This is the wire: with Plex
    chosen the scan never asks Tautulli, and what Plex said ends up stored, ids
    and paths included, with the day's library size written down as before."""
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
    """An episode's TMDB id is TMDB's id for the episode, a different number
    space from the film or show a request names. With every episode in the
    library carrying one, a film whose key changed could otherwise be matched
    to an unrelated episode that happens to share the number."""
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

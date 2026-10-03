"""The library list caches what each file says about itself. It must not lie.

Half the cost of that page was working out the same answers again for thirty
thousand files that had not changed. Caching them is only safe if a file that
*has* changed stops matching, so these are all about that: tidy it, rescan it,
move it, rename its store, and the page has to show the new answer rather than
yesterday's.
"""

import json

from app.db import session_scope
from app.models import Library, LibraryStore, MediaItem
from app.services import library


def add(db, rating_key: int, **over):
    base = dict(
        rating_key=rating_key,
        title=f"Film {rating_key}",
        full_title=f"Film {rating_key}",
        media_type="movie",
        section_id=1,
        duration=3_600_000,
        file_size=4_000_000_000,
        file_path=f"/movies/Film {rating_key}/f.mkv",
        file_container="mkv",
        file_bitrate=9000,
        video_resolution="1080p",
        audio_tracks=json.dumps([{"codec": "aac", "channels": 2, "language": "eng"}]),
        subtitle_tracks=json.dumps([]),
    )
    db.add(MediaItem(**{**base, **over}))


def one(db, **kwargs):
    """The browse row for our single film."""
    library.forget_rows()
    rows = library.browse(db, days=90, **kwargs)["items"]
    return next(r for r in rows if r["rating_key"] == 1)


def live(db, **kwargs):
    """The same, without clearing the cache first: what a second visit sees."""
    rows = library.browse(db, days=90, **kwargs)["items"]
    return next(r for r in rows if r["rating_key"] == 1)


def test_a_second_visit_agrees_with_the_first(client):
    with session_scope() as db:
        db.add(Library(section_id=1, name="Films"))
        add(db, 1)

    with session_scope() as db:
        first = one(db)
        again = live(db)
    assert first == again


# ---- the cases that must invalidate -----------------------------------------


def test_a_tidied_file_shows_its_new_size(client):
    """A tidy writes a smaller file and clears file_checked_at. Both change the
    key, so neither alone has to be relied on."""
    with session_scope() as db:
        db.add(Library(section_id=1, name="Films"))
        add(db, 1)

    with session_scope() as db:
        before = one(db)
    assert before["file_size"] == 4_000_000_000
    assert before["gb_per_hour"] == 4.0

    with session_scope() as db:
        db.get(MediaItem, 1).file_size = 2_000_000_000
        db.get(MediaItem, 1).file_checked_at = None

    with session_scope() as db:
        after = live(db)
    assert after["file_size"] == 2_000_000_000
    assert after["gb_per_hour"] == 2.0


def test_a_renamed_file_shows_its_new_path(client):
    """Tidying an avi leaves an mkv, and the store comes from the path."""
    with session_scope() as db:
        db.add(Library(section_id=1, name="Films"))
        add(db, 1, file_path="/movies/Film 1/f.avi", file_container="avi")

    with session_scope() as db:
        assert one(db)["file_container"] == "avi"

    with session_scope() as db:
        item = db.get(MediaItem, 1)
        item.file_path = "/archive/Film 1/f.mkv"
        item.file_container = "mkv"
        item.file_checked_at = None

    with session_scope() as db:
        after = live(db)
    assert after["store"] == "/archive"


def test_a_rescan_that_changes_the_tracks_shows_the_new_languages(client):
    """What a rescan does: new tracks, new file_checked_at."""
    import datetime

    with session_scope() as db:
        db.add(Library(section_id=1, name="Films"))
        add(db, 1, file_checked_at=datetime.datetime(2026, 1, 1))

    with session_scope() as db:
        assert one(db)["languages"] == ["eng"]

    with session_scope() as db:
        item = db.get(MediaItem, 1)
        item.audio_tracks = json.dumps([
            {"codec": "aac", "channels": 2, "language": "eng"},
            {"codec": "ac3", "channels": 6, "language": "jpn"},
        ])
        item.file_checked_at = datetime.datetime(2026, 6, 1)

    with session_scope() as db:
        assert live(db)["languages"] == ["eng", "jpn"]


def test_renaming_a_store_renames_it_everywhere(client):
    """The store label is not on the file, so the file's own key cannot see it
    change. The whole cache is stamped with the labels instead."""
    with session_scope() as db:
        db.add(Library(section_id=1, name="Films"))
        add(db, 1)

    with session_scope() as db:
        assert one(db)["store"] == "/movies"

    with session_scope() as db:
        db.add(LibraryStore(prefix="/movies", label="The array"))

    with session_scope() as db:
        assert live(db)["store"] == "The array"


def test_changing_how_much_of_a_path_names_a_store_is_seen(client):
    """library_store_depth is a setting, and the same question of a different
    setting is a different answer."""
    from app.settings_store import trial

    with session_scope() as db:
        db.add(Library(section_id=1, name="Films"))
        add(db, 1, file_path="/mnt/user/movies/Film 1/f.mkv")

    with session_scope() as db:
        assert one(db)["store"] == "/mnt"

    with trial({"library_store_depth": 3}), session_scope() as db:
        assert live(db)["store"] == "/mnt/user/movies"


# ---- and the thing it exists for ---------------------------------------------


def test_plays_are_never_cached(client):
    """They change without the file changing, so they are read every time."""
    with session_scope() as db:
        db.add(Library(section_id=1, name="Films"))
        add(db, 1)

    with session_scope() as db:
        row = one(db)
    assert row["plays"] == 0
    assert "unwatched" in row["marks"]

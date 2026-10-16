"""Browsing by where a file lives, and seeing past the first page.

Two things the browse list could not do. It had no way to ask "what is still
on the disk that is full", which is the question somebody moving things off an
array actually has, even though every row already knew which store it sat on.
And it answered with the first sixty rows and said so, with no way to ask for
the rest, which on a library of four thousand films is most of it hidden.

Each test here was watched failing against the mistake it names.
"""

from __future__ import annotations

from app.db import session_scope
from app.services import library

GB = 1_000_000_000


def film(key, title, path, size=2 * GB):
    from app.models import MediaItem

    return MediaItem(
        rating_key=key, media_type="movie", title=title, full_title=title, section_id=1,
        file_path=path, file_size=size, file_bitrate=4000, duration=7_200_000,
        video_resolution="1080p",
    )


def put(rows):
    with session_scope() as db:
        for row in rows:
            db.add(row)


def browse(**kw):
    with session_scope() as db:
        return library.browse(db, 90, media_type="movie", **kw)


def library_of_two_disks():
    put([
        film(1, "One", "/array/movies/One.mkv"),
        film(2, "Two", "/array/movies/Two.mkv"),
        film(3, "Three", "/array/kids/Three.mkv"),
        film(4, "Four", "/nas/movies/Four.mkv"),
    ])


def test_every_location_is_offered(client):
    library_of_two_disks()
    assert len(browse()["stores"]) >= 2


def test_ticking_one_location_keeps_only_what_is_there(client):
    library_of_two_disks()
    everything = browse()
    one = everything["stores"][0]
    narrowed = browse(stores=[one])
    assert narrowed["total"] < everything["total"]
    assert {row["store"] for row in narrowed["items"]} == {one}


def test_narrowing_does_not_remove_the_other_options(client):
    """Tick one location and the others vanishing is a filter nobody can use
    twice. The list of places is worked out before any row is dropped for
    being in the wrong one."""
    library_of_two_disks()
    everything = browse()
    narrowed = browse(stores=[everything["stores"][0]])
    assert narrowed["stores"] == everything["stores"]


def test_two_locations_at_once(client):
    """The question is usually what is still on these two disks, which a
    dropdown cannot ask."""
    library_of_two_disks()
    both = browse(stores=browse()["stores"][:2])
    apart = sum(browse(stores=[s])["total"] for s in browse()["stores"][:2])
    assert both["total"] == apart


def test_ticking_nothing_is_the_same_as_ticking_everything(client):
    library_of_two_disks()
    assert browse(stores=[])["total"] == browse()["total"]


def test_an_empty_name_is_not_a_location(client):
    """A blank slipping into the list would match nothing and quietly empty
    the page."""
    library_of_two_disks()
    assert browse(stores=["", None])["total"] == browse()["total"]


def test_a_page_can_be_asked_for_past_the_first(client):
    library_of_two_disks()
    first = browse(limit=2)
    second = browse(limit=2, offset=2)
    assert first["offset"] == 0 and second["offset"] == 2
    assert {r["rating_key"] for r in first["items"]}.isdisjoint({r["rating_key"] for r in second["items"]})


def test_the_total_is_everything_rather_than_the_page(client):
    """Otherwise nothing can say there is more to ask for."""
    library_of_two_disks()
    assert browse(limit=1)["total"] == 4


def test_asking_past_the_end_gives_nothing_rather_than_the_last_page(client):
    """A slice with an offset past the end has to be empty. Falling back to
    the start would loop forever as somebody pressed for more."""
    library_of_two_disks()
    assert browse(limit=2, offset=99)["items"] == []


def episode(key, show, title, path):
    from app.models import MediaItem

    return MediaItem(
        rating_key=key, media_type="episode", title=title, full_title=title, section_id=2,
        grandparent_rating_key=show, grandparent_title=f"Show {show}",
        parent_media_index=1, media_index=key, file_path=path, file_size=GB, duration=2_700_000,
    )


def tv():
    put([
        episode(11, 100, "A", "/array/tv/Show 100/A.mkv"),
        episode(12, 100, "B", "/array/tv/Show 100/B.mkv"),
        episode(21, 200, "C", "/nas/tv/Show 200/C.mkv"),
        episode(31, 300, "D", "/array/tv/Show 300/D.mkv"),
        episode(32, 300, "E", "/nas/tv/Show 300/E.mkv"),
    ])


def shows(**kw):
    with session_scope() as db:
        return library.shows(db, 90, **kw)


def test_the_shows_list_offers_the_places_shows_live(client):
    """Browsing television, the ticks were whatever the last film list had
    offered, because this endpoint had never heard of a store. The television
    archives could not be reached at all: the only places on offer were ones
    films live in."""
    tv()
    # A store is named by the first part of its path, as deep as the setting
    # says, so these are the two disks rather than the two folders.
    assert shows()["stores"] == ["/array", "/nas"]


def test_a_show_is_listed_if_any_of_it_is_in_the_ticked_place(client):
    """The point of ticking is to find what to move off a disk, and a show
    with one episode left on it is still something on it."""
    tv()
    assert {s["rating_key"] for s in shows(stores=["/nas"])["items"]} == {200, 300}


def test_a_show_knows_the_places_it_is_spread_across(client):
    tv()
    spread = next(s for s in shows()["items"] if s["rating_key"] == 300)
    assert spread["stores"] == ["/array", "/nas"]


def test_narrowing_shows_keeps_the_other_places_on_offer(client):
    tv()
    assert shows(stores=["/nas"])["stores"] == shows()["stores"]


def test_every_show_carries_an_episode_to_look_it_up_by(client):
    """A show mostly has no row of its own, so anything that finds it in
    Radarr or Sonarr goes through an episode, which resolves to the series."""
    tv()
    assert all(s["episode_key"] is not None for s in shows()["items"])

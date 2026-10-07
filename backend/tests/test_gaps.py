"""What a library is missing, and what it is holding twice.

Both questions are easy to answer wrongly in a way that looks fine. Each test
here was watched failing against the mistake it names.
"""

from __future__ import annotations

def episode(key: int, show: int, season: int, number: int, section: int = 1, title: str = "A Show"):
    from app.models import MediaItem

    return MediaItem(
        rating_key=key,
        grandparent_rating_key=show,
        grandparent_title=title,
        parent_rating_key=show * 100 + season,
        parent_media_index=season,
        media_index=number,
        media_type="episode",
        section_id=section,
        title=f"Episode {number}",
    )


def film(key: int, title: str, versions: int | None = None, section: int = 1, **ids):
    from app.models import MediaItem

    return MediaItem(
        rating_key=key, title=title, full_title=title, media_type="movie",
        section_id=section, versions=versions, year=2020, **ids,
    )


def put(items):
    """Write these rows, then answer in a session of their own, which is how
    the service is really called."""
    from app.db import session_scope

    with session_scope() as db:
        for item in items:
            db.add(item)


def holes(**kw):
    from app.db import session_scope
    from app.services import gaps

    with session_scope() as db:
        return gaps.holes(db, **kw)


def copies(**kw):
    from app.db import session_scope
    from app.services import gaps

    with session_scope() as db:
        return gaps.copies(db, **kw)


def test_a_hole_in_the_middle_of_a_season_is_found(client):
    put([episode(i, 10, 1, n) for i, n in enumerate([1, 2, 3, 5, 6], start=1)])
    found = holes()
    assert found["episodes_missing"] == 1
    assert found["seasons"][0]["missing"] == [4]
    assert found["seasons"][0]["season"] == 1
    assert found["seasons"][0]["have"] == 5


def test_a_season_part_way_through_airing_is_not_missing_the_rest(client):
    """The mistake this exists for. Comparing against a season's expected
    length, or against any number other than the last episode present, reports
    five missing episodes every week of every running season, which is noise
    on a scale that makes the whole list worthless."""
    put([episode(i, 10, 1, n) for i, n in enumerate([1, 2, 3, 4, 5], start=1)])
    found = holes()
    assert found["seasons"] == []
    assert found["episodes_missing"] == 0


def test_specials_are_left_alone(client):
    """Season zero is numbered however somebody felt. Episodes 1, 7 and 12 of
    it are not nine missing specials."""
    put([episode(i, 10, 0, n) for i, n in enumerate([1, 7, 12], start=1)])
    assert holes()["seasons"] == []


def test_double_episodes_are_not_reported_as_half_a_season_missing(client):
    """Plex files S01E01-E02 under index 1, so a complete season reads as
    every second episode gone. Measured on a real library: eleven seasons and
    187 of the apparently missing episodes were exactly this.
    """
    put([episode(i, 10, 1, n) for i, n in enumerate([1, 3, 5, 7, 9, 11], start=1)])
    found = holes()
    assert found["seasons"] == []
    assert found["double_episode_seasons"] == 1
    assert found["double_episode_holes"] == 5


def test_a_season_with_both_shapes_is_still_reported(client):
    """Alternating is only an excuse when it is the whole story. Two episodes
    gone back to back is a real hole whatever the rest of the season looks
    like, and swallowing it would hide the thing the list is for."""
    put([episode(i, 10, 1, n) for i, n in enumerate([1, 3, 5, 7, 11], start=1)])
    found = holes()
    assert found["seasons"], "a run of three is not a double episode"
    assert found["seasons"][0]["missing"] == [2, 4, 6, 8, 9, 10]
    assert found["double_episode_seasons"] == 0


def test_each_season_is_judged_on_its_own(client):
    put([episode(i, 10, 1, n) for i, n in enumerate([1, 2, 4], start=1)])
    put([episode(i, 10, 2, n) for i, n in enumerate([1, 2, 3], start=20)])
    found = holes()
    assert len(found["seasons"]) == 1
    assert found["seasons"][0]["season"] == 1


def test_two_shows_are_not_one_season(client):
    """Grouping by season number alone would merge every show's first season
    into one, and then almost nothing would be missing from anything."""
    put([episode(i, 10, 1, n, title="One") for i, n in enumerate([1, 3], start=1)])
    put([episode(i, 11, 1, n, title="Two") for i, n in enumerate([2], start=20)])
    found = holes()
    assert found["shows"] == 1
    assert found["seasons"][0]["missing"] == [2]


def test_the_emptiest_season_is_first(client):
    put([episode(i, 10, 1, n, title="One") for i, n in enumerate([1, 3], start=1)])
    put([episode(i, 11, 1, n, title="Two") for i, n in enumerate([1, 5], start=20)])
    found = holes()
    assert [len(s["missing"]) for s in found["seasons"]] == [3, 1]


def test_one_library_can_be_asked_about_on_its_own(client):
    put([episode(i, 10, 1, n, section=1) for i, n in enumerate([1, 3], start=1)])
    put([episode(i, 11, 1, n, section=2) for i, n in enumerate([1, 4], start=20)])
    assert holes(section_id=2)["episodes_missing"] == 2
    assert holes()["episodes_missing"] == 3


def test_an_item_with_several_files_is_found(client):
    put([film(1, "One", versions=3), film(2, "Two", versions=1), film(3, "Three", versions=None)])
    found = copies(sizes=False)
    assert [row["rating_key"] for row in found["multi"]] == [1]
    assert found["extra_files"] == 2


def test_room_to_be_had_is_everything_but_the_best_copy(client, monkeypatch):
    """Not the sum of the files. Somebody deduplicating keeps one, so the
    figure that means anything is what the rest take. Summing all three would
    promise back room that holds the copy being kept."""
    put([film(1, "One", versions=3)])
    monkeypatch.setattr(
        "app.plex.library.versions_of",
        lambda keys: {1: [{"size": 10}, {"size": 4}, {"size": 3}]},
    )
    found = copies()
    assert found["multi"][0]["extra_bytes"] == 7
    assert found["extra_bytes"] == 7


def test_a_size_nobody_knows_is_not_a_size_of_zero(client, monkeypatch):
    """An optimised version reports no size. Zero there reads as "nothing to
    gain from this one", which is an answer, and the truth is that nobody
    knows."""
    put([film(1, "One", versions=2)])
    monkeypatch.setattr(
        "app.plex.library.versions_of",
        lambda keys: {1: [{"size": None}, {"size": None}]},
    )
    found = copies()
    assert found["multi"][0]["extra_bytes"] is None
    assert found["sizes_partial"] == 1


def test_a_list_still_comes_back_when_plex_will_not_answer(client, monkeypatch):
    """A list without sizes beats no list and an error box."""
    def no(keys):
        raise RuntimeError("no server")

    put([film(1, "One", versions=2)])
    monkeypatch.setattr("app.plex.library.versions_of", no)
    found = copies()
    assert len(found["multi"]) == 1
    assert found["extra_bytes"] is None


def test_two_items_claiming_to_be_one_film_are_found(client):
    put([film(1, "One", tmdb_id="55"), film(2, "One again", tmdb_id="55")])
    found = copies(sizes=False)
    assert len(found["same_id"]) == 1
    assert sorted(i["rating_key"] for i in found["same_id"][0]["items"]) == [1, 2]


def test_a_pair_sharing_every_id_is_reported_once(client):
    """A film matched twice shares all three ids, and reporting it under each
    would be reporting the ids rather than the films."""
    put([
        film(1, "One", imdb_id="tt1", tmdb_id="55", tvdb_id="9"),
        film(2, "One", imdb_id="tt1", tmdb_id="55", tvdb_id="9"),
    ])
    assert len(copies(sizes=False)["same_id"]) == 1


def test_the_same_film_in_two_libraries_is_not_a_duplicate(client):
    """A 4K library beside an HD one holds the same films on purpose."""
    put([film(1, "One", tmdb_id="55", section=1), film(2, "One", tmdb_id="55", section=2)])
    assert copies(sizes=False)["same_id"] == []


def test_an_item_with_no_external_id_is_not_matched_to_another(client):
    """Empty is not a value. Grouping on it would put every unmatched film in
    the library into one enormous duplicate."""
    put([film(1, "One", tmdb_id=""), film(2, "Two", tmdb_id=""), film(3, "Three", tmdb_id=None)])
    assert copies(sizes=False)["same_id"] == []


def test_a_season_says_how_many_of_its_holes_are_the_double_episode_shape(client):
    """A season of double episodes with one real gap in it fails the whole
    season test and lands in the list claiming forty missing files, most of
    which are the second half of an episode nobody is missing. The row carries
    the count so it can say so, rather than the list lying or dropping it."""
    put([episode(i, 10, 1, n) for i, n in enumerate([1, 3, 5, 7, 11], start=1)])
    season = holes()["seasons"][0]
    assert season["missing"] == [2, 4, 6, 8, 9, 10]
    assert season["paired"] == 3


def test_the_most_room_to_be_had_comes_first(client, monkeypatch):
    """Not the most copies. Six copies of a clip is not where somebody looking
    for room starts, and sorting on the count puts it at the top."""
    put([film(1, "Small", versions=6), film(2, "Big", versions=2)])
    monkeypatch.setattr(
        "app.plex.library.versions_of",
        lambda keys: {1: [{"size": 2}] * 6, 2: [{"size": 900}, {"size": 800}]},
    )
    assert [row["title"] for row in copies()["multi"]] == ["Big", "Small"]


def test_a_row_carries_the_episode_name_apart_from_the_show(client):
    """The row that draws these splits a title into its show and its episode.
    Handed the full title as the episode's own name, it prints the show
    twice."""
    from app.db import session_scope
    from app.models import MediaItem

    with session_scope() as db:
        db.add(MediaItem(
            rating_key=1, media_type="episode", versions=2, section_id=1,
            title="Future Dib", full_title="Invader ZIM - Future Dib",
            grandparent_title="Invader ZIM", parent_media_index=1, media_index=24,
        ))
    row = copies(sizes=False)["multi"][0]
    assert row["title"] == "Future Dib"
    assert row["full_title"] == "Invader ZIM - Future Dib"

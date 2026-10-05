"""Television browsed as show, season, episode.

The scan stores films and episodes and nothing between: a show and a season
have no file and take up no room, so there is no row for either. But every
episode carries the keys and the numbers that say where it belongs, so both
levels are a GROUP BY rather than something to go and fetch.
"""

import time

from tests.test_auth import claim


def seed():
    from app.db import session_scope
    from app.models import History, Library, MediaItem

    now = int(time.time())
    with session_scope() as db:
        db.add(Library(section_id=2, name="TV"))
        # Two seasons of one show, one season of another, and a film, which
        # must stay out of all of it.
        episodes = [
            (101, 900, 1, 1, "Pilot"),
            (102, 900, 1, 2, "Second"),
            (103, 900, 2, 1, "Return"),
            (201, 950, 1, 1, "Other show"),
        ]
        for key, show, season, number, title in episodes:
            db.add(MediaItem(
                rating_key=key, media_type="episode", section_id=2, title=title,
                grandparent_rating_key=show, grandparent_title="Show A" if show == 900 else "Show B",
                parent_media_index=season, media_index=number,
                file_size=1_000_000_000, duration=1_800_000, year=2020,
            ))
        db.add(MediaItem(rating_key=301, media_type="movie", section_id=1, title="A Film",
                         file_size=8_000_000_000, duration=3_600_000))
        # One play, against an episode, which is where plays are recorded.
        db.add(History(row_id=1, user_id=1, rating_key=101, started=now - 3600, machine_id="tv"))


def test_shows_are_built_from_their_episodes(client):
    claim(client)
    seed()
    r = client.get("/api/library/shows").json()
    by_name = {s["title"]: s for s in r["items"]}
    assert set(by_name) == {"Show A", "Show B"}, "a film is not a show"
    assert by_name["Show A"]["seasons"] == 2
    assert by_name["Show A"]["episodes"] == 3
    assert by_name["Show A"]["file_size"] == 3_000_000_000
    assert by_name["Show A"]["library"] == "TV"
    # A show's plays are its episodes' plays.
    assert by_name["Show A"]["plays"] == 1 and by_name["Show B"]["plays"] == 0
    # Alphabetical, because somebody looking for a show knows its name.
    assert [s["title"] for s in r["items"]] == ["Show A", "Show B"]


def test_one_show_lists_its_seasons(client):
    claim(client)
    seed()
    r = client.get("/api/library/shows/900").json()
    assert r["title"] == "Show A"
    assert [s["season"] for s in r["seasons"]] == [1, 2]
    assert r["seasons"][0]["episodes"] == 2 and r["seasons"][1]["episodes"] == 1
    assert r["seasons"][0]["plays"] == 1


def test_a_show_nobody_has_is_empty_rather_than_an_error(client):
    claim(client)
    seed()
    r = client.get("/api/library/shows/4242").json()
    assert r["seasons"] == [] and r["title"] is None


def test_browse_narrows_to_a_show_and_to_a_season(client):
    claim(client)
    seed()
    everything = client.get("/api/library/browse?media_type=episode").json()
    assert everything["total"] == 4

    show = client.get("/api/library/browse?media_type=episode&show=900").json()
    assert show["total"] == 3

    season = client.get("/api/library/browse?media_type=episode&show=900&season=1").json()
    assert season["total"] == 2
    assert {i["rating_key"] for i in season["items"]} == {101, 102}


def test_the_show_list_can_be_searched_and_narrowed_to_a_library(client):
    claim(client)
    seed()
    assert [s["title"] for s in client.get("/api/library/shows?search=show+b").json()["items"]] == ["Show B"]
    assert len(client.get("/api/library/shows?section_id=2").json()["items"]) == 2
    assert client.get("/api/library/shows?section_id=1").json()["items"] == []


def test_the_show_lists_are_admin_only(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "all")
    assert client.get("/api/library/shows").status_code == 403
    assert client.get("/api/library/shows/900").status_code == 403

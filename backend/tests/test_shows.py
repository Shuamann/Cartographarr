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


def requests_from(monkeypatch, rows):
    from app.integrations.seerr import seerr

    monkeypatch.setattr(type(seerr), "configured", lambda self: True)

    async def all_requests(limit=2000):
        return rows

    monkeypatch.setattr(seerr, "all_requests", all_requests)


def a_request(key, who="shua", tmdb=None):
    return {
        "is4k": False,
        "media": {"status": 5, "ratingKey": str(key), "mediaType": "movie",
                  "mediaAddedAt": "2024-01-01T00:00:00Z", **({"tmdbId": tmdb} if tmdb else {})},
        "requestedBy": {"plexUsername": who},
    }


def test_requests_with_no_file_are_their_own_list(client, monkeypatch):
    """Seerr saying a request arrived, and the library having no such file, is
    a different problem from nobody having watched it. Side by side they read
    as the same thing, and the second is the more actionable one."""
    from app.db import session_scope
    from app.models import MediaItem

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=501, media_type="movie", title="On the disk",
                         file_size=4_000_000_000, section_id=1))

    requests_from(monkeypatch, [a_request(501), a_request(45848)])
    r = client.get("/api/library/requests?fresh=true").json()

    assert [x["title"] for x in r["requests"]] == ["On the disk"]
    assert r["requests"][0]["in_library"] is True and r["requests"][0]["file_size"] == 4_000_000_000
    assert [x["rating_key"] for x in r["missing"]] == [45848]
    assert r["missing"][0]["in_library"] is False and r["missing"][0]["title"] is None


def test_two_people_asking_for_one_film_is_one_row(client, monkeypatch):
    from app.db import session_scope
    from app.models import MediaItem

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=502, media_type="movie", title="Wanted twice",
                         file_size=1_000_000_000, section_id=1))

    requests_from(monkeypatch, [a_request(502, "alpha"), a_request(502, "beta"), a_request(502, "alpha")])
    r = client.get("/api/library/requests?fresh=true").json()
    assert len(r["requests"]) == 1
    row = r["requests"][0]
    assert row["requested_by"] == "alpha"
    assert row["also_requested_by"] == ["beta"], "and not the same person twice"


def test_a_title_whose_key_changed_is_still_named(client, monkeypatch):
    """Plex can give the same film a new key. Seerr remembers the old one, and
    the id finds it anyway, so the row reads as a film rather than a number."""
    from app.db import session_scope
    from app.models import MediaItem

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=999, media_type="movie", title="Renumbered",
                         tmdb_id="12345", file_size=2_000_000_000, section_id=1))

    requests_from(monkeypatch, [a_request(45848, tmdb=12345)])
    r = client.get("/api/library/requests?fresh=true").json()
    # Still in the second list, because the library has nothing under that key,
    # but it has a name now instead of "Item 45848".
    assert r["requests"] == []
    assert r["missing"][0]["title"] == "Renumbered"
    assert r["missing"][0]["matched_by_id"] is True


def test_a_request_carries_somewhere_to_go(client, monkeypatch):
    """A row named a film and offered nothing to do about it. A missing id
    means no button rather than one that goes nowhere."""
    from app.db import session_scope
    from app.models import MediaItem

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=601, media_type="movie", title="Has every id",
                         imdb_id="tt0111161", tmdb_id="278", file_size=5_000_000_000, section_id=1))

    requests_from(monkeypatch, [a_request(601, tmdb=278), a_request(70001, tmdb=999)])
    r = client.get("/api/library/requests?fresh=true").json()

    here = r["requests"][0]["links"]
    assert here["imdb"].endswith("/tt0111161/")
    assert here["tmdb"].endswith("/movie/278")
    assert "trakt" in here

    # Nothing in the library: no Plex link, because a key Plex does not know
    # lands on an error, but the id still opens the outside world.
    gone = r["missing"][0]["links"]
    assert "plex" not in gone and "imdb" not in gone
    assert gone["tmdb"].endswith("/movie/999")

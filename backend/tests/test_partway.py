"""What somebody started and did not finish.

Not a Plex question, which was worth checking before building anything: the
history already carries how far into a thing each play got, and twenty nine
people on the server this was written against have something part finished.
"""

import time

from tests.test_auth import claim

DAY = 86400


def play(db, row_id, user, key, percent, days_ago, show=None, show_title=None, title="A Film"):
    from app.models import History

    started = int(time.time()) - days_ago * DAY
    db.add(History(
        row_id=row_id, user_id=user, rating_key=key, percent_complete=percent,
        started=started, stopped=started + 600, full_title=title,
        grandparent_rating_key=show, grandparent_title=show_title,
        media_type="episode" if show else "movie",
    ))


def partway_for(user=1):
    from app.db import session_scope
    from app.services import partway

    with session_scope() as db:
        return partway.for_user(db, user)


def test_something_half_watched_is_listed(client):
    from app.db import session_scope

    claim(client)
    with session_scope() as db:
        play(db, 1, 1, 100, 42, 2, title="A Film")
    rows = partway_for()
    assert [(r["title"], r["percent"]) for r in rows] == [("A Film", 42)]


def test_barely_started_and_all_but_finished_are_both_left_out(client):
    """A play that got two per cent in is somebody opening the wrong thing.
    Credits and a stinger are the difference between 85 and 100, and calling
    those unfinished would put every watched episode on the list."""
    from app.db import session_scope

    claim(client)
    with session_scope() as db:
        play(db, 1, 1, 100, 2, 2, title="Opened by mistake")
        play(db, 2, 1, 101, 97, 2, title="Watched")
        play(db, 3, 1, 102, 50, 2, title="Half watched")
    assert [r["title"] for r in partway_for()] == ["Half watched"]


def test_going_back_to_the_start_does_not_unwatch_it(client):
    """The furthest they ever got, not the most recent attempt."""
    from app.db import session_scope

    claim(client)
    with session_scope() as db:
        play(db, 1, 1, 100, 90, 10, title="Finished once")
        play(db, 2, 1, 100, 4, 1, title="Finished once")
    assert partway_for() == []


def test_a_show_is_one_row_however_many_episodes_are_part_watched(client):
    """Somebody four episodes into a season is partway through one programme.
    Listing it four times is a list about the data rather than about them."""
    from app.db import session_scope

    claim(client)
    with session_scope() as db:
        play(db, 1, 1, 200, 30, 5, show=900, show_title="A Show", title="A Show - One")
        play(db, 2, 1, 201, 60, 3, show=900, show_title="A Show", title="A Show - Two")
        play(db, 3, 1, 202, 45, 1, show=900, show_title="A Show", title="A Show - Three")
    rows = partway_for()
    assert len(rows) == 1
    assert rows[0]["title"] == "A Show"
    # The one they are actually on, which is the most recent.
    assert rows[0]["what"] == "A Show - Three" and rows[0]["percent"] == 45


def test_two_different_shows_are_two_rows(client):
    from app.db import session_scope

    claim(client)
    with session_scope() as db:
        play(db, 1, 1, 200, 30, 5, show=900, show_title="One Show", title="One Show - A")
        play(db, 2, 1, 300, 30, 4, show=901, show_title="Another Show", title="Another Show - A")
    assert {r["title"] for r in partway_for()} == {"One Show", "Another Show"}


def test_something_abandoned_a_year_ago_is_not_partway_through_anything(client):
    from app.db import session_scope

    claim(client)
    with session_scope() as db:
        play(db, 1, 1, 100, 40, 400, title="Long gone")
    assert partway_for() == []


def test_it_is_only_about_the_person_asked_for(client):
    from app.db import session_scope

    claim(client)
    with session_scope() as db:
        play(db, 1, 1, 100, 40, 2, title="Mine")
        play(db, 2, 2, 101, 40, 2, title="Theirs")
    assert [r["title"] for r in partway_for(1)] == ["Mine"]
    assert [r["title"] for r in partway_for(2)] == ["Theirs"]


def test_a_row_carries_what_it_needs_to_be_drawn_like_any_other_title(client):
    """The show, the episode's number and own name, and the show's year rather
    than the year the episode aired: the row says which show before it is read."""
    from app.db import session_scope
    from app.models import History, MediaItem

    claim(client)
    started = int(time.time()) - 2 * DAY
    with session_scope() as db:
        db.add(MediaItem(rating_key=500, title="Quiet Harbour", media_type="show", year=2019))
        db.add(History(
            row_id=1, user_id=1, rating_key=503, percent_complete=40, started=started, stopped=started + 600,
            full_title="Quiet Harbour - The Lamp", title="The Lamp", grandparent_rating_key=500,
            grandparent_title="Quiet Harbour", parent_media_index=2, media_index=3, year=2024,
            media_type="episode",
        ))
        play(db, 2, 1, 600, 30, 1, title="A Film")
    with session_scope() as db:
        db.query(History).filter(History.row_id == 2).update({"year": 2011})
    rows = {r["title"]: r for r in partway_for()}
    episode = rows["Quiet Harbour"]
    assert (episode["episode_title"], episode["season"], episode["episode"], episode["year"]) == ("The Lamp", 2, 3, 2019)
    film = rows["A Film"]
    assert (film["episode_title"], film["season"], film["year"]) == (None, None, 2011)


def test_most_watched_carries_a_year_for_films_and_shows(client):
    """A film's year from its plays; a show's from the library, never from an
    episode, whose year is the year it aired."""
    from app.db import session_scope
    from app.models import History, MediaItem, User

    claim(client)
    started = int(time.time()) - DAY
    with session_scope() as db:
        db.add(User(user_id=1, username="alpha"))
        db.add(MediaItem(rating_key=500, title="Quiet Harbour", media_type="show", year=2019))
        db.add(History(row_id=1, user_id=1, rating_key=503, grandparent_rating_key=500, started=started,
                       full_title="Quiet Harbour - The Lamp", media_type="episode", year=2024, percent_complete=100))
        db.add(History(row_id=2, user_id=1, rating_key=600, started=started, full_title="A Film",
                       media_type="movie", year=2011, percent_complete=100))
    top = {m["title"]: m for m in client.get("/api/users/1").json()["top_media"]}
    assert top["Quiet Harbour"]["year"] == 2019
    assert top["A Film"]["year"] == 2011

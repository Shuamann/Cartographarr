"""A person's month or year, added up from the history they can already read."""

from datetime import datetime

from tests.test_auth import claim

# A Wednesday evening, so the weekday and hour are known.
NOW = int(datetime(2026, 10, 7, 21, 0).timestamp())
DAY = 86400


def add(db, row_id, *, user=1, key, started, seconds, show=None, show_title=None, title="A Film", player="TV"):
    from app.models import History

    db.add(History(
        row_id=row_id, user_id=user, rating_key=key, started=started, stopped=started + seconds,
        play_duration=seconds, full_title=title if not show else f"{show_title} - {title}",
        grandparent_rating_key=show, grandparent_title=show_title, player=player,
        media_type="episode" if show else "movie", percent_complete=100,
    ))


def seed():
    from app.db import session_scope
    from app.models import MediaItem, MediaTag

    with session_scope() as db:
        db.add(MediaItem(rating_key=500, title="Quiet Harbour", media_type="show", year=2019))
        db.add(MediaItem(rating_key=600, title="Paper Moons", media_type="movie", year=2015))
        db.add(MediaTag(rating_key=500, kind="genre", value="Drama"))
        db.add(MediaTag(rating_key=600, kind="genre", value="Comedy"))
        # Three episodes of a show first played this month: one title, started here.
        for i, key in enumerate((501, 502, 503)):
            add(db, 1 + i, key=key, started=NOW - 2 * DAY - 3600, seconds=2700, show=500,
                show_title="Quiet Harbour", title=f"Part {i + 1}")
        # A film, on a phone.
        add(db, 10, key=600, started=NOW - 5 * DAY, seconds=5400, title="Paper Moons", player="Phone")
        # A show they began long ago and came back to: watched, not started.
        add(db, 20, key=701, started=NOW - 200 * DAY, seconds=1800, show=700, show_title="Old Friend")
        add(db, 21, key=702, started=NOW - 3 * DAY, seconds=1800, show=700, show_title="Old Friend")
        # The month before, to compare against.
        add(db, 30, key=600, started=NOW - 40 * DAY, seconds=3600, title="Paper Moons")
        # Somebody else entirely.
        add(db, 40, user=2, key=600, started=NOW - DAY, seconds=9000, title="Paper Moons")


def recap(days=30):
    from app.db import session_scope
    from app.services import recap as service

    with session_scope() as db:
        return service.for_user(db, 1, days, now=NOW)


def test_a_month_adds_up(client):
    claim(client)
    seed()
    r = recap()
    assert r["plays"] == 5
    assert r["hours"] == round((3 * 2700 + 5400 + 1800) / 3600, 1)
    assert r["hours_before"] == 1.0
    assert r["devices"] == 2
    assert r["days_watched"] == 3


def test_a_show_is_one_title_with_its_year(client):
    claim(client)
    seed()
    top = recap()["top"]
    assert [(t["title"], t["media_type"], t["year"]) for t in top[:2]] == [
        ("Quiet Harbour", "show", 2019),
        ("Paper Moons", "movie", 2015),
    ]
    assert top[0]["plays"] == 3


def test_genres_are_by_time_and_through_the_show(client):
    claim(client)
    seed()
    assert [g["genre"] for g in recap()["genres"]] == ["Drama", "Comedy"]


def test_only_a_show_first_played_in_the_window_counts_as_started(client):
    claim(client)
    seed()
    assert recap()["shows_started"] == 1


def test_when_they_watch(client):
    claim(client)
    seed()
    r = recap()
    assert r["busiest_weekday"] == datetime.fromtimestamp(NOW - 2 * DAY - 3600).strftime("%A")
    assert r["biggest_day"]["hours"] == 2.2


def test_a_viewer_reads_their_own_and_nobody_elses(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "own")
    assert client.get("/api/users/7/recap?days=365").status_code == 200
    assert client.get("/api/users/8/recap").status_code == 403

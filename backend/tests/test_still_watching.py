"""Do not suggest deleting the next episode of something somebody is watching.

An episode nobody has played, in a show somebody is partway through, is not an
abandoned file. It is the next episode. On this library 1,751 of the 8,911 big
never played episodes belong to a show watched in the last sixty days, and 38
of the 702 files the cleanup list actually suggested were exactly that.

They are counted and said rather than silently dropped: a list that quietly
shrinks is a list nobody can reason about.
"""

import time

from tests.test_auth import claim

DAY = 86400


def seed(last_play_days_ago: int | None):
    from app.db import session_scope
    from app.models import History, MediaItem, User

    now = int(time.time())
    with session_scope() as db:
        db.add(User(user_id=1, username="someone", friendly_name="Someone"))
        # A show with two episodes. One watched, one never touched.
        for key, index in ((100, 1), (101, 2)):
            db.add(MediaItem(
                rating_key=key, media_type="episode", title=f"Episode {index}",
                full_title=f"A Show - Episode {index}", grandparent_rating_key=900,
                grandparent_title="A Show", file_size=9_000_000_000, file_path=f"/tv/e{index}.mkv",
                library_seen_at=None, section_id=1,
            ))
        if last_play_days_ago is not None:
            db.add(History(row_id=1, user_id=1, rating_key=100, grandparent_rating_key=900,
                           started=now - last_play_days_ago * DAY, stopped=now - last_play_days_ago * DAY + 600,
                           full_title="A Show - Episode 1", media_type="episode", percent_complete=100))


def suggested(client):
    from app.services import cleanup

    return cleanup.candidates(days=365)


def test_the_next_episode_of_something_being_watched_is_left_out(client, monkeypatch):
    from app.services import library_scan

    claim(client)
    monkeypatch.setattr(library_scan, "in_library", lambda: True)
    seed(last_play_days_ago=3)
    found = suggested(client)
    assert found["watching"] == 1, "the unplayed episode is the next one, not an abandoned file"
    assert [row["rating_key"] for row in found["items"]] == []


def test_a_show_nobody_has_touched_in_months_is_still_suggested(client, monkeypatch):
    """Long enough to cover somebody who watches an episode a week and takes a
    month off, short enough that a show abandoned last year is not protected
    for ever."""
    from app.services import library_scan

    claim(client)
    monkeypatch.setattr(library_scan, "in_library", lambda: True)
    seed(last_play_days_ago=200)
    found = suggested(client)
    assert found["watching"] == 0
    assert 101 in [row["rating_key"] for row in found["items"]]


def test_a_film_is_never_spared_by_this(client, monkeypatch):
    """It has no show to be partway through, and sparing one would be the rule
    quietly doing something else."""
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import cleanup, library_scan

    claim(client)
    monkeypatch.setattr(library_scan, "in_library", lambda: True)
    seed(last_play_days_ago=3)
    with session_scope() as db:
        db.add(MediaItem(rating_key=200, media_type="movie", title="A Film", full_title="A Film",
                         file_size=9_000_000_000, file_path="/films/a.mkv", section_id=1))
    found = cleanup.candidates(days=365)
    assert 200 in [row["rating_key"] for row in found["items"]]


def test_it_says_how_many_it_left_out(client, monkeypatch):
    """A list that quietly shrinks is a list nobody can reason about."""
    from app.services import library_scan

    claim(client)
    monkeypatch.setattr(library_scan, "in_library", lambda: True)
    seed(last_play_days_ago=3)
    answer = client.get("/api/library/attention?kind=room&days=365").json()
    assert answer["watching"] == 1 and answer["watching_days"] == 60


# ---- and the other reason a file has not been watched -------------------------


def test_something_added_last_week_is_not_a_file_nobody_wants(client, monkeypatch):
    """It has not been ignored. It has been added. On this library 1,102 of
    the big never played files arrived in the last month, and offering them up
    for the room is arguing with whoever put them there a fortnight ago."""
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import cleanup, library_scan

    claim(client)
    monkeypatch.setattr(library_scan, "in_library", lambda: True)
    now = int(time.time())
    with session_scope() as db:
        db.add(MediaItem(rating_key=1, media_type="movie", title="Just arrived", full_title="Just arrived",
                         file_size=9_000_000_000, file_path="/films/new.mkv", section_id=1,
                         added_at=now - 3 * DAY))
        db.add(MediaItem(rating_key=2, media_type="movie", title="Been here ages", full_title="Been here ages",
                         file_size=9_000_000_000, file_path="/films/old.mkv", section_id=1,
                         added_at=now - 400 * DAY))
    found = cleanup.candidates(days=365)
    assert found["settling"] == 1
    assert [row["rating_key"] for row in found["items"]] == [2]


def test_a_file_with_no_added_date_is_judged_as_before(client, monkeypatch):
    """Anything scanned before the date was being stored has none, and
    treating a missing date as new would empty the list."""
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import cleanup, library_scan

    claim(client)
    monkeypatch.setattr(library_scan, "in_library", lambda: True)
    with session_scope() as db:
        db.add(MediaItem(rating_key=1, media_type="movie", title="No date", full_title="No date",
                         file_size=9_000_000_000, file_path="/films/x.mkv", section_id=1, added_at=None))
    found = cleanup.candidates(days=365)
    assert found["settling"] == 0 and [r["rating_key"] for r in found["items"]] == [1]


def test_an_old_file_nobody_played_in_years_is_not_spared_by_the_settling_rule(client, monkeypatch):
    """The grace period is about never having been played, not about a file
    somebody watched once in 2021."""
    from app.db import session_scope
    from app.models import History, MediaItem
    from app.services import cleanup, library_scan

    claim(client)
    monkeypatch.setattr(library_scan, "in_library", lambda: True)
    now = int(time.time())
    with session_scope() as db:
        db.add(MediaItem(rating_key=1, media_type="movie", title="Watched long ago", full_title="Watched long ago",
                         file_size=9_000_000_000, file_path="/films/x.mkv", section_id=1, added_at=now - 3 * DAY))
        db.add(History(row_id=1, user_id=1, rating_key=1, started=now - 1500 * DAY,
                       stopped=now - 1500 * DAY + 600, full_title="Watched long ago", media_type="movie"))
    found = cleanup.candidates(days=365)
    assert found["settling"] == 0
    assert [r["reason"] for r in found["items"]] == ["not_played_in_years"]

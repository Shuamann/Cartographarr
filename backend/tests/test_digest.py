import time
from datetime import UTC, datetime, timedelta

from tests.test_auth import claim

DAY = 86400


def seed(now):
    from app.db import session_scope
    from app.models import Device, History, Issue, Library, MediaItem, TravelFlag, User

    with session_scope() as db:
        db.add(Library(section_id=1, name="Movies"))
        db.add(User(user_id=1, username="alpha", friendly_name="Alpha"))
        db.add(User(user_id=2, username="beta"))
        # Two plays this week, one last week, so a week-on-week figure has
        # something to be wrong about.
        db.add(History(row_id=1, user_id=1, started=now - 2 * DAY, play_duration=3600,
                       rating_key=101, title="Film 1", grandparent_title=None, machine_id="tv"))
        db.add(History(row_id=2, user_id=2, started=now - 3 * DAY, play_duration=1800,
                       rating_key=101, title="Film 1", machine_id="tv"))
        db.add(History(row_id=3, user_id=1, started=now - 9 * DAY, play_duration=7200,
                       rating_key=102, title="Film 2", machine_id="tv"))
        db.add(Device(machine_id="new-tv", user_id=1, player="New TV", platform="Roku", first_seen=now - DAY))
        db.add(Device(machine_id="old-tv", user_id=1, player="Old TV", first_seen=now - 300 * DAY))
        db.add(TravelFlag(user_id=1, from_history_id=1, to_history_id=2, status="new",
                          created_at=datetime.fromtimestamp(now - DAY, UTC)))
        db.add(Issue(issue_type="audio", status="open", rating_key=101,
                     created_at=datetime.fromtimestamp(now - DAY, UTC)))
        db.add(MediaItem(rating_key=101, title="Film 1", media_type="movie", section_id=1, file_size=8_000_000_000))
        db.add(MediaItem(rating_key=103, title="Film 3", media_type="movie", section_id=1, file_size=2_000_000_000))


def test_the_digest_is_the_week_not_everything(client):
    from app.db import session_scope
    from app.services import digest

    claim(client)
    now = int(time.time())
    seed(now)
    with session_scope() as db:
        title, body = digest.compose(db)

    assert title.startswith("Cartographarr, week to")
    # Two plays this week, not the three on record.
    assert "2 plays" in body and "1.5 hours" in body and "2 people" in body
    assert "up 100% on the week before" in body  # two plays against last week's one
    assert "Film 1" in body and "Film 2" not in body
    # The device seen last year is not news.
    assert "1 new device: New TV (Roku)" in body and "Old TV" not in body
    assert "1 new signal, 1 waiting to be looked at" in body
    assert "1 problem reported this week, 1 still open" in body
    # Where the library stands, including what nobody has ever watched.
    assert "2 files, 10 GB, across 1 library" in body
    assert "1 of them have never been played" in body


def test_a_quiet_week_is_a_short_message(client):
    from app.db import session_scope
    from app.services import digest

    claim(client)
    with session_scope() as db:
        _, body = digest.compose(db)
    assert body.strip() == "Watching\n  Nobody watched anything this week."


def test_it_waits_for_its_day_and_needs_somewhere_to_send(client):
    """The job runs every hour and sends on one of them."""
    import asyncio

    from app import tasks
    from app.main import _weekly_digest
    from app.settings_store import save

    claim(client)
    assert "digest" in tasks.TASKS

    def go():
        return asyncio.run(_weekly_digest())

    # Off by default.
    try:
        go()
        raise AssertionError("should have skipped")
    except tasks.Skipped as exc:
        assert "switched off" in str(exc)

    # On, but not on the right day: still nothing, and it says when.
    now = datetime.now()
    save({"weekly_digest": True, "digest_weekday": (now.weekday() + 1) % 7, "digest_hour": now.hour})
    try:
        go()
        raise AssertionError("should have skipped")
    except tasks.Skipped as exc:
        assert "Sent " in str(exc)

    # Unless somebody pressed Run now, which means now whatever the day says.
    tasks.TASKS["digest"].trigger = "manual"
    try:
        go()
        raise AssertionError("should have got as far as sending")
    except RuntimeError as exc:
        assert "No notification targets" in str(exc)
    finally:
        tasks.TASKS["digest"].trigger = "schedule"

    # Right day and hour, but nowhere to send it, which is an error rather
    # than a skip: somebody asked for this and is not getting it.
    save({"weekly_digest": True, "digest_weekday": now.weekday(), "digest_hour": now.hour, "apprise_urls": ""})
    try:
        go()
        raise AssertionError("should have failed")
    except RuntimeError as exc:
        assert "No notification targets" in str(exc)


def test_the_hour_can_be_set_and_read_back(client):
    claim(client)
    assert client.put("/api/settings", json={"weekly_digest": True, "digest_weekday": 6, "digest_hour": 18}).status_code == 200
    values = {s["key"]: s["value"] for s in client.get("/api/settings").json()}
    assert values["weekly_digest"] is True
    assert values["digest_weekday"] == 6 and values["digest_hour"] == 18

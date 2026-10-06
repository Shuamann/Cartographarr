"""Is anything missing, and if so what.

Switching where the data comes from is the one change where everything can
look normal and be wrong: a day nobody fetched looks exactly like a day nobody
watched anything. The useful half of bringing in Tautulli's history is the
question, not the copy.
"""

import asyncio
from datetime import UTC, datetime

from tests.test_auth import claim


class FakeTautulli:
    """Answers get_plays_by_date and get_history, and records what it was asked."""

    def __init__(self, per_day, rows_by_day=None):
        self.per_day = per_day
        self.rows_by_day = rows_by_day or {}
        self.asked = []

    async def call(self, command, **params):
        self.asked.append((command, params))
        if command == "get_plays_by_date":
            days = sorted(self.per_day)
            return {
                "categories": days,
                "series": [
                    {"name": "TV", "data": [self.per_day[d] for d in days]},
                    {"name": "Total", "data": [self.per_day[d] for d in days]},
                ],
            }
        if command == "get_history":
            return {"data": self.rows_by_day.get(params.get("after"), [])}
        return {}

    async def aclose(self):
        pass


def _play(db, row_id, day, hour=12):
    from app.models import History

    started = int(datetime(*[int(p) for p in day.split("-")], hour).timestamp())
    db.add(History(row_id=row_id, user_id=7, started=started, stopped=started + 600, full_title=f"row {row_id}"))


def test_a_day_that_matches_is_not_reported(client):
    from app.db import session_scope
    from app.services import handover

    claim(client)
    with session_scope() as db:
        _play(db, 1, "2026-03-01")
        _play(db, 2, "2026-03-01", 14)

    found = asyncio.run(handover.compare(FakeTautulli({"2026-03-01": 2})))
    assert found["missing"] == 0 and found["extra"] == 0
    assert found["missing_days"] == [] and found["tautulli"] == found["here"] == 2


def test_a_day_that_is_short_is_named_with_how_short(client):
    """A missing week in 2022 and a missing hour last Tuesday are different
    problems, and only naming the days tells them apart."""
    from app.db import session_scope
    from app.services import handover

    claim(client)
    with session_scope() as db:
        _play(db, 1, "2026-03-01")

    found = asyncio.run(handover.compare(FakeTautulli({"2026-03-01": 4, "2026-03-02": 0})))
    assert found["missing"] == 3
    assert found["missing_days"] == [{"day": "2026-03-01", "tautulli": 4, "here": 1, "difference": 3}]


def test_days_with_more_here_are_reported_separately(client):
    """Not a fault on its own: this app records plays from Plex directly when
    Tautulli is not connected, so a day it watched and Tautulli did not is
    expected. Reported because a lot of them, on days Tautulli was running, is
    what counting something twice looks like."""
    from app.db import session_scope
    from app.services import handover

    claim(client)
    with session_scope() as db:
        _play(db, 1, "2026-03-01")
        _play(db, 2, "2026-03-01", 13)
        _play(db, 3, "2026-03-01", 14)

    found = asyncio.run(handover.compare(FakeTautulli({"2026-03-01": 1})))
    assert found["missing"] == 0 and found["extra"] == 2
    assert found["extra_days"][0]["difference"] == 2


def test_only_the_short_days_are_fetched(client):
    """One request for the day that is short, rather than a walk through four
    years to find it."""
    from app.db import session_scope
    from app.models import History
    from app.services import handover

    claim(client)
    with session_scope() as db:
        _play(db, 1, "2026-03-01")

    started = int(datetime(2026, 3, 2, 20).timestamp())
    fake = FakeTautulli(
        {"2026-03-01": 1, "2026-03-02": 1, "2026-03-03": 0},
        {"2026-03-02": [{"row_id": 99, "user_id": 7, "date": started, "started": started, "stopped": started + 60,
                         "full_title": "The missing one", "media_type": "movie"}]},
    )
    filled = asyncio.run(handover.fill(fake))
    assert filled == {"filled": 1, "days": 1}
    asked = [params.get("after") for command, params in fake.asked if command == "get_history"]
    assert asked == ["2026-03-02"], "only the day that was short"
    with session_scope() as db:
        assert db.get(History, 99) is not None


def test_running_it_twice_changes_nothing(client):
    """History is keyed on Tautulli's own row id and written with an upsert,
    so a play that is already here arrives with the id it already has. That is
    checked rather than trusted, because the whole point of this is not
    importing what is already here."""
    from app.db import session_scope
    from app.models import History
    from app.services import handover

    claim(client)
    started = int(datetime(2026, 3, 2, 20).timestamp())
    row = {"row_id": 99, "user_id": 7, "date": started, "started": started, "stopped": started + 60,
           "full_title": "The missing one", "media_type": "movie"}
    fake = FakeTautulli({"2026-03-02": 1}, {"2026-03-02": [row]})

    asyncio.run(handover.fill(fake))
    asyncio.run(handover.fill(FakeTautulli({"2026-03-02": 1}, {"2026-03-02": [row]})))
    with session_scope() as db:
        assert db.query(History).filter(History.row_id == 99).count() == 1


def test_a_tautulli_that_says_nothing_useful_is_said_so_rather_than_guessed_at(client):
    from app.services import handover

    claim(client)

    class Empty(FakeTautulli):
        async def call(self, command, **params):
            return {}

    found = asyncio.run(handover.compare(Empty({})))
    assert found["asked"] is False and found["reason"]


def test_it_is_a_task_so_it_runs_and_can_be_seen(client):
    """A check nobody can run is a check nobody runs."""
    from app import tasks

    assert "history_check" in tasks.TASKS
    assert tasks.TASKS["history_check"].name == "Check nothing is missing"


def test_the_check_answers_now_rather_than_starting_a_job(client, monkeypatch):
    """One request to Tautulli and a count, under a second on a four year
    library. A question somebody asked deserves an answer rather than a
    spinner and a task page to go and find."""
    from app.routers import admin

    claim(client)
    monkeypatch.setattr(admin, "TautulliClient", lambda settings: FakeTautulli({"2026-03-01": 0}))
    answer = client.get("/api/handover/check").json()
    assert answer["asked"] is True and answer["missing"] == 0


def test_without_tautulli_it_says_so_rather_than_failing(client, monkeypatch):
    """There is nothing to compare against, which is a plain answer and not an
    error worth colouring red."""
    from tests.test_setup_plex import no_tautulli

    claim(client)
    no_tautulli(monkeypatch)
    answer = client.get("/api/handover/check").json()
    assert answer["asked"] is False and "Tautulli" in answer["reason"]


def test_filling_without_tautulli_is_refused(client, monkeypatch):
    from tests.test_setup_plex import no_tautulli

    claim(client)
    no_tautulli(monkeypatch)
    assert client.post("/api/handover/fill").status_code == 400


def test_filling_a_day_does_not_leave_the_play_recorded_twice(client):
    """An install that ran on Plex alone wrote these plays down itself, under
    a negative id, and Tautulli has now delivered its own copy.

    The history sync has always dropped ours when that happens. Filling a gap
    writes to the same table and did not, so a fetched day ended up holding
    both copies of every play, which is the exact thing this feature exists to
    notice and would then have reported as extra on the next run.
    """
    from app.db import session_scope
    from app.models import History
    from app.services import handover

    claim(client)
    started = int(datetime(2026, 3, 2, 20).timestamp())
    with session_scope() as db:
        # Recorded here from Plex: negative id, same person, same item, same
        # moment.
        db.add(History(row_id=-5, user_id=7, rating_key=4101, started=started, stopped=started + 600,
                       full_title="The same play"))

    fake = FakeTautulli(
        {"2026-03-02": 2},
        {"2026-03-02": [{"row_id": 99, "user_id": 7, "rating_key": 4101, "date": started, "started": started,
                         "stopped": started + 600, "full_title": "The same play", "media_type": "movie"}]},
    )
    asyncio.run(handover.fill(fake))
    with session_scope() as db:
        kept = db.query(History).all()
        assert [h.row_id for h in kept] == [99], "Tautulli's copy is the one kept, and only one is kept"

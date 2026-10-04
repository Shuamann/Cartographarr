"""Tidying waits for the house to go quiet.

Tidying reads and rewrites a whole film: minutes of the array's attention for a
file nobody is waiting on. Doing that at eight in the evening while four people
stream from the same disks is the one piece of work this app does that somebody
else can feel.

The case that matters most is the one where it must *not* wait: if the check
itself cannot be made, a job that never runs is worse than one that runs at a
bad moment.
"""

import asyncio

import pytest

from app.services import mediafix
from app.settings_store import trial


def quiet() -> bool:
    return asyncio.run(mediafix._house_is_quiet())


@pytest.fixture()
def activity(monkeypatch):
    """Whatever Tautulli is pretending to say this time."""
    answer: dict = {"sessions": []}

    class Fake:
        def __init__(self, _settings):
            pass

        async def call(self, _cmd, **_kw):
            if isinstance(answer.get("raise"), Exception):
                raise answer["raise"]
            return answer

        async def aclose(self):
            return None

    monkeypatch.setattr("app.tautulli.client.TautulliClient", Fake)
    return answer


def test_an_empty_house_is_quiet(client, activity):
    with trial({"tidy_when_quiet": True}):
        assert quiet() is True


def test_one_stream_is_not(client, activity):
    activity["sessions"] = [{"session_key": "1"}]
    with trial({"tidy_when_quiet": True}):
        assert quiet() is False


def test_switched_off_never_waits(client, activity):
    activity["sessions"] = [{"session_key": "1"}, {"session_key": "2"}]
    with trial({"tidy_when_quiet": False}):
        assert quiet() is True


def test_a_tautulli_that_cannot_be_reached_does_not_stop_everything(client, activity):
    """The important one. A job held for ever because the thing it asks is
    down is worse than a job that runs while somebody is watching."""
    activity["raise"] = RuntimeError("Tautulli is not answering")
    with trial({"tidy_when_quiet": True}):
        assert quiet() is True


def test_nothing_set_up_yet_does_not_wait(client, activity):
    """Before setup there is nothing to ask, and nothing streaming either."""
    with trial({"tidy_when_quiet": True, "tautulli_url": "", "tautulli_api_key": ""}):
        assert quiet() is True


# ---- the queue keeps its place ----------------------------------------------

def test_a_waiting_job_still_reads_as_queued(client):
    """It is not taken off the queue while it waits, so it never looks like a
    job that stalled halfway through."""
    import json

    from app.db import session_scope
    from app.models import MediaJob

    with session_scope() as db:
        db.add(MediaJob(rating_key=1, title="A Film", path="/movies/a.mkv",
                        steps=json.dumps({"steps": ["subtitle_clutter"], "chosen": {}}),
                        status="queued", progress=0))

    assert mediafix._anything_queued() is True

    with session_scope() as db:
        db.query(MediaJob).delete()
    assert mediafix._anything_queued() is False

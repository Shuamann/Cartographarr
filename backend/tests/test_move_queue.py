"""Queueing moves, one title at a time.

A move is the disk reading and writing a whole file, so two at once is each of
them taking twice as long. The queue exists so somebody can pick fifty titles
off a full array in one sitting and walk away, which is the only way moving is
any use at that scale.

The awkward parts are what happens when a job's turn comes and it cannot move
yet, and what happens when the app is restarted with a move in flight. Each
test below was watched failing against the mistake it names.
"""

from __future__ import annotations

import asyncio

import pytest

from app.db import session_scope
from app.services import moves

NAS = "/nas/media/movies"
ARRAY = "/array/media/movies"


def put(rating_key=1, to=NAS, status="queued", **kw):
    return moves.queue(rating_key, "radarr", 7, kw.pop("title", "A Film"), to, ARRAY, 4_000_000_000,
                       kw.pop("who", "someone"))


def rows():
    return moves.listing()


def one(job_id):
    from app.models import MoveJob

    with session_scope() as db:
        return moves.as_dict(db.get(MoveJob, job_id))


def test_a_title_is_queued_once_however_often_it_is_asked_for(client):
    """Pressing twice is somebody pressing twice, not a second move. The first
    one is still going to happen, and two jobs for one title would have the
    second one fail as "it is already there" after the first succeeded."""
    first = put(rating_key=5)
    second = put(rating_key=5)
    assert first["id"] == second["id"]
    assert len(rows()) == 1


def test_a_different_title_gets_its_own_job(client):
    put(rating_key=5)
    put(rating_key=6)
    assert len(rows()) == 2


def test_a_queued_one_can_be_taken_out(client):
    job = put(rating_key=5)
    assert moves.cancel(job["id"]) is True
    assert one(job["id"])["status"] == "cancelled"


def test_one_already_moving_is_left_to_the_service(client):
    """The service is doing it. Stopping halfway is how a file ends up in
    neither place."""
    job = put(rating_key=5)
    moves._mark(job["id"], status="moving")
    assert moves.cancel(job["id"]) is False
    assert one(job["id"])["status"] == "moving"


def test_a_cancelled_one_frees_the_title_to_be_queued_again(client):
    job = put(rating_key=5)
    moves.cancel(job["id"])
    again = put(rating_key=5)
    assert again["id"] != job["id"]


def test_the_newest_job_is_listed_first(client):
    put(rating_key=5)
    last = put(rating_key=6)
    assert rows()[0]["id"] == last["id"]


class Service:
    label = "Radarr"
    name = "radarr"
    path = "movie"
    base_url = "http://radarr.invalid"
    headers: dict[str, str] = {}

    def configured(self):
        return True


@pytest.fixture
def mover(monkeypatch):
    """A service that answers, with nothing in the way unless a test says so."""
    asked: list[str] = []
    state = {"blockers": [], "landed": False}

    async def get_json(url, headers=None, params=None, **kw):
        return {"id": 7, "title": "A Film", "hasFile": True, "sizeOnDisk": 4_000_000_000,
                "rootFolderPath": NAS if state["landed"] else ARRAY,
                "movieFile": {"path": (NAS if state["landed"] else ARRAY) + "/A Film/A.mkv"}}

    async def plan(service, rating_key, whole, to_path):
        return {"can_move": not state["blockers"], "blockers": list(state["blockers"]),
                "warnings": [], "from": ARRAY, "to": to_path, "bytes": 4_000_000_000}

    async def move(service, rating_key, whole, to_path):
        asked.append(to_path)
        state["landed"] = True
        return {}

    monkeypatch.setattr("app.integrations.base.get_json", get_json)
    monkeypatch.setattr(moves, "plan", plan)
    monkeypatch.setattr(moves, "move", move)
    monkeypatch.setattr("app.integrations.arr.radarr", Service())
    monkeypatch.setattr(moves, "WATCH_EVERY", 0)
    # Settling waits for Plex to finish a scan. A test has no Plex and no
    # reason to wait thirty seconds for one.
    monkeypatch.setattr(moves, "SETTLE_SECONDS", 0)
    state["settled"] = []
    monkeypatch.setattr(
        moves, "settle",
        lambda key, old: state["settled"].append((key, old)) or {"old": True, "new": True, "row": True},
    )
    return asked, state


def test_a_job_whose_turn_comes_is_asked_for_and_finishes(client, mover):
    asked, _ = mover
    job = put(rating_key=5)
    assert asyncio.run(moves._one(job["id"])) is True
    assert asked == [NAS]
    assert one(job["id"])["status"] == "done"


def test_one_that_cannot_move_yet_stays_queued_and_says_why(client, mover):
    """Failing it would throw away a move somebody still wants, and stopping
    the queue would mean a list left overnight did nothing."""
    asked, state = mover
    state["blockers"] = ["it is being watched right now by somebody"]
    job = put(rating_key=5)
    assert asyncio.run(moves._one(job["id"])) is False
    after = one(job["id"])
    assert after["status"] == "queued"
    assert "watched" in (after["message"] or "")
    assert asked == [], "nothing should have been asked of the service"


def test_a_blocked_one_does_not_hold_up_the_rest(client, mover):
    """The whole point of a queue somebody walks away from is that it drains.
    Stopping at the first title that is busy would leave fifty behind it."""
    asked, state = mover
    blocked = put(rating_key=5)
    movable = put(rating_key=6)

    real = moves.plan

    async def plan(service, rating_key, whole, to_path):
        if rating_key == 5:
            return {"can_move": False, "blockers": ["busy"], "warnings": [], "from": ARRAY, "to": to_path}
        return await real(service, rating_key, whole, to_path)

    moves.plan = plan
    monkeypatch_sleep = moves.RETRY_AFTER
    moves.RETRY_AFTER = 0
    try:
        asyncio.run(moves._work())
    finally:
        moves.plan = real
        moves.RETRY_AFTER = monkeypatch_sleep
    assert one(blocked["id"])["status"] == "queued"
    assert one(movable["id"])["status"] == "done"


def test_a_service_that_has_forgotten_the_title_fails_that_one(client, mover):
    asked, _ = mover

    async def gone(url, headers=None, params=None, **kw):
        return None

    import app.integrations.base as base

    base.get_json = gone
    job = put(rating_key=5)
    try:
        assert asyncio.run(moves._one(job["id"])) is True
    finally:
        pass
    assert one(job["id"])["status"] == "failed"


def test_landing_needs_the_file_and_not_just_the_record(client):
    """The service records the new folder before the copy is finished. Taking
    that as done starts the next move while the disk is still busy with this
    one, which is the whole thing one at a time exists to avoid."""
    record_only = {"rootFolderPath": NAS, "hasFile": True, "movieFile": {"path": ARRAY + "/A/A.mkv"}}
    both = {"rootFolderPath": NAS, "hasFile": True, "movieFile": {"path": NAS + "/A/A.mkv"}}
    assert moves.has_landed(record_only, NAS) is False
    assert moves.has_landed(both, NAS) is True


def test_a_title_with_no_file_has_not_landed(client):
    """The path alone is not enough. The service can hold a folder under the
    destination with nothing in it, and calling that landed would mark a move
    done that never copied anything."""
    assert moves.has_landed(
        {"rootFolderPath": NAS, "hasFile": False, "movieFile": {"path": NAS + "/A/A.mkv"}}, NAS
    ) is False
    assert moves.has_landed({"rootFolderPath": NAS, "hasFile": False, "movieFile": {}}, NAS) is False


def test_a_trailing_slash_is_not_a_different_folder(client):
    assert moves.has_landed({"rootFolderPath": NAS + "/", "hasFile": True,
                             "movieFile": {"path": NAS + "/A/A.mkv"}}, NAS) is True


def test_plex_is_told_and_the_row_read_back_when_it_lands(client, mover):
    """The move is only finished once this app and Plex agree with the service
    about where the file is. Without this the card went on naming the old disk
    for as long as six hours, beside a panel reading the new one."""
    asked, state = mover
    job = put(rating_key=5)
    asyncio.run(moves._one(job["id"]))
    assert state["settled"] == [(5, ARRAY)], "told about the old folder as well as the new"
    assert one(job["id"])["status"] == "done"

"""Moving a title from one library source to another.

An array fills up and the answer is to move things off it. Radarr and Sonarr
each move the files and update their own record in one operation, which nothing
outside them can do correctly, so the app asks for that rather than moving
anything itself.

The shapes here were measured against a real Radarr 6.4.4 before any of it was
written: root folders carry id, path, accessible and freeSpace and nothing
else; a movie carries hasFile, sizeOnDisk, rootFolderPath and path, and its
`status` is the release status, which says nothing about the file; and a queue
row's useful field is trackedDownloadState, where a real queue had two rows
whose status was "completed" and whose state was "importBlocked".

Each test was watched failing against the mistake it names.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import moves

ARRAY = "/array/media/movies"
ARRAY_TOO = "/array/media/kidsmovies"
NAS = "/nas/media/movies"

SMALL = 4_000_000_000
ROOM = 300_000_000_000
LOTS = 60_000_000_000_000


class Service:
    """A stand in shaped like the real one, with nothing happening by default."""

    label = "Radarr"
    path = "movie"
    base_url = "http://radarr.invalid"
    headers: dict[str, str] = {}

    def __init__(self):
        self.roots = [
            {"id": 1, "path": ARRAY, "accessible": True, "freeSpace": ROOM},
            {"id": 2, "path": ARRAY_TOO, "accessible": True, "freeSpace": ROOM},
            {"id": 3, "path": NAS, "accessible": True, "freeSpace": LOTS},
        ]
        self.queue: list[dict] = []


def movie(**kw):
    return {"id": 7, "title": "A Film", "hasFile": True, "sizeOnDisk": SMALL,
            "rootFolderPath": ARRAY, "path": ARRAY + "/A Film (2019)", **kw}


@pytest.fixture
def service(monkeypatch):
    svc = Service()

    async def get_json(url, headers=None, params=None, **kw):
        if url.endswith("/rootfolder"):
            return svc.roots
        if url.endswith("/queue"):
            return {"records": svc.queue}
        return None

    monkeypatch.setattr("app.integrations.base.get_json", get_json)
    # Nothing playing and nothing being done to it, unless a test says so.
    monkeypatch.setattr(moves, "_busy_here", lambda key: [])

    async def nobody(key):
        return []

    monkeypatch.setattr(moves, "_being_watched", nobody)
    return svc


def plan(service, to=NAS, item=None, key=1):
    return asyncio.run(moves.plan(service, key, item or movie(), to))


def test_a_move_to_another_disk_is_allowed(service):
    answer = plan(service)
    assert answer["can_move"] is True
    assert answer["blockers"] == [] and answer["warnings"] == []
    assert answer["bytes"] == SMALL


def test_a_title_being_watched_is_not_moved(service, monkeypatch):
    """Moving the files out from under a stream breaks it. The server is asked
    rather than the stream table, because the table is one poll old and the
    question is about the next few minutes."""
    async def watching(key):
        return ["it is being watched right now by somebody"]

    monkeypatch.setattr(moves, "_being_watched", watching)
    answer = plan(service)
    assert answer["can_move"] is False
    assert any("watched" in b for b in answer["blockers"])


def test_not_knowing_what_is_playing_stops_it_too(service, monkeypatch):
    """Not knowing is not the same as nobody watching, and a move is never
    urgent enough to guess."""
    async def cannot(key):
        return ["this app cannot see what is playing right now (no server)"]

    monkeypatch.setattr(moves, "_being_watched", cannot)
    assert plan(service)["can_move"] is False


def test_a_download_in_the_queue_stops_it(service):
    """Moving the folder while the service is importing into it is a race
    nobody wins."""
    service.queue = [{"movieId": 7, "status": "completed", "trackedDownloadState": "importBlocked"}]
    answer = plan(service)
    assert answer["can_move"] is False
    assert "Radarr has a download for it that it will not import by itself" in answer["blockers"]


def test_a_download_for_a_different_title_does_not_stop_it(service):
    """Keyed on the title's own id. Stopping on anything in the queue would
    stop every move whenever anything at all was downloading."""
    service.queue = [{"movieId": 999, "status": "downloading", "trackedDownloadState": "downloading"}]
    assert plan(service)["can_move"] is True


def test_the_queue_is_described_as_a_person_would(service):
    """A real queue had rows whose status was "completed" and whose state was
    "importBlocked", and "Radarr is completed a download" is not a sentence."""
    service.queue = [{"movieId": 7, "status": "completed", "trackedDownloadState": "downloading"}]
    assert "Radarr is downloading something for it" in plan(service)["blockers"]


def test_this_app_tidying_it_stops_it(service, monkeypatch):
    """Tidying rewrites the file where it stands. Moving it at the same moment
    is two things writing one file."""
    monkeypatch.setattr(moves, "_busy_here", lambda key: ["this app is tidying it, which rewrites the file"])
    assert plan(service)["can_move"] is False


def test_a_title_with_no_file_has_nothing_to_move(service):
    answer = plan(service, item=movie(hasFile=False, sizeOnDisk=0))
    assert answer["can_move"] is False
    assert any("nothing to move" in b for b in answer["blockers"])


def test_moving_it_where_it_already_is_is_refused(service):
    assert plan(service, to=ARRAY)["can_move"] is False


def test_a_destination_the_service_cannot_reach_is_refused(service):
    service.roots[2]["accessible"] = False
    assert plan(service, to=NAS)["can_move"] is False


def test_a_destination_with_less_room_than_the_files_is_refused(service):
    answer = plan(service, item=movie(sizeOnDisk=ROOM * 2))
    assert plan(service, to=ARRAY_TOO, item=movie(sizeOnDisk=ROOM * 2))["can_move"] is False
    assert answer["can_move"] is True, "the big disk still has room for it"


def test_an_unknown_destination_is_refused(service):
    assert plan(service, to="/somewhere/else")["can_move"] is False


def test_moving_within_one_disk_warns_rather_than_refuses(service):
    """Two roots on one disk report the same free space, and moving between
    them frees nothing on the disk somebody is trying to empty. A warning, not
    a refusal: moving a title between libraries on one disk is a reasonable
    thing to want, and identical figures are a hint rather than proof."""
    answer = plan(service, to=ARRAY_TOO)
    assert answer["can_move"] is True
    assert any("one disk" in w for w in answer["warnings"])


def test_every_reason_is_given_at_once(service, monkeypatch):
    """Somebody deciding whether to wait wants to know everything they are
    waiting for, not the first thing that happened to be checked."""
    service.queue = [{"movieId": 7, "status": "completed", "trackedDownloadState": "importing"}]
    monkeypatch.setattr(moves, "_busy_here", lambda key: ["this app is tidying it"])
    assert len(plan(service, item=movie(hasFile=False))["blockers"]) >= 3


def test_the_move_checks_again_before_asking(service, monkeypatch):
    """A plan somebody read for two minutes is a plan about the past, and the
    things it checks are exactly the ones that start without warning."""
    asked: list = []

    async def watching(key):
        return ["it is being watched right now by somebody"]

    monkeypatch.setattr(moves, "_being_watched", watching)
    monkeypatch.setattr(moves, "_tell_plex", lambda key, old: asked.append(("plex", old)))
    with pytest.raises(ValueError, match="watched"):
        asyncio.run(moves.move(service, 1, movie(), NAS))
    assert asked == [], "nothing should have been asked of anybody"

"""A grab that says up front it does not want to be asked again.

Radarr holds an import when it will not take a release by itself, usually
because it does not rate it an upgrade on what is already there. The app
already reads the manual import candidates at that point and offers Confirm,
so nobody has to open Radarr; what it could not do was decide in advance. You
picked a release, waited for the download, came back and clicked the thing you
already knew you wanted.

Each test here was watched failing against the mistake it names.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest

from app.db import session_scope
from app.services import replacements

HELD = "Not an upgrade for existing movie file"


class Radarr:
    """One held download, and a record of what was asked of it."""

    name = "radarr"
    label = "Radarr"
    path = "movie"

    def __init__(self, files=None):
        self.imported: list[tuple] = []
        self.files = [{"path": "/d/Film.mkv", "size": 5_000_000_000, "quality": {}, "languages": []}] if files is None else files

    def configured(self):
        return True

    async def queue(self):
        return [{
            "id": 3, "downloadId": "abc", "movieId": 7, "sizeleft": 0, "size": 1, "status": "completed",
            "trackedDownloadState": "importPending", "trackedDownloadStatus": "warning",
            "statusMessages": [{"messages": [HELD]}],
        }]

    async def history(self, arr_id, episode_id):
        return []

    async def manual_import_candidates(self, download_id):
        return self.files

    async def manual_import(self, files, arr_id, episode_id, download_id):
        self.imported.append((tuple(f.get("path") for f in files), arr_id, download_id))

    async def current_file(self, arr_id, episode_id):
        return None


@pytest.fixture
def radarr(monkeypatch):
    service = Radarr()
    monkeypatch.setattr(replacements, "_service", lambda name: service)
    return service


def put(auto_confirm, status="downloading"):
    from app.models import Replacement

    now = datetime.now(UTC)
    with session_scope() as db:
        db.add(Replacement(
            id=1, rating_key=1, title="Film", service="radarr", arr_id=7, episode_id=None,
            guid="g", indexer_id=2, status=status, download_id="abc", queue_id=3,
            auto_confirm=auto_confirm, created_by="someone", created_at=now, updated_at=now,
        ))


def row():
    from app.models import Replacement

    with session_scope() as db:
        r = db.get(Replacement, 1)
        return {"status": r.status, "message": r.message, "resolved_by": r.resolved_by,
                "candidate": json.loads(r.candidate or "{}")}


def test_without_it_a_held_import_waits_to_be_asked(client, radarr):
    """The behaviour that was there before, and still the default: confirming
    overrides the service's judgement about a file, which is not something to
    do to somebody by surprise."""
    put(auto_confirm=False)
    asyncio.run(replacements.poll())
    assert row()["status"] == "ready"
    assert radarr.imported == []


def test_with_it_the_held_import_happens_at_once(client, radarr):
    put(auto_confirm=True)
    asyncio.run(replacements.poll())
    assert row()["status"] == "importing"
    assert radarr.imported == [(("/d/Film.mkv",), 7, "abc")]


def test_it_imports_the_same_file_confirming_by_hand_would(client, radarr):
    """A release folder carries samples, subtitles and artwork beside the
    film. Two code paths choosing differently is how one of them quietly
    starts importing a two megabyte sample."""
    radarr.files = [
        {"path": "/d/sample.mkv", "size": 2_000_000, "quality": {}, "languages": []},
        {"path": "/d/Film.mkv", "size": 5_000_000_000, "quality": {}, "languages": []},
    ]
    put(auto_confirm=True)
    asyncio.run(replacements.poll())
    assert radarr.imported[0][0] == ("/d/Film.mkv",)


def test_nothing_to_import_waits_after_all_rather_than_failing(client, radarr):
    """A download the service can find no file in is not an error, it is a
    thing to go and look at. Silently marking it imported would be the worst
    of the three answers."""
    radarr.files = []
    put(auto_confirm=True)
    asyncio.run(replacements.poll())
    answer = row()
    assert answer["status"] == "ready"
    assert "waiting for you after all" in (answer["message"] or "")
    assert radarr.imported == []


def test_it_is_recorded_against_whoever_asked_for_it(client, radarr):
    """An import nobody appears to have confirmed is an import somebody will
    come looking for an explanation of."""
    put(auto_confirm=True)
    asyncio.run(replacements.poll())
    assert row()["resolved_by"] == "someone"


def test_it_fires_once_rather_than_on_every_poll(client, radarr):
    """The poll runs on a timer. Importing again each time it comes round
    would ask the service to import the same download over and over."""
    put(auto_confirm=True)
    asyncio.run(replacements.poll())
    asyncio.run(replacements.poll())
    asyncio.run(replacements.poll())
    assert len(radarr.imported) == 1


def test_the_candidate_is_still_written_down(client, radarr):
    """What was imported has to be recorded whichever way it was confirmed, or
    the row cannot say afterwards what it took."""
    put(auto_confirm=True)
    asyncio.run(replacements.poll())
    assert row()["candidate"].get("files")


def test_picking_the_file_is_one_function_for_both_paths():
    """Confirming by hand and confirming because it was asked for in advance
    must not drift into choosing differently."""
    candidate = json.dumps({"files": [{"path": "a", "size": 1}, {"path": "b", "size": 9}]})
    assert replacements.importable(candidate)["path"] == "b"
    assert replacements.importable(json.dumps({"files": []})) is None
    assert replacements.importable(None) is None

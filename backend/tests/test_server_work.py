from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db import session_scope
from app.plex import serverwork

SCAN = {
    "uuid": "fa6e1c8b", "kind": "library.update.section", "title": "Scanning Movies",
    "subtitle": "A Film (1997)", "progress": 40, "section_id": 3,
}
ANALYSE = {
    "uuid": "0a1b2c3d", "kind": "provider.subscriptions.process", "title": "Analysing media",
    "subtitle": None, "progress": 5, "section_id": None,
}

# Relative to now, not a date written down. `recent` asks what has run in the
T0 = datetime.now(UTC).replace(tzinfo=None, microsecond=0) - timedelta(hours=6)


def put(rows, at):
    with session_scope() as db:
        return serverwork.record(db, rows, at)


def recent(hours=48):
    with session_scope() as db:
        return serverwork.recent(db, hours)


def busy(when, **kw):
    with session_scope() as db:
        return serverwork.busy_at(db, when, **kw)


def test_one_job_seen_on_many_polls_is_one_spell(client):
    """The whole design."""
    assert put([SCAN], T0) == 1
    for i in range(1, 40):
        put([SCAN], T0 + timedelta(seconds=10 * i))
    rows = recent()
    assert len(rows) == 1
    assert rows[0]["minutes"] == 6.5


def test_a_second_run_of_the_same_scan_is_its_own_spell(client):
    put([SCAN], T0)
    put([{**SCAN, "uuid": "later"}], T0 + timedelta(hours=5))
    assert len(recent(hours=24)) == 2


def test_what_it_was_on_is_the_last_thing_seen(client):
    put([SCAN], T0)
    put([{**SCAN, "subtitle": "Another Film", "progress": 99}], T0 + timedelta(seconds=30))
    rows = recent()
    assert rows[0]["subtitle"] == "Another Film"
    assert rows[0]["progress"] == 99


def test_an_idle_server_writes_nothing(client):
    assert put([], T0) == 0
    assert recent() == []


def test_a_spell_is_found_from_a_moment_inside_it(client):
    put([SCAN], T0)
    put([SCAN], T0 + timedelta(minutes=20))
    assert [j["title"] for j in busy(T0 + timedelta(minutes=10))] == ["Scanning Movies"]


def test_a_moment_outside_a_spell_finds_nothing(client):
    put([SCAN], T0)
    put([SCAN], T0 + timedelta(minutes=20))
    assert busy(T0 + timedelta(hours=3)) == []


def test_a_spell_has_a_real_end_rather_than_an_open_one(client):
    """The app being stopped mid scan leaves a spell nothing closed."""
    put([SCAN], T0)
    assert busy(T0 + timedelta(days=7)) == []


def test_a_job_that_started_just_after_a_stall_still_lines_up_with_it(client):
    put([SCAN], T0 + timedelta(seconds=40))
    assert [j["title"] for j in busy(T0)] == ["Scanning Movies"]


def test_two_jobs_at_once_are_both_reported(client):
    put([SCAN, ANALYSE], T0)
    assert sorted(j["title"] for j in busy(T0)) == ["Analysing media", "Scanning Movies"]


def test_the_newest_spell_is_first(client):
    put([SCAN], T0)
    put([{**SCAN, "uuid": "later", "title": "Scanning TV"}], T0 + timedelta(hours=1))
    assert [j["title"] for j in recent()] == ["Scanning TV", "Scanning Movies"]


def test_an_activity_with_no_id_is_ignored(client, monkeypatch):
    """Nothing to key a spell on."""
    class Attrs(dict):
        attrib = {}

        def __init__(self, attrib):
            super().__init__()
            self.attrib = attrib

        def __iter__(self):
            return iter(())

    monkeypatch.setattr(
        "app.plex.server.server",
        lambda: type("S", (), {"query": staticmethod(lambda path: [Attrs({"type": "x", "title": "y"})])})(),
    )
    assert serverwork.now() == []


def test_a_server_that_will_not_answer_costs_the_poll_nothing(client, monkeypatch):
    """This rides on the sweep that enforces the rules."""
    def no():
        raise RuntimeError("no server")

    monkeypatch.setattr(serverwork, "now", no)
    assert serverwork.sample() == 0


def test_the_spell_is_keyed_on_plexs_id_and_nothing_else(client):
    put([SCAN], T0)
    put([{**SCAN, "uuid": "second-run"}], T0 + timedelta(hours=1))
    rows = recent()
    assert [r["title"] for r in rows] == ["Scanning Movies", "Scanning Movies"]
    assert len(rows) == 2
    # And the same id twice is one spell however its title is reported.
    put([{**SCAN, "title": "Scanning Movies (2)"}], T0 + timedelta(minutes=1))
    assert len(recent()) == 2

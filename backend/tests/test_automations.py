"""Rules about things nobody is watching.

A stream rule gets its chance while the stream is playing. These run on a
sweep, so the questions that matter are: do they only see their own kind of
subject, do they stop repeating themselves, and do they stop when told.
"""

import asyncio
import json
from datetime import UTC, datetime

from tests.test_auth import claim

NOW = int(datetime.now(UTC).timestamp())


def rule(name, trigger, field, op, value, action="log_only", **over):
    from app.db import session_scope
    from app.models import Rule

    with session_scope() as db:
        row = Rule(
            name=name, enabled=True, trigger=trigger, action=action,
            conditions=json.dumps({"type": "group", "op": "and", "items": [
                {"type": "condition", "field": field, "op": op, "value": value},
            ]}),
            actions=json.dumps([{"name": action, "params": {}}]),
            **over,
        )
        db.add(row)
        db.flush()
        return row.id


def seed_files():
    """One file transcoded for everyone, one watched happily."""
    from app.db import session_scope
    from app.models import History, MediaItem

    with session_scope() as db:
        db.add(MediaItem(rating_key=1, title="Trouble", full_title="Trouble", media_type="movie",
                         file_bitrate=40000, file_checked_at=datetime.now(UTC), video_codec="hevc"))
        db.add(MediaItem(rating_key=2, title="Fine", full_title="Fine", media_type="movie",
                         file_bitrate=6000, file_checked_at=datetime.now(UTC), video_codec="h264"))
        row = 0
        for key, decision in [(1, "transcode"), (1, "transcode"), (1, "transcode"), (2, "direct play")]:
            row += 1
            db.add(History(row_id=row, reference_id=row, rating_key=key, user_id=7, started=NOW - row * 3600,
                           media_type="movie", location="wan", transcode_decision=decision))


def log_rows(client, rule_id):
    return [e for e in client.get("/api/enforcement-log").json() if e.get("rule_id") == rule_id]


def test_a_file_rule_records_what_it_would_do(client):
    from app.services import automations

    claim(client)
    seed_files()
    rule_id = rule("Transcoded for everyone", "file", "file_transcode_percent", "gte", 80)

    answer = asyncio.run(automations.run_once())
    assert answer["matched"] == 1 and answer["acted"] == 0  # record only until told otherwise
    rows = log_rows(client, rule_id)
    assert len(rows) == 1 and rows[0]["full_title"] == "Trouble" and rows[0]["dry_run"] is True
    assert "would" in (rows[0]["result"] or "")


def test_the_same_file_does_not_set_it_off_every_sweep(client):
    from app.services import automations

    claim(client)
    seed_files()
    rule_id = rule("Transcoded for everyone", "file", "file_transcode_percent", "gte", 80)
    asyncio.run(automations.run_once())
    asyncio.run(automations.run_once())
    assert len(log_rows(client, rule_id)) == 1


def test_a_rule_stops_at_its_cap(client):
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import automations

    claim(client)
    seed_files()
    with session_scope() as db:
        # A second file that also matches, so there is something to stop at.
        db.add(MediaItem(rating_key=3, title="Also trouble", full_title="Also trouble", media_type="movie",
                         file_bitrate=50000, file_checked_at=datetime.now(UTC)))
        from app.models import History

        db.add(History(row_id=9, reference_id=9, rating_key=3, user_id=7, started=NOW - 100,
                       media_type="movie", location="wan", transcode_decision="transcode"))
    rule_id = rule("Big files", "file", "file_bitrate_mbps", "gte", 30, record_only=False, daily_cap=1)

    answer = asyncio.run(automations.run_once())
    assert answer["acted"] == 1 and answer["capped"] == 1
    rows = log_rows(client, rule_id)
    assert [r["dry_run"] for r in rows] == [False, True] or [r["dry_run"] for r in rows] == [True, False]
    assert any("already acted" in (r["result"] or "") for r in rows)


def test_a_stream_rule_is_left_to_the_stream_sweep(client):
    from app.services import automations

    claim(client)
    seed_files()
    rule("Live one", "stream", "user_streams", "gte", 2)
    assert asyncio.run(automations.run_once()) == {"rules": 0}


def test_a_rule_about_reports_sees_reports(client):
    from app.db import session_scope
    from app.models import Issue, MediaItem
    from app.services import automations

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=5, title="Film", full_title="Film", media_type="movie",
                         audio_tracks='[{"codec": "truehd", "channels": 8}]', file_checked_at=datetime.now(UTC)))
        db.add(Issue(source="local", issue_type="audio", status="open", message="No sound", rating_key=5,
                     title="Film", media_type="movie", created_at=datetime.now(UTC).replace(tzinfo=None)))
    # The point of joining the two: a report about audio on a file whose audio
    # this app already knows is unplayable.
    rule_id = rule("Audio reports on bad audio", "issue", "file_finding", "any", ["no_compatible_audio"])

    answer = asyncio.run(automations.run_once())
    assert answer["matched"] == 1
    assert log_rows(client, rule_id)[0]["full_title"] == "Film"


def test_a_rule_about_people_sees_people(client):
    from app.db import session_scope
    from app.models import User
    from app.services import automations

    claim(client)
    with session_scope() as db:
        db.add(User(user_id=7, username="quiet_one"))
        db.add(User(user_id=8, username="busy"))
        from app.models import History

        db.add(History(row_id=1, reference_id=1, user_id=8, started=NOW - 3600, media_type="movie"))
    rule_id = rule("Nobody watching", "person", "person_quiet", "is", True)

    asyncio.run(automations.run_once())
    rows = log_rows(client, rule_id)
    assert [r["username"] for r in rows] == ["quiet_one"]


def test_the_sweep_is_skipped_when_rules_are_off(client):
    from app import tasks

    claim(client)
    client.put("/api/settings", json={"enforce_enabled": False})
    asyncio.run(tasks.run("automations"))
    assert tasks.TASKS["automations"].last["status"] == "skipped"


def make(client, **over):
    body = {
        "name": "A rule",
        "trigger": "file",
        "conditions": {"type": "group", "op": "and", "items": [
            {"type": "condition", "field": "file_stalls", "op": "gte", "value": 3},
        ]},
        "actions": [{"name": "log_only", "params": {}}],
    }
    body.update(over)
    return client.post("/api/rules", json=body)


def test_a_rule_cannot_ask_what_its_subject_cannot_answer(client):
    claim(client)
    assert make(client).status_code == 200

    # A file has no device playing it.
    wrong = make(client, conditions={"type": "group", "op": "and", "items": [
        {"type": "condition", "field": "platform", "op": "any", "value": ["Roku"]},
    ]})
    assert wrong.status_code == 400 and "cannot be asked" in wrong.json()["detail"]

    # And nothing to stop.
    cannot = make(client, actions=[{"name": "terminate", "params": {}}])
    assert cannot.status_code == 400 and "not something that can be done" in cannot.json()["detail"]

    assert make(client, trigger="sideways").status_code == 400
    assert make(client, daily_cap=0).status_code == 400
    assert make(client, daily_cap=5).status_code == 200


def test_the_builder_offers_the_right_questions_for_each_trigger(client):
    claim(client)
    catalogue = client.get("/api/rules/fields").json()
    triggers = {t["key"] for t in catalogue["triggers"]}
    assert triggers == {"stream", "file", "issue", "replacement", "person"}

    by_key = {f["key"]: f for f in catalogue["fields"]}
    assert by_key["platform"]["triggers"] == ["stream"]
    assert "file" in by_key["file_stalls"]["triggers"]
    assert by_key["file_finding"]["options"] == "findings"
    assert any(o["value"] == "no_compatible_audio" for o in catalogue["options"]["findings"])

    actions = {a["name"]: a for a in client.get("/api/actions").json()}
    assert actions["terminate"]["triggers"] == ["stream"]
    assert "file" in actions["arr_search"]["triggers"]


# ---- what a rule can do about a report or a file -----------------------------

def seed_report(rating_key=1, status="open"):
    """A report about a file, as the sweep would find it."""
    from app.db import session_scope
    from app.models import Issue

    with session_scope() as db:
        row = Issue(seerr_id=None, source="local", issue_type="audio", status=status, rating_key=rating_key,
                    title="Trouble", media_type="movie", message="No sound at all", reporter_user_id=7,
                    created_at=datetime.now(UTC).replace(tzinfo=None), updated_at=datetime.now(UTC).replace(tzinfo=None))
        db.add(row)
        db.flush()
        return row.id


def test_a_rule_can_leave_a_note_on_a_report(client):
    from app.actions import registry
    from app.db import session_scope
    from app.models import Issue

    claim(client)
    issue_id = seed_report()
    action = registry.get("comment_on_issue")
    said = asyncio.run(action.execute({"subject": "issue", "issue_id": issue_id},
                                      {"message": "A better copy is on the way."}))
    assert "Trouble" in said
    with session_scope() as db:
        notes = json.loads(db.get(Issue, issue_id).comments)
    assert notes[-1]["message"] == "A better copy is on the way."
    # Signed, so nobody wonders who wrote it.
    assert notes[-1]["author"] == "a rule"


def test_a_rule_closes_the_reports_about_a_file_it_replaced(client):
    from app.actions import registry
    from app.db import session_scope
    from app.models import Issue

    claim(client)
    mine = seed_report(rating_key=1)
    someone_elses = seed_report(rating_key=2)
    action = registry.get("resolve_issue")
    # A replacement subject knows its file, not any particular report.
    said = asyncio.run(action.execute({"subject": "replacement", "rating_key": 1, "full_title": "Trouble"},
                                      {"note": "Replaced with a copy that has working audio."}))
    assert "1 report" in said
    with session_scope() as db:
        assert db.get(Issue, mine).status == "resolved"
        assert db.get(Issue, someone_elses).status == "open"


def test_an_automatic_grab_leaves_anything_it_would_have_to_ask_about():
    """The one action that spends bandwidth only takes a release that fixes
    something and that Radarr would import on its own."""
    from app.actions.registry import pick_release

    assert pick_release([]) is None
    assert pick_release([{"guid": "a", "indexer_id": 1, "fixes": [], "held": False, "blocked": False}]) is None
    assert pick_release([{"guid": "a", "indexer_id": 1, "fixes": ["Playable audio (AAC)"], "held": True}]) is None
    assert pick_release([{"guid": "a", "indexer_id": 1, "fixes": ["Playable audio (AAC)"], "blocked": True}]) is None
    good = {"guid": "b", "indexer_id": 2, "fixes": ["Playable audio (AAC)"], "held": False, "blocked": False}
    assert pick_release([{"guid": "a", "indexer_id": 1, "fixes": [], "blocked": True}, good]) is good


def test_only_the_actions_that_suit_a_trigger_are_offered(client):
    from app.actions import registry

    claim(client)
    for name, trigger, offered in [
        ("terminate", "stream", True), ("terminate", "file", False),
        ("queue_replacement", "file", True), ("queue_replacement", "stream", False),
        ("comment_on_issue", "issue", True), ("comment_on_issue", "file", False),
        ("resolve_issue", "replacement", True),
    ]:
        action = registry.get(name)
        assert (trigger in action.triggers) is offered, f"{name} on {trigger}"

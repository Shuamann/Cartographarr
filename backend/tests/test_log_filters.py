"""Filtering the Log.

Three hundred entries on one timeline and the only control was which of the
two tables to read. The thing that needs watching is the outcome: it is worked
out from three columns, in both the page and the endpoint, and filtering by
"stopped" has to select exactly the rows that read "stopped".
"""

import pathlib
import re
from datetime import UTC, datetime, timedelta

from tests.test_auth import claim

ROOT = pathlib.Path(__file__).resolve().parents[2]


def seed():
    from app.db import session_scope
    from app.models import AuditLog, EnforcementLog

    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as db:
        db.add(EnforcementLog(rule_name="Banned devices", action="terminate", result="terminated",
                              dry_run=False, username="viewer1", acted_at=now,
                              full_title="Star Wars", actor=None))
        db.add(EnforcementLog(rule_name="Banned addresses", action="terminate", result="terminated",
                              dry_run=True, username="viewer1", acted_at=now - timedelta(days=1),
                              full_title="Star Wars", actor=None))
        db.add(EnforcementLog(rule_name="Buffering", action="log_only", result="recorded",
                              dry_run=False, username="viewer2", acted_at=now - timedelta(days=9),
                              full_title="The Strain", actor=None))
        db.add(EnforcementLog(rule_name="No VPN", action="terminate", result="refused: requires plex",
                              dry_run=False, username="viewer2", acted_at=now - timedelta(days=2),
                              full_title="Dune", actor=None))
        db.add(AuditLog(action="settings.save", summary="Changed 1 setting", actor="admin", created_at=now))
        db.add(AuditLog(action="device.ban", summary="Banned a tv", actor="someone-else",
                        created_at=now - timedelta(days=9)))


def rows(client, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"/api/log?{query}").json()


def test_filtering_by_outcome_rule_person_and_date(client):
    claim(client)
    seed()

    stopped = rows(client, outcome="stopped")
    assert [r["rule_name"] for r in stopped] == ["Banned devices"]

    # Record only is its own answer, not a kind of stopped, even though the
    # action and the result both say terminate.
    assert [r["rule_name"] for r in rows(client, outcome="recorded+only")] == ["Banned addresses"]
    assert [r["rule_name"] for r in rows(client, outcome="refused")] == ["No VPN"]
    assert [r["rule_name"] for r in rows(client, outcome="logged")] == ["Buffering"]

    assert {r["rule_name"] for r in rows(client, rule="Banned devices")} == {"Banned devices"}
    assert {r.get("username") for r in rows(client, who="viewer2")} == {"viewer2"}

    # A person who only appears as an admin on a change.
    changes = rows(client, who="someone-else")
    assert [c["summary"] for c in changes] == ["Banned a tv"]

    # The last week, which leaves out the two nine days back.
    week = (datetime.now(UTC) - timedelta(days=7)).date().isoformat()
    recent = rows(client, start=week)
    assert "Buffering" not in {r.get("rule_name") for r in recent}
    assert "Banned a tv" not in {r.get("summary") for r in recent}
    # The three stream actions inside the week, and no count of the whole:
    # claiming the account writes an audit row of its own.
    assert {r.get("rule_name") for r in recent if r["kind"] == "stream"} == {
        "Banned devices", "Banned addresses", "No VPN",
    }


def test_a_filter_one_half_cannot_answer_drops_that_half(client):
    """Asking for one rule has no sensible answer among settings changes."""
    claim(client)
    seed()
    assert all(r["kind"] == "stream" for r in rows(client, rule="Banned devices"))
    assert all(r["kind"] == "stream" for r in rows(client, outcome="stopped"))
    assert all(r["kind"] == "change" for r in rows(client, area="settings"))
    assert [r["summary"] for r in rows(client, area="settings")] == ["Changed 1 setting"]


def test_searching_covers_both_halves(client):
    claim(client)
    seed()
    assert {r["full_title"] for r in rows(client, search="star")} == {"Star Wars"}
    assert [r["summary"] for r in rows(client, search="Banned a")] == ["Banned a tv"]


def test_the_options_only_offer_what_exists(client):
    claim(client)
    seed()
    options = client.get("/api/log/options").json()
    assert set(options["rules"]) == {"Banned devices", "Banned addresses", "Buffering", "No VPN"}
    assert {"viewer1", "viewer2", "admin", "someone-else"} <= set(options["people"])
    assert set(options["areas"]) >= {"settings", "device"}
    assert options["outcomes"][0] == "stopped"


def test_the_page_and_the_endpoint_agree_on_what_an_outcome_is(client):
    """Two copies of the same judgement, which have to stay in step or a
    filter selects rows that do not show what was asked for."""
    from app.routers.live import LOG_OUTCOMES

    page = (ROOT / "frontend/src/components/EnforcementLog.tsx").read_text(encoding="utf-8")
    body = page[page.index("function outcomeOf("):]
    body = body[: body.index("\n}")]
    labels = set(re.findall(r'label: "([^"]+)"', body))
    # "acted" is the fallback and is written as a column reference there.
    assert labels - {"acted"} <= set(LOG_OUTCOMES), labels
    for name in ("recorded only", "refused", "stopped", "logged", "notified"):
        assert name in labels, name
        assert name in LOG_OUTCOMES, name

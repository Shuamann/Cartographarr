from datetime import UTC, datetime, timedelta

from tests.test_auth import claim


def _add(db, model, column, days_ago: int, **fields):
    when = datetime.now(UTC) - timedelta(days=days_ago)
    db.add(model(**{column: when, **fields}))


def test_old_streams_go_and_recent_ones_stay(client):
    from app.db import session_scope
    from app.models import StreamEvent, StreamSession
    from app.services import housekeeping

    claim(client)
    client.put("/api/settings", json={"keep_streams_days": 30})
    with session_scope() as db:
        _add(db, StreamSession, "started_at", 400, session_key="old")
        _add(db, StreamSession, "started_at", 5, session_key="new")
        # A stream and its buffering are one record in two tables, so an old
        # stream whose events survived would look as though it played cleanly.
        _add(db, StreamEvent, "started_at", 400, session_key="old", kind="buffer")
        _add(db, StreamEvent, "started_at", 5, session_key="new", kind="buffer")

    gone = housekeeping.prune()
    assert gone["stream_sessions"] == 1 and gone["stream_events"] == 1
    with session_scope() as db:
        assert [s.session_key for s in db.query(StreamSession).all()] == ["new"]
        assert [e.session_key for e in db.query(StreamEvent).all()] == ["new"]


def test_the_logs_keep_to_their_own_setting(client):
    from app.db import session_scope
    from app.models import AuditLog, EnforcementLog
    from app.services import housekeeping

    claim(client)
    client.put("/api/settings", json={"keep_streams_days": 1, "keep_logs_days": 90})
    with session_scope() as db:
        _add(db, AuditLog, "created_at", 400, action="old")
        _add(db, AuditLog, "created_at", 30, action="recent")
        _add(db, EnforcementLog, "acted_at", 400, rule_name="old")
        _add(db, EnforcementLog, "acted_at", 30, rule_name="recent")

    gone = housekeeping.prune()
    # Signing in and saving a setting wrote their own audit rows, so count the
    # two this test put there rather than the whole table.
    assert gone["audit_log"] == 1 and gone["enforcement_log"] == 1
    with session_scope() as db:
        mine = [a.action for a in db.query(AuditLog).filter(AuditLog.action.in_(("old", "recent"))).all()]
        assert mine == ["recent"]
        assert [e.rule_name for e in db.query(EnforcementLog).all()] == ["recent"]


def test_zero_keeps_everything(client):
    from app.db import session_scope
    from app.models import AuditLog, StreamSession
    from app.services import housekeeping

    claim(client)
    client.put("/api/settings", json={"keep_streams_days": 0, "keep_logs_days": 0})
    with session_scope() as db:
        _add(db, StreamSession, "started_at", 4000, session_key="ancient")
        _add(db, AuditLog, "created_at", 4000, action="ancient")

    gone = housekeeping.prune()
    assert "stream_sessions" not in gone and "audit_log" not in gone
    with session_scope() as db:
        assert [s.session_key for s in db.query(StreamSession).all()] == ["ancient"]
        assert db.query(AuditLog).filter(AuditLog.action == "ancient").count() == 1


def test_pruning_runs_as_part_of_the_sync(client):
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "sync.py").read_text(encoding="utf-8")
    assert "housekeeping.prune()" in source

"""Stalls recorded before skipping was told apart from buffering."""

from datetime import UTC, datetime, timedelta

from tests.test_auth import claim


def seed():
    from app.db import session_scope
    from app.models import StreamEvent
    from app.services.stalls import SEEK_FILTERING_SINCE

    before = SEEK_FILTERING_SINCE.replace(tzinfo=None) - timedelta(days=2)
    after = SEEK_FILTERING_SINCE.replace(tzinfo=None) + timedelta(days=2)
    with session_scope() as db:
        for when in (before, before + timedelta(hours=1)):
            db.add(StreamEvent(kind="buffering", user_id=1, rating_key=5, seconds=9, started_at=when, ended_at=when))
        db.add(StreamEvent(kind="buffering", user_id=1, rating_key=5, seconds=9, started_at=after, ended_at=after))
        # Not a stall, so not this cleanup's business.
        db.add(StreamEvent(kind="stopped", user_id=1, rating_key=5, seconds=0, started_at=before, ended_at=before))


def test_old_stalls_are_counted_and_can_be_forgotten(client):
    from app.db import session_scope
    from app.models import StreamEvent
    from sqlalchemy import func, select

    claim(client)
    seed()

    answer = client.get("/api/library/stalls/unfiltered").json()
    assert answer["count"] == 2 and answer["since"] == "2026-09-17" and answer["newest"]

    assert client.delete("/api/library/stalls/unfiltered").json()["forgotten"] == 2
    assert client.get("/api/library/stalls/unfiltered").json()["count"] == 0
    with session_scope() as db:
        # The recent stall and the other kind of event are untouched.
        kinds = db.execute(select(StreamEvent.kind, func.count()).group_by(StreamEvent.kind)).all()
    assert sorted(kinds) == [("buffering", 1), ("stopped", 1)]


def test_viewers_cannot_forget_them(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "all")
    assert client.get("/api/library/stalls/unfiltered").status_code == 403
    assert client.delete("/api/library/stalls/unfiltered").status_code == 403


def test_a_clean_install_has_nothing_to_forget(client):
    claim(client)
    assert client.get("/api/library/stalls/unfiltered").json()["count"] == 0

"""New devices and shared signals: saying so, and clearing the backlog.

These are the two things the app exists to notice and the two it never
mentioned. Both sat on a page until somebody went and looked, and on the server
this was written against twenty eight devices had been waiting since 2023 and
not one signal had ever been reviewed.

Which is the other half of it. An alert is only worth anything if the normal
state is nought, and there was no way to reach nought from a backlog of twenty
eight except by clicking twenty eight times.
"""

import asyncio
from datetime import UTC, datetime

import pytest

from app.db import session_scope
from app.integrations.notify import AppriseNotifier
from app.models import Device, TravelFlag
from app.services import sync
from app.settings_store import trial
from tests.test_auth import claim


@pytest.fixture()
def sent(monkeypatch):
    out = []

    async def catch(self, title, body):  # noqa: ANN001
        out.append((title, body))
        return True

    monkeypatch.setattr(AppriseNotifier, "send", catch)
    return out


def tell(devices: int, signals: int) -> None:
    asyncio.run(sync._tell_about(devices, signals))


def a_flag(status: str, n: int = 0) -> TravelFlag:
    """A signal with the columns it cannot be without. The pair of history
    rows it was worked out from is the whole point of one, so they are not
    nullable and a test cannot skip them."""
    return TravelFlag(
        user_id=1,
        from_history_id=100 + n,
        to_history_id=200 + n,
        kind="travel",
        status=status,
        created_at=datetime.now(UTC),
    )


# ---- what it says ------------------------------------------------------------

def test_nothing_new_says_nothing(client, sent):
    with trial({"watch_alerts": True}):
        tell(0, 0)
    assert sent == []


def test_a_new_device_is_worth_saying(client, sent):
    with trial({"watch_alerts": True}):
        tell(1, 0)
    assert len(sent) == 1
    assert "1 new device" in sent[0][1]


def test_both_go_in_one_message(client, sent):
    """Two messages for one sync would be two notifications for one glance."""
    with trial({"watch_alerts": True}):
        tell(2, 3)
    assert len(sent) == 1
    body = sent[0][1]
    assert "2 new devices" in body and "3 shared account signals" in body


def test_switched_off_means_switched_off(client, sent):
    with trial({"watch_alerts": False}):
        tell(5, 5)
    assert sent == []


def test_a_sync_does_not_fail_because_apprise_did(client, monkeypatch):
    async def no(self, title, body):  # noqa: ANN001
        raise RuntimeError("Apprise is down")

    monkeypatch.setattr(AppriseNotifier, "send", no)
    with trial({"watch_alerts": True}):
        tell(1, 0)  # must not raise


# ---- clearing the backlog ----------------------------------------------------

def test_every_device_can_be_marked_reviewed_at_once(client):
    with session_scope() as db:
        for n in range(3):
            db.add(Device(machine_id=f"dev-{n}", user_id=1, is_new_unreviewed=True))
        db.add(Device(machine_id="old", user_id=1, is_new_unreviewed=False))

    claim(client)
    assert client.post("/api/devices/review-all").json() == {"reviewed": 3}

    with session_scope() as db:
        assert [d.is_new_unreviewed for d in db.query(Device).all()] == [False] * 4

    # Nothing left to do, and saying so is not an error.
    assert client.post("/api/devices/review-all").json() == {"reviewed": 0}


def test_every_signal_can_be_marked_reviewed_at_once(client):
    with session_scope() as db:
        for n in range(3):
            db.add(a_flag("new", n))
        db.add(a_flag("ignored", 9))

    claim(client)
    assert client.post("/api/travel-flags/review-all").json() == {"reviewed": 3}

    with session_scope() as db:
        assert sorted(f.status for f in db.query(TravelFlag).all()) == ["ignored", "reviewed", "reviewed", "reviewed"]


def test_clearing_is_admin_only(client):
    assert client.post("/api/devices/review-all").status_code in (401, 403)
    assert client.post("/api/travel-flags/review-all").status_code in (401, 403)


def test_a_signal_already_dealt_with_is_left_alone(client):
    """Ignored is a decision somebody made; reviewed-all must not undo it."""
    with session_scope() as db:
        db.add(a_flag("ignored"))

    claim(client)
    client.post("/api/travel-flags/review-all")

    with session_scope() as db:
        assert db.query(TravelFlag).one().status == "ignored"

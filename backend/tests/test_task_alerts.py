"""A job that has stopped working says so.

This is the one thing the app could not previously tell anyone. A background
job that breaks does not announce itself: the app simply stops having the right
answer, and the only sign is a page nobody has reason to open. On the server
this was written against, the update check had failed every half hour for the
life of the install and nothing had ever said a word about it.

The shape that matters is "once, then quiet": a job broken for a week is one
message, not three hundred.
"""

import asyncio

import pytest

from app import tasks
from app.integrations.notify import AppriseNotifier
from app.settings_store import trial


@pytest.fixture()
def sent(monkeypatch):
    """Every notification that would have gone out."""
    out = []

    async def catch(self, title, body):  # noqa: ANN001
        out.append((title, body))
        return True

    # Patched on the class, not the instance: undoing an instance patch leaves
    # the class's function on the object and the next test calls it unbound.
    monkeypatch.setattr(AppriseNotifier, "send", catch)
    return out


def a_task(key: str, fn):
    tasks.register(tasks.Task(key=key, name=key.replace("_", " "), description="", run=fn, interval=lambda: 60))
    return tasks.TASKS[key]


async def fails():
    raise RuntimeError("GitHub can't find the repository")


async def works():
    return "fine"


def test_one_failure_says_nothing(client, sent):
    task = a_task("t_one", fails)
    with trial({"task_alerts": True}):
        asyncio.run(tasks.run(task.key))
    assert task.consecutive == 1
    assert sent == []


def test_three_in_a_row_is_worth_a_message(client, sent):
    task = a_task("t_three", fails)
    with trial({"task_alerts": True}):
        for _ in range(tasks.FAILURES_BEFORE_ALERT):
            asyncio.run(tasks.run(task.key))

    assert len(sent) == 1
    title, body = sent[0]
    assert "failing" in title
    assert "GitHub can't find the repository" in body


def test_it_only_says_it_once(client, sent):
    """A job broken for a week is one message, not three hundred."""
    task = a_task("t_quiet", fails)
    with trial({"task_alerts": True}):
        for _ in range(20):
            asyncio.run(tasks.run(task.key))

    assert task.consecutive == 20
    assert len(sent) == 1


def test_coming_back_is_worth_knowing_too(client, sent):
    task = a_task("t_back", fails)
    with trial({"task_alerts": True}):
        for _ in range(tasks.FAILURES_BEFORE_ALERT):
            asyncio.run(tasks.run(task.key))
        task.run = works
        asyncio.run(tasks.run(task.key))

    assert [t for t, _ in sent] == ["t back is failing", "t back is working again"]
    assert task.consecutive == 0


def test_it_can_break_twice(client, sent):
    """After recovering, the next spell of failure is worth a message again."""
    task = a_task("t_twice", fails)
    with trial({"task_alerts": True}):
        for _ in range(tasks.FAILURES_BEFORE_ALERT):
            asyncio.run(tasks.run(task.key))
        task.run = works
        asyncio.run(tasks.run(task.key))
        task.run = fails
        for _ in range(tasks.FAILURES_BEFORE_ALERT):
            asyncio.run(tasks.run(task.key))

    assert len(sent) == 3


def test_switched_off_means_switched_off(client, sent):
    task = a_task("t_off", fails)
    with trial({"task_alerts": False}):
        for _ in range(tasks.FAILURES_BEFORE_ALERT + 2):
            asyncio.run(tasks.run(task.key))
    assert sent == []


def test_a_skipped_job_is_not_a_broken_one(client, sent):
    """Skipped is "nothing to do yet", which is most of them before setup."""

    async def skip():
        raise tasks.Skipped("Not set up yet")

    task = a_task("t_skip_alert", skip)
    with trial({"task_alerts": True}):
        for _ in range(5):
            asyncio.run(tasks.run(task.key))

    assert task.consecutive == 0
    assert sent == []


def test_a_failure_to_notify_does_not_fail_the_run(client, monkeypatch):
    """A job that failed must not then fail at saying so."""

    async def no(self, title, body):  # noqa: ANN001
        raise RuntimeError("Apprise is down too")

    monkeypatch.setattr(AppriseNotifier, "send", no)
    task = a_task("t_double", fails)
    with trial({"task_alerts": True}):
        for _ in range(tasks.FAILURES_BEFORE_ALERT):
            last = asyncio.run(tasks.run(task.key))

    assert last["status"] == "failed"

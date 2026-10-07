"""Telling somebody when the server stops answering.

The one thing a media server does that everybody notices, and the one thing
this app was not watching for: it reads activity every few seconds, so it knew
within a poll, and all it did was write a line in a log nobody has reason to
open.

The whole difficulty is in not crying wolf. Each test here was watched failing
against the mistake it names.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.services import reachable

T0 = datetime(2026, 10, 7, 2, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    """Catch what would have been sent instead of sending it."""
    sent: list[tuple[str, str]] = []

    class Notifier:
        @staticmethod
        async def send(heading, body):
            sent.append((heading, body))

    monkeypatch.setattr("app.integrations.notify.apprise_notifier", Notifier)
    reachable.forget()
    yield sent
    reachable.forget()


def test_a_restart_is_not_news(quiet):
    """A server restarting is unreachable for most of a minute. A message for
    every restart is a message nobody reads, which is how an alert that
    matters gets muted."""
    asyncio.run(reachable.seen("timed out", 5, T0))
    asyncio.run(reachable.seen("timed out", 5, T0 + timedelta(seconds=40)))
    asyncio.run(reachable.seen(None, 5, T0 + timedelta(seconds=50)))
    assert quiet == []


def test_a_real_outage_is_said_once(quiet):
    asyncio.run(reachable.seen("timed out", 5, T0))
    for seconds in (60, 120, 180, 240, 299):
        asyncio.run(reachable.seen("timed out", 5, T0 + timedelta(seconds=seconds)))
    assert quiet == [], "not yet: it has not been five minutes"
    asyncio.run(reachable.seen("timed out", 5, T0 + timedelta(minutes=5)))
    assert len(quiet) == 1
    assert "Cannot reach" in quiet[0][0]
    # Said once. The poll runs every few seconds and a warning repeated every
    # few seconds is the thing this exists to avoid.
    for minute in range(6, 40):
        asyncio.run(reachable.seen("timed out", 5, T0 + timedelta(minutes=minute)))
    assert len(quiet) == 1


def test_coming_back_is_said_with_how_long_it_was_gone(quiet):
    asyncio.run(reachable.seen("timed out", 5, T0))
    asyncio.run(reachable.seen("timed out", 5, T0 + timedelta(minutes=6)))
    asyncio.run(reachable.seen(None, 5, T0 + timedelta(minutes=20)))
    assert len(quiet) == 2
    assert "answering again" in quiet[1][0]
    assert "20 minutes" in quiet[1][1]


def test_coming_back_from_something_nobody_was_told_about_says_nothing(quiet):
    """There is nothing to take back. A blip is not news in either
    direction, and "the server is answering again" after a blip reads as
    though something had been wrong."""
    asyncio.run(reachable.seen("timed out", 5, T0))
    asyncio.run(reachable.seen(None, 5, T0 + timedelta(seconds=20)))
    assert quiet == []


def test_a_second_outage_after_a_recovery_is_said_again(quiet):
    """The state has to be cleared on recovery, or an outage a week later is
    silently swallowed as "already told"."""
    asyncio.run(reachable.seen("timed out", 5, T0))
    asyncio.run(reachable.seen("timed out", 5, T0 + timedelta(minutes=6)))
    asyncio.run(reachable.seen(None, 5, T0 + timedelta(minutes=10)))
    asyncio.run(reachable.seen("timed out", 5, T0 + timedelta(hours=5)))
    asyncio.run(reachable.seen("timed out", 5, T0 + timedelta(hours=5, minutes=6)))
    assert [q[0] for q in quiet] == [
        "Cannot reach the server", "The server is answering again", "Cannot reach the server",
    ]


def test_the_clock_restarts_after_a_moment_of_success(quiet):
    """Unreachable for four minutes, back for one poll, unreachable for four
    more is not an eight minute outage. Counting from the first failure ever
    seen would report one."""
    asyncio.run(reachable.seen("timed out", 5, T0))
    asyncio.run(reachable.seen("timed out", 5, T0 + timedelta(minutes=4)))
    asyncio.run(reachable.seen(None, 5, T0 + timedelta(minutes=4, seconds=10)))
    asyncio.run(reachable.seen("timed out", 5, T0 + timedelta(minutes=4, seconds=20)))
    asyncio.run(reachable.seen("timed out", 5, T0 + timedelta(minutes=8)))
    assert quiet == []


def test_what_the_server_said_is_passed_on(quiet):
    asyncio.run(reachable.seen("Connection refused", 5, T0))
    asyncio.run(reachable.seen("Connection refused", 5, T0 + timedelta(minutes=6)))
    assert "Connection refused" in quiet[0][1]


def test_the_message_does_not_claim_the_server_is_down(quiet):
    """Only one of three things has been ruled out. Saying "the server is
    down" is a claim this app cannot support, and the one that sends somebody
    to restart the wrong thing."""
    asyncio.run(reachable.seen("timed out", 5, T0))
    asyncio.run(reachable.seen("timed out", 5, T0 + timedelta(minutes=6)))
    heading, body = quiet[0]
    assert "down" not in heading.lower()
    assert "network" in body.lower()


def test_a_broken_notifier_does_not_break_the_poll(quiet, monkeypatch):
    class Broken:
        @staticmethod
        async def send(heading, body):
            raise RuntimeError("no notifier")

    monkeypatch.setattr("app.integrations.notify.apprise_notifier", Broken)
    asyncio.run(reachable.seen("timed out", 5, T0))
    assert asyncio.run(reachable.seen("timed out", 5, T0 + timedelta(minutes=6))) is None
    # And it does not try again every poll afterwards.
    assert asyncio.run(reachable.seen("timed out", 5, T0 + timedelta(minutes=7))) is None


def test_a_wait_of_zero_is_still_given_a_minute(quiet):
    """A floor, so a misconfigured zero does not send a message for every
    momentary timeout, which is the poll firing every few seconds."""
    asyncio.run(reachable.seen("timed out", 0, T0))
    asyncio.run(reachable.seen("timed out", 0, T0 + timedelta(seconds=30)))
    assert quiet == []
    asyncio.run(reachable.seen("timed out", 0, T0 + timedelta(seconds=61)))
    assert len(quiet) == 1

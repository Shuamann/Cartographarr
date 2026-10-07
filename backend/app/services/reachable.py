"""Telling somebody when the server stops answering.

The one thing a media server does that everybody notices, and the one thing
this app was not watching for. It reads activity every few seconds, so it
knows within a poll that the server has gone, and until now all it did was
write a line in a log nobody has reason to open. Plex falling over at two in
the morning was something you found out when somebody complained.

What this can honestly say is "this app could not reach the server", not "the
server is down". The container, the network between them and the server itself
are three different things and only one of them has been tested. The message
says which it is.

The shape is the one the disk warning and the job alert already use, because
it is the right shape: one message when it goes, one when it comes back,
nothing in between. A warning repeated every ten seconds is a warning that
gets muted.

The waiting is deliberate and is the whole difficulty. A server that is
restarting is unreachable for most of a minute, and a message for every
restart is a message nobody reads. The alert waits a few minutes of
unbroken failure, measured in time rather than in polls so it does not change
meaning when somebody changes the poll interval.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)

_state: dict[str, Any] = {"since": None, "told": False, "last_error": None}
"""When the first failure of this run was, whether anybody has been told, and
what it said. In memory: a restart of this app is not something to remember an
outage across, since it has just lost the thread anyway."""


def forget() -> None:
    """For tests, and for a settings change that should be able to warn again."""
    _state.update({"since": None, "told": False, "last_error": None})


def state() -> dict[str, Any]:
    """What is known right now, for a page that wants to say so."""
    return dict(_state)


def _words(gone: timedelta) -> str:
    minutes = int(gone.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} minutes" if minutes != 1 else "a minute"
    hours = minutes / 60
    return f"{hours:.1f} hours"


async def seen(error: str | None, after_minutes: int, at: datetime | None = None) -> str | None:
    """Record whether the last read worked, and say something if it should.

    Returns what was sent, or None. Called on every poll, so it has to be
    cheap and has to stay quiet.
    """
    now = at or datetime.now(UTC)

    if error is None:
        if not _state["told"]:
            # Never got as far as saying anything, so there is nothing to take
            # back. A blip is not news in either direction.
            forget()
            return None
        gone = now - _state["since"] if _state["since"] else timedelta(0)
        forget()
        return await _say(
            "The server is answering again",
            f"It was unreachable for about {_words(gone)}.",
        )

    if _state["since"] is None:
        _state["since"] = now
    _state["last_error"] = error
    if _state["told"]:
        return None
    if now - _state["since"] < timedelta(minutes=max(after_minutes, 1)):
        return None
    _state["told"] = True
    return await _say(
        "Cannot reach the server",
        f"Nothing has answered for {_words(now - _state['since'])}. This app, the network between them and the "
        f"server itself are three different things and only the first has been ruled out. It said: {error}",
    )


async def _say(heading: str, body: str) -> str | None:
    from app.integrations.notify import apprise_notifier

    try:
        await apprise_notifier.send(heading, body)
    except Exception:  # noqa: BLE001 - a broken notifier must not break the poll
        log.exception("could not send word that the server is unreachable")
        return None
    return heading

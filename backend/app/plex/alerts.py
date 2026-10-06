"""Plex telling us something changed, instead of us asking every five seconds.

The enforcer polls. A poll is a floor: whatever else happens, the rules and
the ban list are checked on a timer and nothing is missed. It is also a
ceiling on how fast a ban can land, because a device banned the moment it
starts playing keeps playing until the next poll comes round.

Plex has a websocket it pushes playback events down. Measured against a real
server: it connects in under a second, and an ongoing stream pings about every
ten seconds with its position, while a stream starting, stopping or being
paused arrives when it happens. That last one is the whole point. The nudge
costs nothing and turns up to five seconds of extra playback into none worth
measuring.

Deliberately a nudge and not a source. Nothing here reads a session or decides
anything. It asks the enforcer to run now rather than in a moment, and the
poll carries on underneath regardless, because a websocket that quietly dies
would otherwise be a feature that quietly stops.

It needs no new dependency: uvicorn already brings the websockets library,
which is why this does not use plexapi's own listener (that one wants
websocket-client, which is not installed).
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from typing import Any, Callable

log = logging.getLogger(__name__)

RETRY_SECONDS = 30.0
"""How long to wait before reconnecting. Long enough that a server which is
down does not spin, short enough that a restart is picked up without one."""

QUIET_SECONDS = 1.0
"""The least time between two nudges.

A busy server pings for every stream every ten seconds, and several arriving
together are one event as far as this is concerned. Without this a full house
would ask the enforcer to run a dozen times a second for no new information."""


def _url(settings) -> str:
    base = (settings.plex_url or "").rstrip("/")
    base = base.replace("https://", "wss://").replace("http://", "ws://")
    return f"{base}/:/websockets/notifications?X-Plex-Token={settings.plex_token}"


def worth_waking(message: dict[str, Any], seen: dict[str, str]) -> bool:
    """A state change, rather than a stream saying where it has got to.

    Every playing stream pings about every ten seconds with its position, and
    that ping says "playing", exactly as a stream that has just started does.
    The state alone cannot tell them apart, so the last state of each session
    is kept and only a change counts: a session nobody has seen before, or one
    whose state is not what it was. Those are the cases the poll would be slow
    to notice; a stream carrying on is not.

    `seen` is updated in place, and a session that has stopped is forgotten,
    so this does not grow forever on a busy server.
    """
    if message.get("type") != "playing":
        return False
    changed = False
    for item in message.get("PlaySessionStateNotification") or []:
        key, state = str(item.get("sessionKey") or ""), item.get("state")
        if not key or not state:
            continue
        if seen.get(key) != state:
            changed = True
        if state == "stopped":
            seen.pop(key, None)
        else:
            seen[key] = state
    return changed


async def listen(wake: Callable[[], Any], stopping: asyncio.Event) -> None:
    """Connect, and call wake() when Plex says something happened.

    Runs until `stopping` is set. Every failure is a reconnect, because the
    alternative is a listener that gives up quietly after a server reboot and
    leaves the app slower than it was with no sign of why.
    """
    import websockets

    from app.settings_store import current

    last = 0.0
    # The state each session was last seen in, so a position ping can be told
    # from a stream actually doing something.
    seen: dict[str, str] = {}
    nudges = 0
    while not stopping.is_set():
        settings = current()
        if not (settings.plex_token and settings.plex_url):
            await _sleep_or_stop(RETRY_SECONDS, stopping)
            continue
        url = _url(settings)
        try:
            context = ssl.create_default_context() if url.startswith("wss://") else None
            async with websockets.connect(url, ssl=context, open_timeout=20) as socket:
                log.info("listening to Plex for playback events")
                # A reconnect has missed whatever happened while it was away,
                # so nothing is assumed about what is playing.
                seen.clear()
                async for raw in socket:
                    if stopping.is_set():
                        break
                    try:
                        message = json.loads(raw).get("NotificationContainer", {})
                    except (ValueError, AttributeError):
                        continue
                    if not worth_waking(message, seen):
                        continue
                    now = asyncio.get_running_loop().time()
                    if now - last < QUIET_SECONDS:
                        continue
                    last = now
                    nudges += 1
                    # Once at info, so there is evidence in the log that this
                    # is doing something, and quietly after that.
                    log.log(
                        logging.INFO if nudges == 1 else logging.DEBUG,
                        "Plex says something changed, checking now",
                    )
                    try:
                        await wake()
                    except Exception:  # noqa: BLE001 - a bad sweep must not drop the connection
                        log.exception("could not act on a Plex event")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - every failure is a reconnect
            log.debug("Plex event stream closed (%s), trying again in %ss", exc, int(RETRY_SECONDS))
        await _sleep_or_stop(RETRY_SECONDS, stopping)


async def _sleep_or_stop(seconds: float, stopping: asyncio.Event) -> None:
    """Wait, but wake at once on shutdown rather than holding it up."""
    try:
        await asyncio.wait_for(stopping.wait(), timeout=seconds)
    except TimeoutError:
        pass

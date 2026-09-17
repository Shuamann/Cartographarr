"""Actions a rule can take.

The enforcer resolves by name and calls `execute`, so it never learns what any
particular action does. Adding a webhook, a notification or a script runner
later is one module plus an entry here, with no enforcer change, no migration.

`requires` ties into services/capabilities: an action whose requirements aren't
met is refused with a logged reason rather than failing silently somewhere
deeper.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.services import capabilities
from app.settings_store import current
from app.tautulli.client import TautulliClient

log = logging.getLogger(__name__)

Session = dict[str, Any]
Params = dict[str, Any]


@dataclass(frozen=True)
class Action:
    name: str
    label: str
    description: str
    execute: Callable[[Session, Params], Awaitable[str]]
    requires: tuple[str, ...] = ()
    param_schema: dict[str, Any] = field(default_factory=dict)


_REGISTRY: dict[str, Action] = {}


def register(action: Action) -> None:
    _REGISTRY[action.name] = action


def get(name: str) -> Action | None:
    return _REGISTRY.get(name)


def all_actions() -> list[Action]:
    return list(_REGISTRY.values())


def unmet(action: Action) -> list[str]:
    """Which of this action's requirements aren't satisfied right now."""
    missing = []
    for requirement in action.requires:
        if requirement == "plex_pass" and not capabilities.plex_pass_active():
            missing.append("plex_pass")
        elif requirement == "viewer_messaging":
            if not (current().viewer_message_url or "").strip():
                missing.append("viewer_messaging")
        elif requirement.startswith("integration:"):
            from app.integrations.notify import apprise_notifier, webhook_notifier

            available = {i.name: i for i in (apprise_notifier, webhook_notifier)}
            integration = available.get(requirement.split(":", 1)[1])
            if integration is None or not integration.configured():
                missing.append(requirement)
    return missing


# ---- terminate -------------------------------------------------------------

# Plex builds the on-screen text as
#   "<account> asked to stop your playback from this server: " + message + <id>
# Only the middle is ours. The UI shows the whole rendered string so this
# isn't a surprise.
DEFAULT_MESSAGE = "This device is not permitted to stream. Contact the server owner."


async def _terminate(session: Session, params: Params) -> str:
    session_key = session.get("session_key")
    if session_key is None:
        raise RuntimeError("session has no session_key")

    client = TautulliClient(current())
    try:
        await client.call(
            "terminate_session",
            session_key=session_key,
            message=params.get("message") or DEFAULT_MESSAGE,
        )
        return "terminated"
    finally:
        await client.aclose()


register(
    Action(
        name="terminate",
        label="Stop the stream",
        description="Ends playback and shows the viewer a message. Needs Plex Pass.",
        execute=_terminate,
        requires=("plex_pass",),
        param_schema={
            "message": {
                "type": "string",
                "label": "Message shown to the viewer",
                "default": DEFAULT_MESSAGE,
            }
        },
    )
)


# ---- log only --------------------------------------------------------------

async def _log_only(session: Session, _params: Params) -> str:
    log.info(
        "rule matched (log only): user=%s player=%s title=%s",
        session.get("username"),
        session.get("player"),
        session.get("full_title"),
    )
    return "logged"


def _describe(session: Session) -> str:
    who = session.get("friendly_name") or session.get("username") or "Someone"
    where = (session.get("geo") or {}).get("city") if isinstance(session.get("geo"), dict) else None
    parts = [
        f"{who} started {session.get('full_title')}",
        f"on {session.get('player')}" if session.get("player") else "",
        f"from {where}" if where else "",
    ]
    return " ".join(p for p in parts if p)


async def _notify(session: Session, params: Params) -> str:
    from app.integrations.notify import apprise_notifier

    title = params.get("title") or "Cartographarr"
    body = params.get("message") or _describe(session)
    return await apprise_notifier.send(title, body)


register(
    Action(
        name="notify",
        label="Send a notification",
        description="Messages wherever you have pointed Apprise, and leaves the stream alone.",
        execute=_notify,
        requires=("integration:apprise",),
        param_schema={
            "message": {
                "type": "string",
                "label": "Message (defaults to a description of the stream)",
            }
        },
    )
)


async def _webhook(session: Session, params: Params) -> str:
    from app.integrations.notify import webhook_notifier

    return await webhook_notifier.send(
        {
            "event": "rule_matched",
            "message": params.get("message") or _describe(session),
            "session": {
                key: session.get(key)
                for key in (
                    "session_key",
                    "user_id",
                    "username",
                    "friendly_name",
                    "machine_id",
                    "player",
                    "platform",
                    "ip_address",
                    "full_title",
                    "transcode_decision",
                )
            },
        }
    )


register(
    Action(
        name="webhook",
        label="Post to a webhook",
        description="Sends the stream details as JSON to the URL in Settings.",
        execute=_webhook,
        requires=("integration:webhook",),
        param_schema={"message": {"type": "string", "label": "Message"}},
    )
)


register(
    Action(
        name="log_only",
        label="Record it only",
        description="Writes to the enforcement log and leaves the stream alone.",
        execute=_log_only,
        requires=(),
        param_schema={},
    )
)


# ---- message the viewer ------------------------------------------------------------

DEFAULT_VIEWER_MESSAGE = (
    "Hi {name}, your stream of {title} on {player} matched a rule on this Plex server. "
    "Nothing has been stopped. If this is unexpected, get in touch with the server owner."
)


def viewer_address(template: str, email: str | None, username: str | None) -> str:
    """The Apprise URL for one person. Values are URL-quoted, so an address
    cannot add or change parameters of the URL around it."""
    from urllib.parse import quote

    if "{email}" in template and not email:
        raise RuntimeError("This viewer has no email address in Plex")
    return template.replace("{email}", quote(email or "", safe="@")).replace("{username}", quote(username or "", safe=""))


async def _message_viewer(session: Session, params: Params) -> str:
    import asyncio

    import apprise

    from app.db import session_scope
    from app.models import User

    template = (current().viewer_message_url or "").strip()
    if not template:
        raise RuntimeError("No viewer message address in Settings")
    user = None
    try:
        uid = int(session.get("user_id"))
    except (TypeError, ValueError):
        uid = None
    if uid is not None:
        with session_scope() as db:
            user = db.get(User, uid)
            if user is not None:
                db.expunge(user)
    name = session.get("friendly_name") or session.get("username") or "there"
    body = (params.get("message") or DEFAULT_VIEWER_MESSAGE).format_map(
        _Blank(name=name, title=session.get("full_title") or "a title", player=session.get("player") or "your device")
    )
    url = viewer_address(template, user.email if user else None, (user.username if user else None) or session.get("username"))
    client = apprise.Apprise()
    if not client.add(url):
        raise RuntimeError("Apprise did not understand the viewer message address")
    sent = await asyncio.to_thread(client.notify, title=params.get("title") or "About your Plex stream", body=body)
    if not sent:
        raise RuntimeError("Apprise reported a failure")
    return "messaged the viewer"


class _Blank(dict):
    """format_map that leaves unknown {placeholders} as they are."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


register(
    Action(
        name="message_viewer",
        label="Message the viewer",
        description="Sends the person watching a message, by email or whatever the viewer message address in Settings "
                    "points at. Leaves the stream alone.",
        execute=_message_viewer,
        requires=("viewer_messaging",),
        param_schema={
            "title": {"type": "string", "label": "Subject", "default": "About your Plex stream"},
            "message": {
                "type": "string",
                "label": "Message ({name}, {title} and {player} are filled in)",
                "default": DEFAULT_VIEWER_MESSAGE,
            },
        },
    )
)

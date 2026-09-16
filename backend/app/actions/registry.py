"""Actions a rule can take.

The enforcer resolves by name and calls `execute`, so it never learns what any
particular action does. Adding a webhook, a notification or a script runner
later is one module plus an entry here — no enforcer change, no migration.

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
        elif requirement.startswith("integration:"):
            # Integrations land in a later phase; treat as unmet until then.
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

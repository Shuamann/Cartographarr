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
    # What this can be the answer to. Stopping a stream needs a stream;
    # tagging a file does not care whether anyone is watching.
    triggers: tuple[str, ...] = ("stream",)


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
        triggers=("stream", "file", "issue", "replacement", "person")
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
        triggers=("stream", "file", "issue", "replacement", "person")
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
        triggers=("stream", "file", "issue", "replacement", "person")
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


# ---- handing a file back to Radarr or Sonarr -------------------------------
#
# These act on a file rather than a stream, so they are what a rule about a
# file, a report or a replacement can do. Neither deletes anything: a search
# asks for a better release, which Radarr or Sonarr only takes if their own
# quality profile rates it higher, and a tag marks it for you to look at.

async def _arr_target(subject: Session) -> tuple[Any, Any, int | None, int | None, str]:
    """Which service, which id, and which episode this subject is about."""
    from app.db import session_scope
    from app.integrations import arr
    from app.models import MediaItem

    rating_key = subject.get("rating_key")
    if not rating_key:
        raise LookupError("Nothing to hand over: this is not about a file")
    with session_scope() as db:
        item = db.get(MediaItem, int(rating_key))
        if item is None or item.title is None:
            raise LookupError("That file is not in the library any more")
        service = arr.for_media_type(item.media_type)
        episodic = item.media_type == "episode"
        show = db.get(MediaItem, item.grandparent_rating_key) if episodic and item.grandparent_rating_key else None
        external = (show.tvdb_id if show else None) if episodic else (
            item.tmdb_id if service.name == "radarr" else item.tvdb_id
        )
        title = item.full_title or item.title
        season, episode = item.parent_media_index, item.media_index
    if not service.configured():
        raise LookupError(f"{service.label} is not set up")
    if not external:
        raise LookupError(f"No id for {title}, so {service.label} cannot find it")
    return service, external, season, episode, title


async def _arr_search(session: Session, _params: Params) -> str:
    service, external, season, episode, title = await _arr_target(session)
    await service.search(external, season, episode)
    return f"asked {service.label} to look for a better {title}"


async def _arr_tag(session: Session, _params: Params) -> str:
    service, external, _season, _episode, title = await _arr_target(session)
    await service.tag(external)
    return f"tagged {title} in {service.label}"


register(
    Action(
        name="arr_search",
        label="Ask Radarr or Sonarr to look again",
        description=(
            "Asks for a search. Whichever one owns the title only takes a release its own quality profile "
            "rates higher, so nothing is replaced by something worse."
        ),
        execute=_arr_search,
        triggers=("file", "issue", "replacement"),
    )
)

register(
    Action(
        name="arr_tag",
        label="Tag it in Radarr or Sonarr",
        description="Adds the cartographarr-replace tag, so it can be found later and dealt with by hand.",
        execute=_arr_tag,
        triggers=("file", "issue", "replacement"),
    )
)

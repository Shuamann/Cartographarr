"""Actions a rule can take.

The enforcer resolves by name and calls `execute`, so it never learns what any
particular action does. Adding a webhook, a notification or a script runner
later is one module plus an entry here, with no enforcer change, no migration.

`requires` ties into services/capabilities: an action whose requirements aren't
met is refused with a logged reason rather than failing silently somewhere
deeper.
"""

from __future__ import annotations

import asyncio
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


# ---- banning ---------------------------------------------------------------
#
# A rule could stop a stream and could not stop it coming back, so the same
# device could be caught and stopped every evening for ever while the only way
# to end it was to go and ban it by hand. The ban lists already have timed
# entries, an expiry sweep, reasons and an audit trail; this joins the two.
#
# Timed by default rather than permanent. A rule acting on its own should not
# make a decision nobody can see being made, and a day is long enough to stop
# a pattern while being short enough to forgive a mistake.

BAN_HOURS = {
    "1": 1.0,
    "24": 24.0,
    "168": 24.0 * 7,
    "720": 24.0 * 30,
    "0": 0.0,
}
"""The lengths a rule may ban for, as the dropdown offers them. 0 is for good,
which is last on the list and not the default on purpose."""

DEFAULT_BAN_HOURS = "24"


def _ban_length(params: Params) -> float | None:
    """Hours, or None for a permanent ban."""
    hours = BAN_HOURS.get(str(params.get("hours") or DEFAULT_BAN_HOURS), 24.0)
    return hours or None


async def _ban_device(session: Session, params: Params) -> str:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import desc, select

    from app.db import session_scope
    from app.models import BannedDevice, Device

    machine_id = session.get("machine_id")
    if not machine_id:
        raise RuntimeError("this stream has no device to ban")

    hours = _ban_length(params)
    with session_scope() as db:
        if db.get(BannedDevice, machine_id) is not None:
            return "already banned"
        # A device is keyed on the machine and the account together, since two
        # people can share one box, so this asks for the most recent rather
        # than fetching by key.
        known = db.execute(
            select(Device).where(Device.machine_id == machine_id).order_by(desc(Device.last_seen)).limit(1)
        ).scalar_one_or_none()
        label = session.get("player") or (known.player if known else None) or str(machine_id)[:12]
        db.add(BannedDevice(
            machine_id=machine_id,
            label=label,
            user_id=_as_int(session.get("user_id")),
            reason=params.get("reason") or "Banned by a rule",
            banned_by="a rule",
            banned_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=hours) if hours else None,
        ))
    return f"banned {label}" + (f" for {hours:g} hours" if hours else " for good")


async def _ban_address(session: Session, params: Params) -> str:
    from datetime import UTC, datetime, timedelta

    from app.db import session_scope
    from app.models import BannedAddress

    address = session.get("ip_address")
    if not address:
        raise RuntimeError("this stream has no address to ban")

    hours = _ban_length(params)
    with session_scope() as db:
        if db.get(BannedAddress, address) is not None:
            return "already banned"
        where = session.get("geo") or {}
        db.add(BannedAddress(
            address=address,
            label=", ".join(x for x in [where.get("city"), where.get("country")] if x) or None
            if isinstance(where, dict) else None,
            user_id=_as_int(session.get("user_id")),
            reason=params.get("reason") or "Banned by a rule",
            banned_by="a rule",
            banned_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=hours) if hours else None,
        ))
    return f"banned {address}" + (f" for {hours:g} hours" if hours else " for good")


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


_BAN_PARAMS = {
    "hours": {
        "type": "choice",
        "label": "For how long",
        "default": DEFAULT_BAN_HOURS,
        "options": [
            {"value": "1", "label": "1 hour"},
            {"value": "24", "label": "1 day"},
            {"value": "168", "label": "1 week"},
            {"value": "720", "label": "30 days"},
            {"value": "0", "label": "Permanently"},
        ],
    },
    "reason": {"type": "string", "label": "Reason, for the ban list and the Log"},
}


register(
    Action(
        name="ban_device",
        label="Ban the device",
        description="Adds it to the ban list, so the next stream from it is stopped without this rule having to "
                    "match again. Timed unless you say otherwise.",
        execute=_ban_device,
        requires=(),
        param_schema=_BAN_PARAMS,
    )
)

register(
    Action(
        name="ban_address",
        label="Ban the address",
        description="The connection rather than the box, for a device that comes back under a new identifier. "
                    "Exactly the address this stream came from, never a range.",
        execute=_ban_address,
        requires=(),
        param_schema=_BAN_PARAMS,
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


# ---- asking for a replacement ------------------------------------------------
#
# The one action that spends somebody's bandwidth without being asked, so it is
# the most careful: it only grabs a release that fixes something the file is
# actually wrong about, never one Radarr or Sonarr would refuse or hold, and it
# answers to the day's limit on automatic downloads in Settings before it is
# ever called. What it queues then follows the same path as one queued by hand,
# and shows up in Replacements with "a rule" as who asked.

def pick_release(releases: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The one release worth taking without asking anybody.

    `compare_releases` has already sorted by how many of the file's problems
    each would fix. Anything blocked, held for a manual import, or that fixes
    nothing is not something to grab while nobody is watching.
    """
    for release in releases:
        if release.get("blocked") or release.get("held"):
            continue
        if not release.get("fixes"):
            continue
        if not release.get("guid") or release.get("indexer_id") is None:
            continue
        return release
    return None


async def _queue_replacement(session: Session, params: Params) -> str:
    import asyncio
    import json

    from datetime import UTC, datetime

    from fastapi import HTTPException

    from app.db import session_scope
    from app.models import Replacement
    from app.routers.library import _arr_target
    from app.services import replacements
    from app.services.automations import AUTOMATION

    rating_key = session.get("rating_key")
    if not rating_key:
        raise LookupError("Nothing to replace: this is not about a file")
    try:
        target, service = await _arr_target(int(rating_key))
    except HTTPException as exc:  # the route's own words, which are the clearest ones
        raise LookupError(str(exc.detail)) from exc

    found, episode_id = await service.locate(target["external"], target["season"], target["episode"])
    raw = await asyncio.wait_for(service.releases(found["id"], episode_id), timeout=150)
    title = target["item"].get("title") or session.get("full_title") or "it"
    ranked = replacements.compare_releases(
        raw,
        {**target["item"], "findings": session.get("findings") or []},
        target["item"].get("duration"),
        int(current().library_bitrate_threshold_mbps * 1000),
    )
    chosen = pick_release(ranked)
    if chosen is None:
        return f"left {title} alone: nothing on offer would fix what is wrong with it"

    existing = await service.current_file(found["id"], episode_id)
    await service.grab(chosen["guid"], int(chosen["indexer_id"]))
    now = datetime.now(UTC)
    with session_scope() as db:
        db.add(Replacement(
            rating_key=int(rating_key), title=title, service=service.name, arr_id=found["id"],
            episode_id=episode_id, guid=chosen["guid"], indexer_id=int(chosen["indexer_id"]), status="queued",
            release=json.dumps(chosen),
            current=json.dumps({**target["item"], "arr_file_id": (existing or {}).get("id")}),
            created_by=AUTOMATION, created_at=now, updated_at=now,
        ))
    return f"asked {service.label} for {chosen['title']} to replace {title}: {', '.join(chosen['fixes'])}"


register(
    Action(
        name="queue_replacement",
        label="Grab a better copy",
        description=(
            "Searches, and takes the best release that would fix what is wrong with the file. Nothing held for a "
            "manual import, nothing that fixes none of it, and never more than the day's limit in Settings. "
            "It appears in Replacements as asked for by a rule."
        ),
        execute=_queue_replacement,
        triggers=("file", "issue"),
    )
)


# ---- answering a report ------------------------------------------------------

AUTHOR = "a rule"
"""Whose name goes on a note or a resolution a rule left. The same words as
the Replacements list uses, so nobody has to work out where it came from."""


async def _comment_on_issue(session: Session, params: Params) -> str:
    from app.services import issues

    issue_id = session.get("issue_id")
    if not issue_id:
        raise LookupError("Nothing to comment on: this is not about a report")
    message = (params.get("message") or "").strip()
    if not message:
        raise LookupError("A note with nothing in it says nothing")
    title, _notes, warning = await issues.add_comment(int(issue_id), message, AUTHOR)
    return f"commented on {title}" + (f" ({warning})" if warning else "")


async def _resolve_issue(session: Session, params: Params) -> str:
    """Close a report.

    From a report, it closes that one. From a file or a replacement, it closes
    whatever was reported about that file, which is the useful direction: a
    better copy has just landed, so what people said about the old one is
    answered.
    """
    from app.services import issues

    note = (params.get("note") or "").strip() or "Closed by a rule."
    issue_id = session.get("issue_id")
    if issue_id:
        title, warning = await issues.mark(int(issue_id), "resolved", AUTHOR, note)
        return f"marked {title} resolved" + (f" ({warning})" if warning else "")
    rating_key = session.get("rating_key")
    if not rating_key:
        raise LookupError("Nothing to resolve: this is not about a report or a file")
    closed = await issues.resolve_for_file(int(rating_key), note)
    if not closed:
        return "nothing was open about that file"
    return f"resolved {len(closed)} report{'s' if len(closed) > 1 else ''} about {session.get('full_title') or 'it'}"


register(
    Action(
        name="comment_on_issue",
        label="Add a note to the report",
        description="Leaves a note on the report, here and in Seerr, signed as coming from a rule.",
        execute=_comment_on_issue,
        param_schema={"message": {"type": "string", "label": "What the note says"}},
        triggers=("issue",),
    )
)

register(
    Action(
        name="resolve_issue",
        label="Mark the report resolved",
        description=(
            "Closes the report, here and in Seerr, with a note saying why. Asked from a file or a replacement it "
            "closes whatever was reported about that file, which is what a landed replacement usually answers."
        ),
        execute=_resolve_issue,
        param_schema={"note": {"type": "string", "label": "Why it is being closed"}},
        triggers=("issue", "file", "replacement"),
    )
)


# ---- tidying a file's tracks on a rule ----------------------------------------
#
# The same work as the button on a file card, driven by a rule instead of a
# person: convert styled subtitles, drop the languages nobody here reads, put
# the right audio first. It rewrites somebody's only copy, so it answers to the
# rule's daily cap, it starts as record only like every rule, and the job
# itself checks the result against the original before replacing anything.


async def _tidy_file(session: Session, params: Params) -> str:
    from app.services import mediafix

    rating_key = session.get("rating_key")
    if not rating_key:
        raise LookupError("Nothing to tidy: this is not about a file")

    asked = [part.strip() for part in str(params.get("steps") or "").replace(";", ",").split(",") if part.strip()]
    with_item = _item(int(rating_key))
    offered = [step["key"] for step in mediafix.plan(with_item)["steps"]]
    steps = [key for key in (asked or offered) if key in offered]
    if not steps:
        return "nothing to tidy about this file"

    job = await asyncio.to_thread(mediafix.queue, int(rating_key), steps, AUTHOR)
    mediafix.start_worker()
    return f"queued tidying ({', '.join(steps)}), job {job}"


def _item(rating_key: int):
    from app.db import session_scope
    from app.models import MediaItem

    with session_scope() as db:
        item = db.get(MediaItem, rating_key)
        if item is None:
            raise LookupError("That file is not in the library any more")
        db.expunge(item)
        return item


register(
    Action(
        name="tidy_file",
        label="Tidy the tracks",
        description=(
            "Runs the same tidying as the button on a file card: styled subtitles to SRT, duplicate and unwanted "
            "language tracks dropped, the preferred audio put first, an AC3 track added where nothing can play what "
            "is there. Leave the steps blank to do whatever that file needs. Nothing re-encodes the picture, and the "
            "result is checked against the original before it replaces anything."
        ),
        execute=_tidy_file,
        param_schema={
            "steps": {
                "type": "string",
                "label": "Which steps, comma separated (blank for whatever the file needs)",
            }
        },
        triggers=("file", "issue"),
    )
)

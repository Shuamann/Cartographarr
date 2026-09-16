"""Who you share the server with, and what they can see.

The only part of Cartographarr that talks to plex.tv rather than Tautulli, and
the only part that does something irreversible. Unsharing cannot be undone from
here: it needs a fresh invitation that the other person has to accept.

python-plexapi does the talking. The sharing endpoints are genuinely awkward,
in particular the section ids in the payload come from
`plex.tv/api/servers/{machineId}` and are not the local library keys nor
Tautulli's section_id. plexapi already maps them, which is reason enough not to
hand-roll the HTTP.

Everything here is synchronous and blocking, so callers run it off the event
loop.
"""

from __future__ import annotations

import logging
from typing import Any

from app.settings_store import current

log = logging.getLogger(__name__)


class NotConfigured(RuntimeError):
    pass


def configured() -> bool:
    return bool(current().plex_token)


def _account():
    if not configured():
        raise NotConfigured("Add a Plex token in Settings to manage sharing")
    from plexapi.myplex import MyPlexAccount

    return MyPlexAccount(token=current().plex_token)


def _server(account):
    """The server being shared.

    Preferring the stored machine identifier, which Tautulli reports, so this
    does not guess when someone owns more than one server.
    """
    wanted = current().plex_machine_identifier
    resources = [r for r in account.resources() if "server" in (r.provides or "")]
    if wanted:
        for resource in resources:
            if resource.clientIdentifier == wanted:
                return resource
    if len(resources) == 1:
        return resources[0]
    raise RuntimeError(
        "Could not tell which server to use. Set the Plex server id in Settings."
    )


def status() -> dict:
    if not configured():
        return {"ok": False, "detail": "Not set up"}
    try:
        account = _account()
        server = _server(account)
        return {"ok": True, "detail": f"Signed in as {account.username}", "server": server.name}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc)}


def list_shares() -> list[dict]:
    """Everyone the server is shared with, and which libraries they see."""
    account = _account()
    server = _server(account)
    out: list[dict] = []

    for user in account.users():
        sections = [
            section.title
            for share in user.servers
            if share.machineIdentifier == server.clientIdentifier
            for section in share.sections()
            if section.shared
        ]
        # Someone with no shares on this server is a friend of the account
        # rather than a viewer here, and listing them would be noise.
        if not any(s.machineIdentifier == server.clientIdentifier for s in user.servers):
            continue

        out.append(
            {
                "id": user.id,
                "username": user.username or user.title,
                "email": user.email,
                "thumb": user.thumb,
                "home": bool(getattr(user, "home", False)),
                "sections": sections,
            }
        )
    return out


def all_sections() -> list[str]:
    account = _account()
    server = _server(account).connect()
    return [section.title for section in server.library.sections()]


def set_sections(username: str, sections: list[str]) -> dict:
    """Replace which libraries someone can see."""
    account = _account()
    server = _server(account)
    account.updateFriend(username, server, sections=sections)
    log.info("sharing: %s now sees %s", username, sections or "nothing")
    # Read back rather than trusting the write, so the UI reflects what Plex
    # actually did.
    return {"username": username, "sections": _sections_for(username)}


def _sections_for(username: str) -> list[str]:
    for share in list_shares():
        if share["username"] == username:
            return share["sections"]
    return []


def unshare(username: str) -> dict:
    """Remove someone's access entirely.

    Irreversible from here. Getting them back means a fresh invitation that
    they have to accept.
    """
    account = _account()
    account.removeFriend(username)
    log.warning("sharing: removed %s", username)
    return {"username": username, "removed": True}


def run(fn, *args: Any):
    """Run one of these off the event loop, since plexapi blocks."""
    import asyncio

    return asyncio.to_thread(fn, *args)

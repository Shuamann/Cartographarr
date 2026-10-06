"""Who the server is shared with, and what the libraries are called.

Both were read through Tautulli, and on an install with Plex alone the people
list held only those who had pressed play: somebody shared with who has never
watched anything was unknown until they did.

The id is the whole difficulty, and it was measured rather than assumed. Plex
offers two lists of accounts and they are not the same numbers:

    the share list   34 ids, every one of them already in the users table
    systemAccounts   47 ids, 13 of them in no id space this app uses

systemAccounts numbers accounts against the server, where the owner is 1. The
share list uses the Plex account id, which is what history, every ban and
every privacy scope key on. So the share list is the source and the other one
is a trap, and the owner is added separately because an owner is not shared
with themselves.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


def _row(user: Any, home: bool = False, sections: list[str] | None = None) -> dict[str, Any]:
    return {
        "user_id": int(user.id),
        "username": getattr(user, "username", None) or None,
        "friendly_name": getattr(user, "title", None) or getattr(user, "username", None) or None,
        "email": getattr(user, "email", None) or None,
        "thumb": getattr(user, "thumb", None) or None,
        "is_active": True,
        "is_home_user": bool(getattr(user, "home", home)),
        # Tautulli's word for someone it has dropped from its own list. Nothing
        # read from Plex has ever been in Tautulli's list, so it is not true of
        # them and saying so would put a warning on every person.
        "deleted_in_tautulli": False,
        "shared_libraries": json.dumps(sections or []),
        "allow_sync": bool(getattr(user, "allowSync", False)) or None,
    }


def read(machine_identifier: str | None = None) -> list[dict[str, Any]]:
    """Everyone with access, in the shape the user table already holds.

    Blocking, because plexapi is. Call it in a worker thread.
    """
    from app.plex.server import server

    plex = server()
    account = plex.myPlexAccount()
    server_id = machine_identifier or getattr(plex, "machineIdentifier", None)

    rows = [_row(account, home=True)]
    for user in account.users():
        # Which libraries this person can see, on this server rather than on
        # whichever one plexapi happens to list first. Somebody shared with on
        # two servers has different access on each.
        sections: list[str] = []
        for share in getattr(user, "servers", None) or []:
            if server_id and getattr(share, "machineIdentifier", None) != server_id:
                continue
            try:
                sections = [str(s.id) for s in share.sections() if getattr(s, "id", None)]
            except Exception as exc:  # noqa: BLE001 - access review is a bonus on the list itself
                log.debug("could not read shared sections for %s: %s", user.id, exc)
            break
        rows.append(_row(user, sections=sections))
    return rows


def libraries() -> list[dict[str, Any]]:
    """The sections, named, in the shape the libraries table holds."""
    from app.plex.server import server

    return [
        {"section_id": int(section.key), "name": section.title or None, "type": section.type or None}
        for section in server().library.sections()
        if str(getattr(section, "key", "")).isdigit()
    ]

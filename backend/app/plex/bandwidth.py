"""What Plex measured each device using, a day at a time.

Plex has kept this since long before this app existed. On the server it was
written against: four years, a row per day per account per device, with local
traffic counted apart from remote. Nothing else here reaches back like that,
because the minute by minute samples only start when this version is
installed, and Tautulli never had it at all since Tautulli only knows what it
was running to watch.

Two ids need care and both were measured rather than assumed.

The account is the Plex account id, which is what history and every ban key
on, with one exception: the owner appears as 1, Plex's own numbering for the
server. Thirty three of the thirty four accounts in the figures were already
in the user table and the odd one out was that 1, so the owner is mapped and
the rest are taken as they come.

The device is Plex's own number, not the client identifier a device is known
by everywhere else. Every one of the 121 in the figures could be named through
the device list, so the identifier is looked up and stored beside the number.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

DAILY = 3
"""Plex's timespan for a day.

Measured: 1 is a month and reaches back four years, 2 is a week and reaches
back one, 3 is a day and reaches back four years, 4 is an hour and reaches
back five weeks. A day over four years is the one worth keeping, at 31,733
rows, which is nothing to store and the right grain for a question about who
uses the upload.
"""


def _devices(plex: Any) -> dict[int, str]:
    """Plex's device number to the client identifier it is known by."""
    found: dict[int, str] = {}
    for device in plex.query("/devices").findall(".//Device"):
        number, identifier = device.get("id"), device.get("clientIdentifier")
        if number and identifier:
            found[int(number)] = identifier
    return found


def read(timespan: int = DAILY) -> list[dict[str, Any]]:
    """The figures, as rows for the plex_bandwidth table.

    Blocking, because plexapi is. Call it in a worker thread.
    """
    from app.plex.server import server

    plex = server()
    names = _devices(plex)
    owner = getattr(plex.myPlexAccount(), "id", None)

    rows: list[dict[str, Any]] = []
    for row in plex.query(f"/statistics/bandwidth?timespan={timespan}").findall(".//StatisticsBandwidth"):
        at, account, device = row.get("at"), row.get("accountID"), row.get("deviceID")
        if not (at and account and device):
            continue
        account = int(account)
        rows.append({
            "at": int(at),
            # Plex calls the owner 1 against the server. Everybody else is
            # already the number this app files their plays under.
            "user_id": owner if account == 1 and owner else account,
            "device_id": int(device),
            "machine_id": names.get(int(device)),
            "lan": bool(int(row.get("lan") or 0)),
            "bytes": int(row.get("bytes") or 0),
        })
    return rows


async def store() -> dict[str, int]:
    """Fetch and keep them. Safe to run again: the rows are keyed as Plex
    gives them and no two share a key."""
    import asyncio

    from app.db import session_scope
    from app.models import PlexBandwidth
    from app.services.sync import _upsert

    rows = await asyncio.to_thread(read)
    if not rows:
        return {"days": 0, "rows": 0}
    with session_scope() as db:
        _upsert(db, PlexBandwidth, rows)
    days = len({r["at"] for r in rows})
    log.info("plex bandwidth: %d rows across %d days", len(rows), days)
    return {"rows": len(rows), "days": days}

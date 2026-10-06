"""Which devices clearly belong to one account.

The shared account signal fires when one account plays from two places too far
apart to be the same person. That is the right rule and it catches real
sharing. It also catches the ordinary life of a household: a phone on mobile
data, a laptop carried to work, a VPN whose exit moves between cities. Those
are the same person every time and the signal has no way to know it.

Trusting a device tells it. The flag is set by hand, but nobody is going to
tick two hundred devices, so this works out which ones are not in question and
offers them. The tick stays the final word: this suggests, it never decides.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.db import session_scope

log = logging.getLogger(__name__)

ENOUGH_PLAYS = 20
"""Below this there is no history to draw a conclusion from, only a guess.

A device with three plays on one account has not shown anything; it is simply
new. Twenty is a few weeks of ordinary use and is the point at which a device
that has never once been used by anybody else is making a statement."""

SETTLED_DAYS = 30
"""And it has to have been around a while.

A device bought yesterday with twenty plays in a day is somebody binge
watching, not an established part of a household, and the whole question this
answers is which devices are established."""


def suggestions() -> list[dict]:
    """Devices with a real history on one account and none on any other.

    The test is deliberately narrow. A device used by two accounts is exactly
    the ambiguous case the signal exists for, so it is not offered whatever
    the counts say, and no amount of history on one side makes up for it.
    """
    from app.models import Device

    now = datetime.now(UTC).timestamp()
    with session_scope() as db:
        # A machine id appearing against more than one account is shared, or is
        # one person's device that somebody else has signed into. Either way it
        # is not something to vouch for.
        shared = {
            machine_id
            for (machine_id,) in db.execute(
                select(Device.machine_id).group_by(Device.machine_id).having(func.count() > 1)
            ).all()
        }
        rows = db.execute(
            select(Device).where(
                Device.trusted_at.is_(None),
                Device.play_count >= ENOUGH_PLAYS,
                Device.machine_id.not_in(shared) if shared else Device.machine_id.is_not(None),
            ).order_by(Device.play_count.desc())
        ).scalars().all()
        return [
            {
                "machine_id": d.machine_id,
                "user_id": d.user_id,
                "player": d.player,
                "platform": d.platform,
                "plays": d.play_count,
                "first_seen": d.first_seen,
                "last_seen": d.last_seen,
            }
            for d in rows
            if d.first_seen and (now - d.first_seen) >= SETTLED_DAYS * 86400
        ]


def set_trusted(machine_id: str, user_id: int | None, on: bool, who: str | None) -> int:
    """Vouch for a device, or take it back. Returns rows changed."""
    from sqlalchemy import update

    from app.models import Device

    values = {"trusted_at": datetime.now(UTC), "trusted_by": who} if on else {"trusted_at": None, "trusted_by": None}
    with session_scope() as db:
        stmt = update(Device).where(Device.machine_id == machine_id)
        # A device is one row per account that has used it, so trusting one
        # account's use of it does not vouch for anybody else's.
        if user_id is not None:
            stmt = stmt.where(Device.user_id == user_id)
        return db.execute(stmt.values(**values)).rowcount or 0

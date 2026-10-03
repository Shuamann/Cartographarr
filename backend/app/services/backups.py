"""A copy of the database, taken while it is in use.

Everything the app has worked out lives in one SQLite file: the stream sessions
with their stall causes, the travel flags, the bans, the rules, the reported
problems, the keep decisions, every setting. Tautulli can reconstruct the raw
history and none of the rest. Lose the appdata volume and all of it is gone.

Copying the file is not a backup. SQLite is in WAL mode, so the newest writes
are in a sidecar file and a plain copy can catch the pair mid-transaction and
produce something that will not open. `VACUUM INTO` is the supported way: it
writes a consistent snapshot of the database as of the moment it starts, from
inside SQLite, while everything carries on using it.

Kept beside the live file rather than somewhere clever, because the thing this
protects against is the database being damaged or a bad migration, not the
array catching fire. Whatever already backs up appdata gets these for free.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.settings_store import current

log = logging.getLogger(__name__)

FOLDER = "backups"
STAMP = "%Y%m%d-%H%M%S"
NAME = re.compile(r"^cartographarr-(\d{8}-\d{6})\.db$")


def folder() -> Path:
    from app.config import get_settings

    return get_settings().data_dir / FOLDER


def existing() -> list[Path]:
    """Snapshots, oldest first, by the time in the name rather than the file's
    own, which a restore or a copy would have rewritten."""
    where = folder()
    if not where.is_dir():
        return []
    return sorted((p for p in where.glob("cartographarr-*.db") if NAME.match(p.name)), key=lambda p: p.name)


def take() -> dict[str, Any]:
    """One snapshot, then drop the oldest beyond the number to keep."""
    keep = max(0, int(current().backup_keep))
    if keep == 0:
        return {"status": "off"}

    where = folder()
    where.mkdir(parents=True, exist_ok=True)
    target = where / f"cartographarr-{datetime.now(UTC).strftime(STAMP)}.db"
    if target.exists():
        # Two in the same second, which only happens by hand.
        return {"status": "already taken this second"}

    # Imported here rather than at the top: `app.db` builds its engine when it
    # is first imported, and a module holding a reference from then on is
    # pointing at whichever database existed at that moment. Which is how the
    # first run of these tests cheerfully backed up the development database.
    from app.db import engine

    # SQLite will not take a bind parameter for this, so the path is quoted the
    # way SQL quotes a string, by doubling any apostrophe in it. The path is
    # ours rather than anyone's input, but the rule is the rule.
    quoted = str(target).replace("'", "''")

    with engine.connect() as conn:
        # VACUUM refuses to run inside a transaction, which is what a
        # connection would otherwise open for it.
        conn.execution_options(isolation_level="AUTOCOMMIT")
        conn.execute(text(f"VACUUM INTO '{quoted}'"))

    removed = 0
    for old in existing()[:-keep] if keep else []:
        try:
            old.unlink()
            removed += 1
        except OSError:
            log.warning("could not remove the old backup %s", old.name)

    return {"file": target.name, "bytes": target.stat().st_size, "kept": len(existing()), "removed": removed}

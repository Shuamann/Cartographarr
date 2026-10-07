"""How much room each library takes, and how much is left.

Three questions that sound like one.

How much a library holds is a sum of its files, and the database can answer it
at any moment. How much it grew is a different thing: nothing records when a
file arrived, and the scan overwrites what it finds, so the only way to know is
to have written yesterday down. `library_sizes` is that, and until it has a few
days in it the answer here is honestly nothing rather than zero.

How much room is left is not a property of a library at all. It belongs to the
disk underneath, and two things on one share have one answer between them, not
two. `disks` answers that for any grouping of files, and says who else is on
the same disk so nobody adds the same free space up twice. Storage is the page
that shows it, since that is the one already about where files sit.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# Imported inside each function, never at module level. The tests reload the
# models, and a name bound up here would be the class from before the reload,
# which SQLAlchemy renders as the same table joined to itself.

MOUNT_CACHE_SECONDS = 60
"""Finding where a library lives can walk the media roots, which is far too
much work for a page that redraws. The disks do not move in a minute."""

_mounts: dict[str, Any] = {"at": 0.0, "value": None, "key": None}


def _used(db: Session) -> list[dict[str, Any]]:
    from app.models import Library, MediaItem
    from app.services.library_scan import in_library

    rows = db.execute(
        select(
            MediaItem.section_id,
            func.count().label("files"),
            func.coalesce(func.sum(MediaItem.file_size), 0).label("bytes"),
        )
        .where(MediaItem.media_type.in_(("movie", "episode")), MediaItem.section_id.is_not(None), in_library())
        .group_by(MediaItem.section_id)
    ).all()
    names = {lib.section_id: lib.name for lib in db.execute(select(Library)).scalars()}
    return [
        {
            "section_id": r.section_id,
            "name": names.get(r.section_id) or f"Library {r.section_id}",
            "files": r.files,
            "size": int(r.bytes or 0),
        }
        for r in rows
    ]


def _was(db: Session, days: int | None) -> dict[int, tuple[int, int, str]]:
    """What each library held, and on which day.

    With `days`, the most recent day at least that long ago: the nearest
    earlier day rather than that day exactly, because the scan only writes on
    days the app was running, and a week off is better than no answer at all.

    With None, the oldest day there is. That is the fallback for a new install
    where nothing is a week old yet, and it is why the day comes back with the
    figures: a change measured over three days must not be presented as a
    week's.
    """
    from app.models import LibrarySize

    stmt = select(LibrarySize.section_id, LibrarySize.on_day, LibrarySize.files, LibrarySize.bytes)
    if days is not None:
        stmt = stmt.where(LibrarySize.on_day <= (date.today() - timedelta(days=days)).isoformat())
    order = LibrarySize.on_day.desc() if days is not None else LibrarySize.on_day.asc()
    out: dict[int, tuple[int, int, str]] = {}
    for r in db.execute(stmt.order_by(LibrarySize.section_id, order)).all():
        out.setdefault(r.section_id, (r.files, int(r.bytes or 0), r.on_day))
    return out


UNITS = {"": 1, "k": 1e3, "kb": 1e3, "m": 1e6, "mb": 1e6, "g": 1e9, "gb": 1e9,
         "t": 1e12, "tb": 1e12, "p": 1e15, "pb": 1e15}


def stated_sizes(setting: str) -> dict[str, int]:
    """Capacities somebody has written down, by path.

    One per line, `path = size`, with the size in whatever unit reads
    naturally. Anything unparseable is ignored rather than guessed at: a typo
    should cost the override, not the page.
    """
    import re

    out: dict[str, int] = {}
    for line in (setting or "").splitlines():
        if "=" not in line:
            continue
        where, _, amount = line.partition("=")
        where, amount = where.strip().rstrip("/"), amount.strip().lower().replace(" ", "")
        found = re.fullmatch(r"([\d.]+)([a-z]*)", amount)
        if not where or not found or found.group(2) not in UNITS:
            continue
        try:
            out[where] = int(float(found.group(1)) * UNITS[found.group(2)])
        except ValueError:
            continue
    return out


def _stated_mount(path: str, stated: dict[str, int]) -> str | None:
    """Which written down mount this path sits under, itself included."""
    where = path.rstrip("/")
    while where:
        if where in stated:
            return where
        parent = where.rsplit("/", 1)[0]
        if parent == where:
            break
        where = parent
    return None


def _stated_for(path: str, stated: dict[str, int]) -> int | None:
    """The capacity written down for this mount, or for a parent of it."""
    where = _stated_mount(path, stated)
    return stated[where] if where else None


def disks(groups: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
    """How much room is left where each of these groups of files lives.

    Takes a label and some example paths, and answers per label. Grouped by
    the device underneath, so two stores on one share get the same answer and
    each is told who it is sharing with, rather than the page showing the same
    four terabytes twice and somebody counting it as eight.

    Empty when the media is not mounted into this container, which is a normal
    way to run the app and not an error.
    """
    key = tuple(sorted(groups))
    now = time.time()
    if _mounts["key"] == key and _mounts["value"] is not None and now - float(_mounts["at"]) < MOUNT_CACHE_SECONDS:
        return _mounts["value"]  # type: ignore[return-value]

    from app.services import mediafix

    by_device: dict[Any, dict[str, Any]] = {}
    for label, paths in groups.items():
        here = None
        for path in paths[:4]:
            here = mediafix.local_path(path)
            if here:
                break
        if not here:
            continue
        folder = os.path.dirname(here)
        try:
            device = os.stat(folder).st_dev
            usage = shutil.disk_usage(folder)
        except OSError as err:
            log.debug("no disk usage for %s: %s", folder, err)
            continue
        row = by_device.setdefault(device, {
            "path": folder, "free": usage.free, "total": usage.total,
            "used": usage.total - usage.free, "labels": [],
        })
        # The shortest path on a device reads best as its name: the share,
        # not whichever film happened to be sampled.
        if len(folder) < len(row["path"]):
            row["path"] = folder
        row["labels"].append(label)

    from app.settings_store import current

    stated = stated_sizes(current().disk_sizes)
    here = _what_is_here(stated) if stated else {}

    out: dict[str, dict[str, Any]] = {}
    for row in by_device.values():
        row["labels"].sort(key=str.lower)
        # A share that answers for the whole array reports a total nothing can
        # correct from the outside, so it can be told. What is in use then
        # comes from the files this app can see there, which is a different
        # kind of answer and is said to be one.
        mount = _stated_mount(row["path"], stated) if stated else None
        size = stated.get(mount) if mount else None
        if size:
            # Looked up by the mount it was counted under, not by whichever
            # folder a sample file happened to sit in.
            used = here.get(mount, 0)
            row["total"], row["used"], row["free"] = size, used, max(size - used, 0)
            row["stated"] = True
        for label in row["labels"]:
            out[label] = {
                "path": row["path"], "free": row["free"], "total": row["total"], "used": row["used"],
                # True where the capacity was written down rather than read
                # off the disk, and the space in use counted from the files
                # this app knows about.
                "stated": bool(row.get("stated")),
                # Who else is on this disk, so its free space is read once.
                "shared_with": [other for other in row["labels"] if other != label],
            }
    _mounts["key"], _mounts["at"], _mounts["value"] = key, now, out
    return out


def _what_is_here(stated: dict[str, int]) -> dict[str, int]:
    """How many bytes of media this app can see under each stated mount.

    Only what it scanned. A share with something else on it reads as having
    more room than it has, which is why the page says where the figure came
    from rather than presenting it as the disk's own answer.
    """
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import MediaItem
    from app.services import mediafix

    totals: dict[str, int] = {}
    with session_scope() as db:
        rows = db.execute(
            select(MediaItem.file_path, MediaItem.file_size).where(
                MediaItem.file_path.is_not(None), MediaItem.file_size.is_not(None)
            )
        ).all()
    for path, size in rows:
        local = mediafix.local_path(path)
        if not local:
            continue
        where = _stated_mount(local, stated)
        if where:
            totals[where] = totals.get(where, 0) + int(size or 0)
    return totals


def forget_mounts() -> None:
    """After the media paths change, the old answer is worse than none."""
    _mounts["at"], _mounts["value"], _mounts["key"] = 0.0, None, None


def report(db: Session) -> dict[str, Any]:
    from app.models import LibrarySize

    used = _used(db)
    week, month = _was(db, 7), _was(db, 30)
    # What to fall back on where nothing is old enough yet. Without this a new
    # install says "no history yet" for its first week while sitting on four
    # days of it, which is the page withholding a real answer.
    earliest = _was(db, None)
    today = date.today().isoformat()
    oldest = db.execute(select(func.min(LibrarySize.on_day))).scalar()
    days = db.execute(select(func.count(func.distinct(LibrarySize.on_day)))).scalar() or 0

    for row in used:
        for label, was in (("week", week), ("month", month)):
            before = was.get(row["section_id"]) or earliest.get(row["section_id"])
            # Today against today says nothing, so it is nothing rather than a
            # change of zero.
            if before is not None and before[2] >= today:
                before = None
            # None rather than zero: "no change" and "nothing written down
            # yet" are different answers and the page says so.
            row[f"change_{label}"] = None if before is None else row["size"] - before[1]
            row[f"files_{label}"] = None if before is None else row["files"] - before[0]
            # How long the figure actually covers, so one measured over three
            # days is never shown as a week's.
            row[f"{label}_since"] = None if before is None else before[2]
            row[f"{label}_days"] = (
                None if before is None else (date.today() - date.fromisoformat(before[2])).days
            )

    return {
        "libraries": sorted(used, key=lambda r: -r["size"]),
        "total": sum(r["size"] for r in used),
        "recorded_from": oldest,
        "recorded_days": days,
    }

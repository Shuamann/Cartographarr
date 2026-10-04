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


def _was(db: Session, days: int) -> dict[int, tuple[int, int]]:
    """What each library held on the most recent day at least `days` ago.

    The nearest earlier day rather than that day exactly, because the scan
    only writes on days the app was running, and a week off is better than no
    answer at all.
    """
    from app.models import LibrarySize
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    out: dict[int, tuple[int, int]] = {}
    rows = db.execute(
        select(LibrarySize.section_id, LibrarySize.on_day, LibrarySize.files, LibrarySize.bytes)
        .where(LibrarySize.on_day <= cutoff)
        .order_by(LibrarySize.section_id, LibrarySize.on_day.desc())
    ).all()
    for r in rows:
        out.setdefault(r.section_id, (r.files, int(r.bytes or 0)))
    return out


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

    out: dict[str, dict[str, Any]] = {}
    for row in by_device.values():
        row["labels"].sort(key=str.lower)
        for label in row["labels"]:
            out[label] = {
                "path": row["path"], "free": row["free"], "total": row["total"], "used": row["used"],
                # Who else is on this disk, so its free space is read once.
                "shared_with": [other for other in row["labels"] if other != label],
            }
    _mounts["key"], _mounts["at"], _mounts["value"] = key, now, out
    return out


def forget_mounts() -> None:
    """After the media paths change, the old answer is worse than none."""
    _mounts["at"], _mounts["value"], _mounts["key"] = 0.0, None, None


def report(db: Session) -> dict[str, Any]:
    from app.models import LibrarySize

    used = _used(db)
    week, month = _was(db, 7), _was(db, 30)
    oldest = db.execute(select(func.min(LibrarySize.on_day))).scalar()
    days = db.execute(select(func.count(func.distinct(LibrarySize.on_day)))).scalar() or 0

    for row in used:
        for label, was in (("week", week), ("month", month)):
            before = was.get(row["section_id"])
            # None rather than zero: "no change" and "nothing written down
            # yet" are different answers and the page says so.
            row[f"change_{label}"] = None if before is None else row["size"] - before[1]
            row[f"files_{label}"] = None if before is None else row["files"] - before[0]

    return {
        "libraries": sorted(used, key=lambda r: -r["size"]),
        "total": sum(r["size"] for r in used),
        "recorded_from": oldest,
        "recorded_days": days,
    }

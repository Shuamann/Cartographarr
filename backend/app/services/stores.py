"""Which storage each file sits on, and how each one behaves.

A Plex library can point at more than one place: an array share and a network
SSD, say. Plex reports the path it sees, so the top of that path is the mount,
and the mount is the storage. Nothing else in the app knew this, which meant a
file that stalls could never be traced to the box it lives on.

Roots are discovered from the paths themselves, so this works on any server
without anyone filling in a form. Giving two roots the same name puts them
together: four mounts off one NAS become one store called what you call it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.db import session_scope
from app.plays import plays, plays_when
from app.settings_store import current

UNKNOWN = "Not known"


def root_of(path: str | None, depth: int = 1) -> str | None:
    """The mount a path sits under: its first `depth` parts."""
    if not path:
        return None
    text = path.replace("\\", "/")
    parts = [part for part in text.split("/") if part]
    if not parts:
        return None
    return "/" + "/".join(parts[:depth])


def labels() -> dict[str, str]:
    from app.models import LibraryStore

    with session_scope() as db:
        return {row.prefix: row.label for row in db.execute(select(LibraryStore)).scalars() if row.label}


def name_for(path: str | None, named: dict[str, str] | None = None, depth: int | None = None) -> str:
    """What to call the storage a file is on."""
    depth = depth or current().library_store_depth
    root = root_of(path, depth)
    if root is None:
        return UNKNOWN
    return (named or labels()).get(root) or root


def summary(days: int = 30) -> dict[str, Any]:
    """Every store: what it holds, how much is watched from it, and what goes
    wrong there."""
    from app.models import History, MediaItem, StreamEvent
    from app.services.library import _since
    from app.services.library_scan import in_library

    since, cutoff = _since(days)
    depth = current().library_store_depth
    named = labels()

    with session_scope() as db:
        files = db.execute(
            select(MediaItem.rating_key, MediaItem.file_path, MediaItem.file_size, MediaItem.file_bitrate)
            .where(MediaItem.file_path.is_not(None), in_library())
        ).all()
        remote = History.location == "wan"
        watched = {
            row[0]: row
            for row in db.execute(
                select(
                    History.rating_key,
                    plays(History),
                    plays_when(History, remote),
                    plays_when(History, History.transcode_decision == "transcode"),
                )
                .where(History.started >= since, History.rating_key.is_not(None))
                .group_by(History.rating_key)
            ).all()
        }
        stalls = dict(
            db.execute(
                select(StreamEvent.rating_key, func.count())
                .where(StreamEvent.started_at >= cutoff, StreamEvent.rating_key.is_not(None))
                .group_by(StreamEvent.rating_key)
            ).all()
        )
    stores: dict[str, dict[str, Any]] = {}
    for rating_key, path, size, bitrate in files:
        root = root_of(path, depth) or UNKNOWN
        label = named.get(root) or root
        store = stores.setdefault(label, {
            "store": label, "roots": set(), "files": 0, "size": 0, "bitrate_total": 0, "bitrate_files": 0,
            "plays": 0, "remote_plays": 0, "transcodes": 0, "stalls": 0,
        })
        store["roots"].add(root)
        store["files"] += 1
        store["size"] += int(size or 0)
        if bitrate:
            store["bitrate_total"] += int(bitrate)
            store["bitrate_files"] += 1
        play = watched.get(rating_key)
        if play:
            store["plays"] += int(play[1] or 0)
            store["remote_plays"] += int(play[2] or 0)
            store["transcodes"] += int(play[3] or 0)
        store["stalls"] += int(stalls.get(rating_key) or 0)

    out = []
    for store in stores.values():
        files_with_bitrate = store.pop("bitrate_files")
        total = store.pop("bitrate_total")
        out.append({
            **store,
            "roots": sorted(store["roots"]),
            "average_bitrate": round(total / files_with_bitrate) if files_with_bitrate else None,
            # What a store is judged on: how often watching from it goes wrong.
            "stalls_per_100": round(store["stalls"] / store["plays"] * 100, 1) if store["plays"] else None,
            "transcode_percent": round(store["transcodes"] / store["plays"] * 100) if store["plays"] else None,
        })
    out.sort(key=lambda s: -s["size"])
    return {"stores": out, "days": days, "depth": depth}


def rename(prefix: str, label: str) -> None:
    """Name a root. Two roots with one name are one store."""
    from app.models import LibraryStore

    with session_scope() as db:
        row = db.get(LibraryStore, prefix)
        if row is None:
            db.add(LibraryStore(prefix=prefix, label=label))
        else:
            row.label = label

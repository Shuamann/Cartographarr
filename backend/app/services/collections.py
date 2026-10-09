"""A collection's health: how big it is, what is wrong in it, who watches it.

Collections are where somebody has already written down what belongs together,
so they are how a library is thought about. Everything here was already kept:
the collection tags from the scan, sizes from the files, problem files from the
library lists and plays from the history. This adds it up per collection.

Plex files a collection against a film or a show, never an episode, so a
show's files are the episodes under it. The largest collection on a real
library held 1,727 titles and the next 42, so this reads the library once and
indexes it rather than asking per collection.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

WATCHED_DAYS = 365
"""A title counts as watched when anybody played it in this many days."""


def health(db, now: int | None = None, problem_days: int = 90) -> list[dict[str, Any]]:
    from app.models import History, MediaItem, MediaTag
    from app.services.library import problem_files
    from app.services.library_scan import in_library
    from app.settings_store import current

    now = now or int(datetime.now().timestamp())
    since = now - WATCHED_DAYS * 86400

    members: dict[str, set[int]] = defaultdict(set)
    for name, key in db.execute(select(MediaTag.value, MediaTag.rating_key).where(MediaTag.kind == "collection")):
        members[name].add(key)
    if not members:
        return []

    # Every file, under each key that owns it: its own, its season's, its show's.
    files: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for key, parent, grandparent, size in db.execute(
        select(MediaItem.rating_key, MediaItem.parent_rating_key, MediaItem.grandparent_rating_key, MediaItem.file_size)
        .where(MediaItem.file_size.is_not(None), in_library())
    ):
        for owner in {key, parent, grandparent} - {None}:
            files[owner].append((key, size or 0))

    # The last play of each title, by its own key and by its show's.
    last: dict[int, int] = {}
    for key, show, started in db.execute(
        select(History.rating_key, History.grandparent_rating_key, func.max(History.started))
        .group_by(History.rating_key, History.grandparent_rating_key)
    ):
        for owner in (key, show):
            if owner is not None and started and started > last.get(owner, 0):
                last[owner] = started

    threshold = int(current().library_bitrate_threshold_mbps * 1000)
    problems = {row["rating_key"] for row in problem_files(db, threshold, problem_days, limit=100_000)}

    out = []
    for name, keys in members.items():
        held = {key: size for owner in keys for key, size in files.get(owner, [])}
        lasts = [last[k] for k in keys if k in last]
        out.append({
            "name": name,
            "titles": len(keys),
            "files": len(held),
            "bytes": sum(held.values()),
            "problems": sum(1 for key in held if key in problems),
            # Titles, not files: a show half watched is a show somebody watches.
            "watched": sum(1 for k in keys if last.get(k, 0) >= since),
            "last_play": max(lasts) if lasts else None,
            # One title to show for it, the first that has a file.
            "poster_key": next((k for k in sorted(keys) if k in files), None),
        })
    out.sort(key=lambda c: -c["bytes"])
    return out

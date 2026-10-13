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

from sqlalchemy import func, or_, select

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


def names(db) -> list[str]:
    """Every collection name, as Plex spells it, in alphabetical order.

    What the kept collections setting and the rule builder's dropdown are
    picked from. health() answers the same names with a great deal more work
    behind them, which is wasted on a dropdown.
    """
    from app.models import MediaTag

    return [
        name
        for (name,) in db.execute(
            select(MediaTag.value)
            .where(MediaTag.kind == "collection")
            .distinct()
            .order_by(func.lower(MediaTag.value))
        )
        if name
    ]


def members(db, name: str) -> list[dict[str, Any]]:
    """Every playable file in one collection, its own and its episodes'.

    Plex files a collection against a film or a show, never against an
    episode, so a collection on a show reaches that show's episodes through
    their grandparent. A collection naming only shows would otherwise come
    back empty, which looks like an empty collection rather than a question
    asked at the wrong level.

    The owning keys stay a subquery rather than being read out and passed
    back in: the largest collection on a real library names 1,727 titles, and
    three IN clauses of that many bound parameters is how a query stops
    working on some SQLite builds.
    """
    from app.models import MediaItem, MediaTag
    from app.services.library_scan import in_library

    owners = (
        select(MediaTag.rating_key)
        .where(MediaTag.kind == "collection", func.lower(MediaTag.value) == name.strip().lower())
        .scalar_subquery()
    )
    rows = db.execute(
        select(MediaItem.rating_key, MediaItem.full_title, MediaItem.title)
        .where(
            MediaItem.media_type.in_(("movie", "episode")),
            in_library(),
            or_(
                MediaItem.rating_key.in_(owners),
                MediaItem.parent_rating_key.in_(owners),
                MediaItem.grandparent_rating_key.in_(owners),
            ),
        )
        .order_by(func.lower(func.coalesce(MediaItem.full_title, MediaItem.title)), MediaItem.rating_key)
    ).all()
    return [{"rating_key": key, "title": full or title} for key, full, title in rows]


def exists(db, name: str) -> bool:
    """Whether Plex has a collection by that name, ignoring case.

    Asked apart from members() so a collection that holds nothing the library
    still has can be told from a name nobody ever used.
    """
    from app.models import MediaTag

    return db.execute(
        select(MediaTag.rating_key)
        .where(MediaTag.kind == "collection", func.lower(MediaTag.value) == name.strip().lower())
        .limit(1)
    ).first() is not None


def names_for(*keys: int | str | None) -> list[str] | None:
    """The collections covering an item, lowercased, for a rule condition.

    Handed an item's own key, its season's and its show's, because Plex files
    a collection at the film or show level and the thing being asked about is
    usually an episode. One indexed lookup: the primary key starts with
    rating_key, so a handful of keys is a handful of seeks.

    None when nothing identifies the item at all, which is not the same
    answer as the empty list. An item whose key is unknown tells us nothing,
    so neither "is in" nor "is not in" should match it. An item with a key
    and no collections is known to be in none of them, and "is not in" is
    true of it. Conflating the two is how a rule about everything outside a
    collection either catches nothing or catches the whole library.
    """
    from app.db import session_scope
    from app.models import MediaTag

    # Plex and Tautulli both report rating keys as strings in activity, so
    # anything that reads as a whole number counts and anything else does not.
    wanted = set()
    for key in keys:
        try:
            wanted.add(int(key))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    if not wanted:
        return None
    with session_scope() as db:
        return sorted({
            str(value).strip().lower()
            for (value,) in db.execute(
                select(MediaTag.value).where(MediaTag.kind == "collection", MediaTag.rating_key.in_(wanted))
            )
            if value
        })

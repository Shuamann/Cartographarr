"""What a library is missing, and what it is holding twice.

Two questions a media server will not answer about itself, and both are
already answerable from what has been scanned. A season with episodes 1, 2, 3
and 5 in it has a hole somebody has to notice by scrolling; a film with three
files behind it is paying for two of them and says nothing.

Neither needs a new request to anything. The episode numbers are in
media_items, and so is how many files Plex says are behind each item. The
sizes of the files nobody has seen are the one thing that is not, and those
are fetched for the few dozen items it turns out to matter for.

Honesty rules, because both questions are easy to answer wrongly:

- Only a hole between two episodes that are here counts. A season that has run
  to episode five of ten is not missing five episodes, it has not aired them,
  and an app that says otherwise is noise from the first week of every season.
- Season 0 is skipped. Specials are numbered however the people filing them
  felt, and the gaps in them are not gaps.
- A season whose missing numbers alternate with its present ones is called out
  as double episodes rather than as missing. Plex files "S01E01-E02" under
  index 1, so a perfectly normal season reads as half empty. Eleven seasons on
  the library this was written against are that shape, and 187 of the 1,572
  apparently missing episodes were that and nothing else.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

log = logging.getLogger(__name__)

SPECIALS = 0
"""Season zero. Numbered arbitrarily, so a gap in it means nothing."""

DOUBLE_RUN = 3
"""How many alternating holes before a season is called double episodes rather
than half missing. Two could be coincidence; three in a row in that shape is
a naming convention."""


def _doubled(present: set[int], missing: list[int]) -> bool:
    """Whether this looks like double episodes filed under the first number.

    Every hole sits between two episodes that are here, and there are about as
    many holes as episodes. That is "1, 3, 5, 7" and not a season with three
    files lost.
    """
    if len(missing) < DOUBLE_RUN:
        return False
    if not all(gap - 1 in present and gap + 1 in present for gap in missing):
        return False
    return len(missing) >= len(present) - 1


def holes(db, section_id: int | None = None, limit: int = 200) -> dict[str, Any]:
    """Seasons with an episode missing from the middle of them."""
    from app.models import MediaItem

    stmt = select(
        MediaItem.grandparent_rating_key,
        MediaItem.grandparent_title,
        MediaItem.parent_rating_key,
        MediaItem.parent_media_index,
        MediaItem.media_index,
        MediaItem.section_id,
        MediaItem.grandparent_thumb,
    ).where(
        MediaItem.media_type == "episode",
        MediaItem.grandparent_rating_key.is_not(None),
        MediaItem.parent_media_index.is_not(None),
        MediaItem.media_index.is_not(None),
    )
    if section_id is not None:
        stmt = stmt.where(MediaItem.section_id == section_id)

    seasons: dict[tuple[int, int], set[int]] = {}
    about: dict[tuple[int, int], dict[str, Any]] = {}
    for row in db.execute(stmt).all():
        if row.parent_media_index == SPECIALS:
            continue
        where = (row.grandparent_rating_key, row.parent_media_index)
        seasons.setdefault(where, set()).add(row.media_index)
        about.setdefault(where, {
            "show_rating_key": row.grandparent_rating_key,
            "season_rating_key": row.parent_rating_key,
            "title": row.grandparent_title,
            "season": row.parent_media_index,
            "section_id": row.section_id,
            "thumb": row.grandparent_thumb,
        })

    found: list[dict[str, Any]] = []
    doubled = 0
    doubled_holes = 0
    for where, present in seasons.items():
        missing = sorted(set(range(min(present), max(present) + 1)) - present)
        if not missing:
            continue
        if _doubled(present, missing):
            doubled += 1
            doubled_holes += len(missing)
            continue
        found.append({
            **about[where],
            "have": len(present),
            "first": min(present),
            "last": max(present),
            # The run this season covers rather than the run it should: the
            # only thing knowable from here. A show numbered absolutely, or
            # one whose first episodes were never filed, reads as a long
            # season mostly missing, which is true of what is on disk and may
            # not be true of the show. The share is on the row so that can be
            # seen rather than inferred from two numbers.
            "total": max(present) - min(present) + 1,
            "missing": missing,
            # How many of the holes sit alone between two episodes that are
            # here. A season of double episodes with a few real gaps in it
            # fails the whole season test above and lands here looking like
            # forty missing files, when most of those forty are the second
            # half of an episode nobody is missing. The row says so rather
            # than the list either lying or dropping it.
            "paired": sum(1 for gap in missing if gap - 1 in present and gap + 1 in present),
        })

    # The emptiest first, because a season with one episode gone and a season
    # with nine are not the same job.
    found.sort(key=lambda row: (-len(row["missing"]), (row["title"] or "").lower(), row["season"]))
    return {
        "seasons": found[:limit],
        "seasons_found": len(found),
        "episodes_missing": sum(len(row["missing"]) for row in found),
        "shows": len({row["show_rating_key"] for row in found}),
        "seasons_checked": len(seasons),
        # Said rather than hidden: a season left out because it reads as double
        # episodes is a judgement, and a judgement nobody is told about is
        # indistinguishable from a bug.
        "double_episode_seasons": doubled,
        "double_episode_holes": doubled_holes,
    }


def _copy_candidates(db, section_id: int | None) -> list[Any]:
    """Items Plex says have more than one file behind them."""
    from app.models import MediaItem

    stmt = select(
        MediaItem.rating_key,
        MediaItem.title,
        MediaItem.full_title,
        MediaItem.grandparent_title,
        MediaItem.parent_media_index,
        MediaItem.media_index,
        MediaItem.year,
        MediaItem.media_type,
        MediaItem.section_id,
        MediaItem.versions,
        MediaItem.file_size,
        MediaItem.file_path,
        MediaItem.thumb,
        MediaItem.grandparent_thumb,
    ).where(MediaItem.versions > 1)
    if section_id is not None:
        stmt = stmt.where(MediaItem.section_id == section_id)
    return db.execute(stmt).all()


def _same_id(db, section_id: int | None) -> list[dict[str, Any]]:
    """Separate items in one library that claim to be the same thing.

    Not the same as an item with two files. This is Plex holding two entries
    for one film, which is what a stray copy in the wrong folder, or a match
    made twice, looks like. The external id is the test rather than the title,
    because two films can share a name and two entries for one film cannot
    share an id by accident.
    """
    from app.models import MediaItem

    rows = db.execute(
        select(
            MediaItem.rating_key,
            MediaItem.title,
            MediaItem.year,
            MediaItem.media_type,
            MediaItem.section_id,
            MediaItem.file_size,
            MediaItem.file_path,
            MediaItem.thumb,
            MediaItem.imdb_id,
            MediaItem.tmdb_id,
            MediaItem.tvdb_id,
        ).where(
            MediaItem.media_type.in_(("movie", "show")),
            *( [MediaItem.section_id == section_id] if section_id is not None else [] ),
        )
    ).all()

    groups: dict[tuple[int | None, str, str], list[Any]] = {}
    for row in rows:
        for kind, value in (("imdb", row.imdb_id), ("tmdb", row.tmdb_id), ("tvdb", row.tvdb_id)):
            if value:
                groups.setdefault((row.section_id, kind, str(value)), []).append(row)

    # One group per set of items, however many ids they happen to share: a
    # film matched twice shares all three, and reporting it three times would
    # be reporting the ids rather than the films.
    seen: set[tuple[int, ...]] = set()
    out: list[dict[str, Any]] = []
    for (section, kind, value), items in groups.items():
        if len(items) < 2:
            continue
        keys = tuple(sorted(item.rating_key for item in items))
        if keys in seen:
            continue
        seen.add(keys)
        out.append({
            "matched_on": kind,
            "id": value,
            "section_id": section,
            "title": items[0].title,
            "year": items[0].year,
            "media_type": items[0].media_type,
            "thumb": items[0].thumb,
            "items": [
                {
                    "rating_key": item.rating_key,
                    "title": item.title,
                    "file_size": item.file_size,
                    "file_path": item.file_path,
                }
                for item in items
            ],
        })
    out.sort(key=lambda row: ((row["title"] or "").lower(), row["year"] or 0))
    return out


def copies(db, section_id: int | None = None, sizes: bool = True, limit: int = 200) -> dict[str, Any]:
    """Items with more than one file, and separate items for one title.

    The sizes of the files beyond the first are not kept: media_items holds one
    file per item because everything else built on it asks about one. There are
    a few dozen of these, so they are asked for directly rather than carried in
    every row of a table of thirty thousand. With Plex unreachable the list is
    still right, and says the room is unknown rather than guessing at it.
    """
    rows = _copy_candidates(db, section_id)
    found = [
        {
            "rating_key": row.rating_key,
            # Both, because the row that draws this splits a title into its
            # show and its episode. Handed the full title as the episode's own
            # name it prints the show twice.
            "title": row.title,
            "full_title": row.full_title or row.title,
            "show": row.grandparent_title,
            "season": row.parent_media_index,
            "episode": row.media_index,
            "year": row.year,
            "media_type": row.media_type,
            "section_id": row.section_id,
            "versions": row.versions,
            "thumb": row.thumb,
            "show_thumb": row.grandparent_thumb,
            "files": None,
            "extra_bytes": None,
            "sizes_known": False,
        }
        for row in rows
    ]
    found.sort(key=lambda row: (-(row["versions"] or 0), (row["title"] or "").lower()))
    found = found[:limit]

    asked = False
    if sizes and found:
        asked = _fill_files(found)
        # Sorted again once the sizes are in. Somebody reading this is looking
        # for room, and the item with six copies of a short clip is not the
        # one to start with. Unknown sizes keep their place at the bottom
        # rather than sorting as nothing.
        if asked:
            found.sort(key=lambda row: (-(row["extra_bytes"] or 0), -(row["versions"] or 0)))

    return {
        "multi": found,
        "multi_found": len(rows),
        "extra_files": sum((row["versions"] or 1) - 1 for row in found),
        # None where Plex could not be asked. Zero would read as "nothing to
        # gain" and the answer is "nobody knows yet".
        "extra_bytes": (
            sum(row["extra_bytes"] or 0 for row in found) if asked else None
        ),
        # How many of the rows gave a complete answer, so a total that is a
        # floor is not read as the whole of it.
        "sizes_partial": (
            sum(1 for row in found if not row.get("sizes_known")) if asked else None
        ),
        "same_id": _same_id(db, section_id)[:limit],
    }


def _fill_files(found: list[dict[str, Any]]) -> bool:
    """Put every file behind each item onto its row. True if Plex answered."""
    from app.plex import library as plex_library

    try:
        got = plex_library.versions_of([row["rating_key"] for row in found])
    except Exception as exc:  # noqa: BLE001 - a list without sizes beats no list
        log.warning("could not read the files behind %d items: %s", len(found), exc)
        return False
    if not got:
        return False
    for row in found:
        files = got.get(row["rating_key"])
        if not files:
            continue
        row["files"] = files
        known = [f["size"] for f in files if f.get("size")]
        # Everything past the largest. Keeping the best copy is the usual
        # intention, so the room to be had is what the rest take.
        #
        # None where fewer than two of the files gave a size, which happens:
        # an optimised version reports none. Zero there would read as "nothing
        # to gain from this one" and the answer is "nobody knows".
        row["extra_bytes"] = sum(sorted(known, reverse=True)[1:]) if len(known) > 1 else None
        row["sizes_known"] = len(known) == len(files)
    return True

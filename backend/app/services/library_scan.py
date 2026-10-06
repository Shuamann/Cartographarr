"""Knowing the whole library, not just what has been played.

Two stages, each its own background task:

1. **Scan** lists every movie and episode, from Tautulli's media info (a
   page per movie library, a request per show and per season) or from Plex
   directly, as the library source setting says, with bitrate, resolution,
   codecs, container and size. Plex adds the file path and the IMDb, TMDB
   and TVDB ids. A few hundred quick
   requests cover tens of thousands of files, so Problem files and 4K copies
   are complete within a minute. A file whose size changed is marked to be
   read again, and anything no longer in Plex drops out of the lists.
2. **Details** reads each file's full metadata (every audio and subtitle
   track, ids for links) through Tautulli, several at a time, in chunks,
   until nothing is left. Messy files fills in as it goes.

Before this, titles only appeared once somebody played them, and file details
were read 150 per sync, so a large library took hours and unwatched files
never showed at all.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, update

from app import models
from app.db import session_scope

log = logging.getLogger(__name__)

SCAN_KEY = "library_scan_started"
CONCURRENCY = 8
DETAILS_CHUNK = 3000
"""About 30 seconds of reading at 8 at a time, inside the one-minute schedule."""


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _resolution(value: Any) -> str | None:
    v = str(value or "").strip().lower()
    if not v:
        return None
    return f"{v}p" if v.isdigit() else v


def row_from_media_info(r: dict[str, Any], section_id: int, show_title: str | None = None) -> dict[str, Any] | None:
    key = _int(r.get("rating_key"))
    media_type = r.get("media_type")
    if key is None or media_type not in ("movie", "episode"):
        return None
    return {
        "rating_key": key,
        "parent_rating_key": _int(r.get("parent_rating_key")),
        "grandparent_rating_key": _int(r.get("grandparent_rating_key")),
        "section_id": _int(r.get("section_id")) or section_id,
        "media_type": media_type,
        "title": r.get("title") or None,
        "full_title": f"{show_title} - {r.get('title')}" if show_title and media_type == "episode" else (r.get("title") or None),
        "grandparent_title": show_title if media_type == "episode" else None,
        "media_index": _int(r.get("media_index")),
        "parent_media_index": _int(r.get("parent_media_index")),
        "year": _int(r.get("year")),
        "thumb": r.get("thumb") or None,
        "file_bitrate": _int(r.get("bitrate")),
        "file_container": r.get("container") or None,
        "video_codec": r.get("video_codec") or None,
        "video_resolution": _resolution(r.get("video_resolution")),
        "audio_codec": r.get("audio_codec") or None,
        "audio_channels": _int(r.get("audio_channels")),
        "file_size": _int(r.get("file_size")),
    }


async def _pages(client, **params) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    start = 0
    while True:
        data = await client.call("get_library_media_info", start=start, length=1000, **params) or {}
        rows = data.get("data") or []
        out.extend(rows)
        total = _int(data.get("recordsFiltered")) or _int(data.get("recordsTotal")) or 0
        start += len(rows)
        if not rows or start >= total:
            return out


async def scan(client) -> dict[str, Any]:
    """List every movie and episode. Returns counts.

    Either source answers in the same rows, so storing them, the size history
    and everything that reads media_items do not know which one was asked.
    Plex also gives the file path and the external ids in the same pass.
    """
    from app.settings_store import current

    started = datetime.now(UTC)
    if current().library_source == "plex":
        from app.plex import library as plex_library

        rows = await asyncio.to_thread(plex_library.read)
    else:
        rows = await _tautulli_rows(client)
    counts = await asyncio.to_thread(_store, rows, started)
    await asyncio.to_thread(_record_sizes, started)
    return {"movies": sum(1 for r in rows if r["media_type"] == "movie"),
            "episodes": sum(1 for r in rows if r["media_type"] == "episode"), **counts}


async def _tautulli_rows(client) -> list[dict[str, Any]]:
    """A page per movie library, a request per show and per season."""
    libraries = await client.call("get_libraries") or []
    semaphore = asyncio.Semaphore(CONCURRENCY)
    rows: list[dict[str, Any]] = []

    async def limited(**params):
        async with semaphore:
            return await _pages(client, **params)

    for lib in libraries:
        section = _int(lib.get("section_id"))
        kind = lib.get("section_type")
        if section is None:
            continue
        if kind == "movie":
            for r in await limited(section_id=section):
                row = row_from_media_info(r, section)
                if row:
                    rows.append(row)
        elif kind == "show":
            shows = await limited(section_id=section)

            async def one_show(show: dict[str, Any], section=section):
                title = show.get("title")
                seasons = await limited(rating_key=show.get("rating_key"))
                episode_lists = await asyncio.gather(*(limited(rating_key=s.get("rating_key")) for s in seasons))
                found = []
                for episodes in episode_lists:
                    for e in episodes:
                        row = row_from_media_info(e, section, title)
                        if row:
                            row["grandparent_rating_key"] = row["grandparent_rating_key"] or _int(show.get("rating_key"))
                            found.append(row)
                return found

            for found in await asyncio.gather(*(one_show(s) for s in shows)):
                rows.extend(found)
    return rows


def _record_sizes(started: datetime) -> None:
    """Write down what each library holds today.

    Nothing records when a file arrived, so whether a library grew this week
    can only be answered by having written down what it was last week. This is
    that. One row per library per day, the day's later scans overwriting the
    earlier ones, so it is the last word on each day rather than the first.
    """
    MediaItem, LibrarySize = models.MediaItem, models.LibrarySize
    day = started.astimezone().strftime("%Y-%m-%d") if started.tzinfo else started.strftime("%Y-%m-%d")
    with session_scope() as db:
        rows = db.execute(
            select(
                MediaItem.section_id,
                func.count().label("files"),
                func.coalesce(func.sum(MediaItem.file_size), 0).label("bytes"),
            )
            .where(MediaItem.media_type.in_(("movie", "episode")), MediaItem.section_id.is_not(None), in_library())
            .group_by(MediaItem.section_id)
        ).all()
        for row in rows:
            existing = db.execute(
                select(LibrarySize).where(LibrarySize.section_id == row.section_id, LibrarySize.on_day == day)
            ).scalar_one_or_none()
            if existing is None:
                db.add(LibrarySize(section_id=row.section_id, on_day=day, files=row.files,
                                   bytes=int(row.bytes or 0), at=started))
            else:
                existing.files, existing.bytes, existing.at = row.files, int(row.bytes or 0), started


def _store(rows: list[dict[str, Any]], started: datetime) -> dict[str, int]:
    MediaItem, SyncState = models.MediaItem, models.SyncState
    new = changed = 0
    for i in range(0, len(rows), 500):
        chunk = rows[i : i + 500]
        with session_scope() as db:
            existing = {
                m.rating_key: m
                for m in db.execute(select(MediaItem).where(MediaItem.rating_key.in_([r["rating_key"] for r in chunk]))).scalars()
            }
            for row in chunk:
                item = existing.get(row["rating_key"])
                if item is None:
                    db.add(MediaItem(**row, library_seen_at=started))
                    new += 1
                    continue
                # The file itself changed (a replacement, an upgrade): read its tracks again.
                if item.file_checked_at is not None and row["file_size"] and item.file_size and row["file_size"] != item.file_size:
                    item.file_checked_at = None
                    changed += 1
                for key, value in row.items():
                    if value is not None and key != "rating_key":
                        setattr(item, key, value)
                item.library_seen_at = started
    with session_scope() as db:
        db.merge(SyncState(key=SCAN_KEY, value=started.isoformat()))
    return {"new": new, "changed": changed}


def last_scan() -> datetime | None:
    with session_scope() as db:
        row = db.get(models.SyncState, SCAN_KEY)
        if row is None:
            return None
        try:
            return datetime.fromisoformat(row.value)
        except ValueError:
            return None


def in_library():
    """Items Plex still has, by the last scan. Everything, before any scan."""
    MediaItem = models.MediaItem
    started = last_scan()
    if started is None:
        return MediaItem.rating_key.is_not(None)
    # SQLite stores these without a zone; compare like with like. Something
    # first played since the scan counts until the next one sees it.
    since = started.replace(tzinfo=None)
    return or_(MediaItem.library_seen_at >= since, and_(MediaItem.library_seen_at.is_(None), MediaItem.synced_at >= since))


async def read_details(client, chunk: int = DETAILS_CHUNK) -> dict[str, int]:
    """Read full metadata for files not read yet, one chunk per run."""
    from app.services.sync import metadata_row

    MediaItem = models.MediaItem

    unread = (
        MediaItem.title.is_not(None),
        MediaItem.file_checked_at.is_(None),
        MediaItem.media_type.in_(("movie", "episode")),
    )

    def pending() -> list[int]:
        with session_scope() as db:
            return [k for (k,) in db.execute(select(MediaItem.rating_key).where(*unread).limit(chunk)).all()]

    keys = await asyncio.to_thread(pending)
    if not keys:
        return {"read": 0, "left": 0}
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def fetch(key: int) -> dict[str, Any]:
        async with semaphore:
            return await metadata_row(client, key)

    results = await asyncio.gather(*(fetch(k) for k in keys))

    def save() -> int:
        now = datetime.now(UTC)
        with session_scope() as db:
            for row in results:
                key = row["rating_key"]
                if row.get("title") is None:
                    # Gone from Plex, or unreadable: do not ask again until the file changes.
                    db.execute(update(MediaItem).where(MediaItem.rating_key == key).values(file_checked_at=now))
                    continue
                values = {k: v for k, v in row.items() if k != "rating_key" and v is not None}
                values.setdefault("file_checked_at", now)
                db.execute(update(MediaItem).where(MediaItem.rating_key == key).values(**values))
        with session_scope() as db:
            return db.execute(select(func.count()).select_from(MediaItem).where(*unread)).scalar() or 0

    left = await asyncio.to_thread(save)
    return {"read": len(keys), "left": left}

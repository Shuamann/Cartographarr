"""Tautulli -> local SQLite sync.

Keeps a warm mirror and moves only the delta. Never a full rescan: a watermark
bounds the history pull, IPs are geocoded once ever, and metadata is fetched
once per rating_key ever.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import session_scope
from app.geo.lookup import GeoResolver, is_private
from app.models import Device, History, IpLocation, Library, MediaItem, SyncState, User
from app.tautulli.client import TautulliClient

log = logging.getLogger(__name__)

WATERMARK = "history_watermark"
BACKFILL_OFFSET = "history_backfill_offset"


# ---- small coercions -------------------------------------------------------
# Tautulli hands back '1' / '' / None where an int or bool is meant.

def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    return str(value) in ("1", "True", "true")


def _state(session: Session, key: str) -> str | None:
    row = session.get(SyncState, key)
    return row.value if row else None


def _set_state(session: Session, key: str, value: str | None) -> None:
    if value is None:
        row = session.get(SyncState, key)
        if row:
            session.delete(row)
        return
    session.merge(SyncState(key=key, value=str(value)))


def _upsert(session: Session, model, rows: list[dict]) -> None:
    """Bulk insert-or-update. One statement per batch, not one per row."""
    if not rows:
        return
    stmt = insert(model)
    keys = {c.name for c in model.__table__.primary_key}
    updatable = {c: stmt.excluded[c] for c in rows[0] if c not in keys}
    if updatable:
        stmt = stmt.on_conflict_do_update(index_elements=list(keys), set_=updatable)
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=list(keys))
    session.execute(stmt, rows)


# ---- history ---------------------------------------------------------------

def _map_history(row: dict) -> dict:
    return {
        "row_id": _int(row.get("row_id")),
        "reference_id": _int(row.get("reference_id")),
        "user_id": _int(row.get("user_id")),
        "machine_id": row.get("machine_id") or None,
        "ip_address": row.get("ip_address") or None,
        "started": _int(row.get("started")),
        "stopped": _int(row.get("stopped")),
        "duration": _int(row.get("duration")),
        "play_duration": _int(row.get("play_duration")),
        "paused_counter": _int(row.get("paused_counter")),
        "percent_complete": _int(row.get("percent_complete")),
        "watched_status": _float(row.get("watched_status")),
        "media_type": row.get("media_type") or None,
        "rating_key": _int(row.get("rating_key")),
        "parent_rating_key": _int(row.get("parent_rating_key")),
        "grandparent_rating_key": _int(row.get("grandparent_rating_key")),
        "title": row.get("title") or None,
        "full_title": row.get("full_title") or None,
        "year": _int(row.get("year")),
        "thumb": row.get("thumb") or None,
        "live": bool(_bool(row.get("live"))),
        "platform": row.get("platform") or None,
        "player": row.get("player") or None,
        "product": row.get("product") or None,
        "transcode_decision": row.get("transcode_decision") or None,
        "location": row.get("location") or None,
        "secure": _bool(row.get("secure")),
        "relayed": _bool(row.get("relayed")),
    }


async def sync_history(client: TautulliClient, settings: Settings, full: bool = False) -> int:
    """Pull new history rows. Returns how many were written."""
    page = settings.sync_page_size

    with session_scope() as session:
        watermark = None if full else _int(_state(session, WATERMARK))
        offset = _int(_state(session, BACKFILL_OFFSET)) or 0

    after = None
    if watermark:
        # Day granularity is all `after` supports; overlap is free because the
        # upsert is idempotent.
        after = datetime.fromtimestamp(watermark, UTC).strftime("%Y-%m-%d")

    written = 0
    newest = watermark or 0

    while True:
        data = await client.call(
            "get_history",
            start=offset,
            length=page,
            order_column="date",
            order_dir="desc",
            after=after,
        )
        rows = (data or {}).get("data") or []
        if not rows:
            break

        mapped = [m for m in map(_map_history, rows) if m["row_id"] is not None]
        newest = max([newest, *(m["started"] or 0 for m in mapped)])

        with session_scope() as session:
            _upsert(session, History, mapped)
            offset += len(rows)
            # Persisted every page so a restart resumes instead of restarting.
            _set_state(session, BACKFILL_OFFSET, offset)

        written += len(mapped)
        total = _int((data or {}).get("recordsFiltered")) or 0
        if offset >= total:
            break

    with session_scope() as session:
        _set_state(session, BACKFILL_OFFSET, None)
        if newest:
            _set_state(session, WATERMARK, newest)

    log.info("history sync: %d rows", written)
    return written


# ---- users, libraries ------------------------------------------------------

async def sync_users(client: TautulliClient) -> int:
    data = await client.call("get_users_table", length=1000) or {}
    rows = [
        {
            "user_id": _int(r.get("user_id")),
            "username": r.get("username") or None,
            "friendly_name": r.get("friendly_name") or None,
            "email": r.get("email") or None,
            "thumb": r.get("user_thumb") or None,
            "is_active": bool(_bool(r.get("is_active")) is not False),
            "is_home_user": bool(_bool(r.get("is_home_user"))),
            "last_seen": _int(r.get("last_seen")),
        }
        for r in data.get("data") or []
    ]
    rows = [r for r in rows if r["user_id"] is not None]
    with session_scope() as session:
        _upsert(session, User, rows)
    return len(rows)


async def sync_libraries(client: TautulliClient) -> int:
    data = await client.call("get_libraries") or []
    rows = [
        {
            "section_id": _int(r.get("section_id")),
            "name": r.get("section_name") or None,
            "type": r.get("section_type") or None,
        }
        for r in data
    ]
    rows = [r for r in rows if r["section_id"] is not None]
    with session_scope() as session:
        _upsert(session, Library, rows)
    return len(rows)


# ---- derived: devices ------------------------------------------------------

def refresh_devices() -> int:
    """Rebuild the device inventory from history.

    One GROUP BY beats tracking device state during the history upsert, and it
    self-heals if a sync is ever interrupted mid-batch.
    """
    with session_scope() as session:
        known = {
            (m, u) for m, u in session.execute(select(Device.machine_id, Device.user_id)).all()
        }
        # On a fresh install every device in years of history would flag as
        # "new", which is noise, not a signal. Only devices that turn up in a
        # later sync are genuinely new.
        first_run = not known
        grouped = session.execute(
            select(
                History.machine_id,
                History.user_id,
                func.max(History.player),
                func.max(History.platform),
                func.max(History.product),
                func.min(History.started),
                func.max(History.started),
                func.count(),
            )
            .where(History.machine_id.is_not(None), History.user_id.is_not(None))
            .group_by(History.machine_id, History.user_id)
        ).all()

        rows = [
            {
                "machine_id": machine_id,
                "user_id": user_id,
                "player": player,
                "platform": platform,
                "product": product,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "play_count": plays,
                # Only set on first sighting, so reviewing one sticks.
                **(
                    {}
                    if (machine_id, user_id) in known
                    else {"is_new_unreviewed": not first_run}
                ),
            }
            for machine_id, user_id, player, platform, product, first_seen, last_seen, plays
            in grouped
        ]
        _upsert(session, Device, rows)
        return len(rows)


# ---- geocoding -------------------------------------------------------------

def geocode_new_ips(resolver: GeoResolver) -> int:
    """Resolve IPs seen in history that aren't in the cache yet."""
    if not resolver.available:
        # Caching a miss now would be permanent: these IPs would never be
        # retried once the database arrives. Leave them unresolved instead.
        log.info("no GeoIP database yet; skipping geocode")
        return 0

    with session_scope() as session:
        unknown = [
            ip
            for (ip,) in session.execute(
                select(History.ip_address)
                .where(
                    History.ip_address.is_not(None),
                    History.ip_address != "",
                    ~History.ip_address.in_(select(IpLocation.ip)),
                )
                .distinct()
            ).all()
        ]

        rows = []
        now = datetime.now(UTC)
        for ip in unknown:
            # A None here means the database had no entry, so it is genuinely
            # unresolvable, safe to cache so it isn't retried forever.
            result = resolver.lookup(ip) or {"ip": ip, "is_private": is_private(ip)}
            result["looked_up_at"] = now
            rows.append(result)

        _upsert(session, IpLocation, rows)

    if rows:
        log.info("geocoded %d new IPs", len(rows))
    return len(rows)


# ---- metadata --------------------------------------------------------------

def _split_guids(guids: list[str] | None) -> dict[str, str | None]:
    out: dict[str, str | None] = {"imdb_id": None, "tmdb_id": None, "tvdb_id": None}
    for guid in guids or []:
        for prefix, key in (("imdb://", "imdb_id"), ("tmdb://", "tmdb_id"), ("tvdb://", "tvdb_id")):
            if guid.startswith(prefix):
                out[key] = guid[len(prefix):]
    return out


async def cache_new_metadata(client: TautulliClient, settings: Settings) -> int:
    """Fetch metadata for rating_keys never seen before.

    This is also where history.section_id comes from, because get_history doesn't
    return it, get_metadata does, and the fetch is happening anyway.
    """
    with session_scope() as session:
        missing = [
            key
            for (key,) in session.execute(
                select(History.rating_key)
                .where(
                    History.rating_key.is_not(None),
                    ~History.rating_key.in_(select(MediaItem.rating_key)),
                )
                .distinct()
            ).all()
        ]

    if not missing:
        return 0

    semaphore = asyncio.Semaphore(settings.metadata_concurrency)

    # A key that no longer exists in Plex 400s, and history keeps referencing
    # it forever. Without a tombstone the "not in media_items" filter would
    # re-request every deleted item on every single sync.
    def tombstone(rating_key: int) -> dict:
        return {"rating_key": rating_key, "synced_at": datetime.now(UTC)}

    async def fetch(rating_key: int) -> dict | None:
        async with semaphore:
            try:
                meta = await client.call("get_metadata", rating_key=rating_key)
            except Exception as exc:  # noqa: BLE001 - one bad item shouldn't stop the batch
                log.debug("metadata unavailable for %s: %s", rating_key, exc)
                return tombstone(rating_key)
        if not meta or not meta.get("title"):
            return tombstone(rating_key)
        return {
            "rating_key": rating_key,
            "parent_rating_key": _int(meta.get("parent_rating_key")),
            "grandparent_rating_key": _int(meta.get("grandparent_rating_key")),
            "section_id": _int(meta.get("section_id")),
            "media_type": meta.get("media_type") or None,
            "title": meta.get("title") or None,
            "full_title": meta.get("full_title") or None,
            "year": _int(meta.get("year")),
            "thumb": meta.get("thumb") or None,
            "art": meta.get("art") or None,
            "duration": _int(meta.get("duration")),
            "content_rating": meta.get("content_rating") or None,
            "summary": meta.get("summary") or None,
            **_split_guids(meta.get("guids")),
            "synced_at": datetime.now(UTC),
        }

    results = [r for r in await asyncio.gather(*(fetch(k) for k in missing)) if r]

    with session_scope() as session:
        _upsert(session, MediaItem, results)
        # Backfill the column get_history doesn't provide.
        session.execute(
            text(
                "UPDATE history SET section_id = ("
                "  SELECT section_id FROM media_items WHERE media_items.rating_key ="
                "  history.rating_key) "
                "WHERE section_id IS NULL AND rating_key IS NOT NULL"
            )
        )

    gone = sum(1 for r in results if r.get("title") is None)
    log.info("cached metadata for %d items (%d no longer in Plex)", len(results) - gone, gone)
    return len(results) - gone


# ---- orchestration ---------------------------------------------------------

async def run_sync(client: TautulliClient, settings: Settings, full: bool = False) -> dict:
    """One full cycle. Safe to call concurrently with reads."""
    history = await sync_history(client, settings, full=full)
    metadata = await cache_new_metadata(client, settings)
    devices = refresh_devices()

    resolver = GeoResolver(settings.geoip_dir)
    try:
        ips = geocode_new_ips(resolver)
    finally:
        resolver.close()

    return {"history": history, "metadata": metadata, "devices": devices, "ips": ips}


async def run_slow_sync(client: TautulliClient) -> dict:
    """Users and libraries. Rarely change, own schedule."""
    return {"users": await sync_users(client), "libraries": await sync_libraries(client)}

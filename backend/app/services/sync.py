"""Tautulli -> local SQLite sync.

Keeps a warm mirror and moves only the delta. Never a full rescan: a watermark
bounds the history pull, IPs are geocoded once ever, and metadata is fetched
once per rating_key ever.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update, func, select, text
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import session_scope
from app.settings_store import current as current_settings
from app.geo.lookup import GeoResolver, is_private
from app.models import Device, History, IpLocation, Library, MediaItem, SyncState, User
from app.services import travel
from app.tautulli.client import TautulliClient

log = logging.getLogger(__name__)

WATERMARK = "history_watermark"
BACKFILL_OFFSET = "history_backfill_offset"
EPISODE_NUMBERS = "history_has_episode_numbers"


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
        "grandparent_title": row.get("grandparent_title") or None,
        "parent_media_index": _int(row.get("parent_media_index")),
        "media_index": _int(row.get("media_index")),
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
            "deleted_in_tautulli": False,
        }
        for r in data.get("data") or []
    ]
    rows = [r for r in rows if r["user_id"] is not None]
    listed = {r["user_id"] for r in rows}

    # Which libraries each person has. Only get_users says, not the table.
    try:
        shares = {
            _int(u.get("user_id")): (
                json.dumps([str(x) for x in (u.get("shared_libraries") or []) if str(x)]),
                _bool(u.get("is_allow_sync")),
            )
            for u in (await client.call("get_users") or [])
        }
    except Exception as exc:  # noqa: BLE001 - access review is a bonus on top of the user list
        log.warning("could not read shared libraries: %s", exc)
        shares = {}
    for r in rows:
        if r["user_id"] in shares:
            r["shared_libraries"], r["allow_sync"] = shares[r["user_id"]]

    with session_scope() as session:
        _upsert(session, User, rows)
        # Someone stored before who has dropped off the list since. Rows are
        # never removed, since their history is still here, but what Tautulli
        # now says about them is looked up again below.
        dropped = {
            uid
            for (uid,) in session.execute(select(User.user_id)).all()
            if uid not in listed
        }
    return len(rows) + await sync_missing_users(client, also=dropped)


async def sync_missing_users(client: TautulliClient, also: set[int] | None = None) -> int:
    """Users that history mentions but the user list does not.

    Tautulli leaves a user it has marked deleted out of get_users and
    get_users_table, yet keeps recording their plays, and the Plex account can
    still have access and be streaming. Without this they show as a bare
    number everywhere. get_user still answers for them, so each is looked up
    by id.

    A user Tautulli has no record of at all still gets a row, so their history
    stays reachable from People rather than vanishing with them.
    """
    with session_scope() as session:
        missing = {
            uid
            for (uid,) in session.execute(
                select(History.user_id)
                .where(History.user_id.is_not(None), ~History.user_id.in_(select(User.user_id)))
                .distinct()
            ).all()
        }
    missing |= also or set()
    if not missing:
        return 0

    rows = []
    for uid in sorted(missing):
        try:
            r = await client.call("get_user", user_id=uid) or {}
        except Exception as exc:  # noqa: BLE001 - one unknown user must not stop the sync
            log.debug("could not look up user %s: %s", uid, exc)
            r = {}
        if r.get("user_id") is None:
            # Unknown to Tautulli. Only written if there is no row yet, so a
            # name learned earlier is not overwritten with nothing.
            rows.append({"user_id": uid, "deleted_in_tautulli": True, "_placeholder": True})
            continue
        rows.append(
            {
                "user_id": uid,
                "username": r.get("username") or None,
                "friendly_name": r.get("friendly_name") or None,
                "email": r.get("email") or None,
                "thumb": r.get("user_thumb") or None,
                "is_active": bool(_bool(r.get("is_active")) is not False),
                "is_home_user": bool(_bool(r.get("is_home_user"))),
                "deleted_in_tautulli": bool(_bool(r.get("deleted_user"))),
            }
        )

    known = [{k: v for k, v in r.items()} for r in rows if not r.get("_placeholder")]
    unknown = [r["user_id"] for r in rows if r.get("_placeholder")]
    with session_scope() as session:
        if known:
            _upsert(session, User, known)
        existing = {uid for (uid,) in session.execute(select(User.user_id).where(User.user_id.in_(unknown))).all()}
        for uid in unknown:
            if uid in existing:
                session.execute(update(User).where(User.user_id == uid).values(deleted_in_tautulli=True))
            else:
                session.add(User(user_id=uid, is_active=False, is_home_user=False, deleted_in_tautulli=True))
    if rows:
        log.info("checked %d user(s) missing from Tautulli's user list", len(rows))
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

def geocode_ips(ips: set[str]) -> int:
    """Resolve and store a specific set of addresses.

    Used by the live activity endpoint, where a stream from an address that has
    never appeared in history would otherwise have nowhere to sit on the map
    until the next sync.
    """
    if not ips:
        return 0
    settings = current_settings()
    resolver = GeoResolver(settings.geoip_dir)
    try:
        if not resolver.available:
            return 0
        now = datetime.now(UTC)
        rows = []
        for ip in ips:
            result = resolver.lookup(ip) or {"ip": ip, "is_private": is_private(ip)}
            result["looked_up_at"] = now
            rows.append(result)
        with session_scope() as session:
            _upsert(session, IpLocation, rows)
        return len(rows)
    finally:
        resolver.close()


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


def _tombstone(rating_key: int) -> dict:
    """A key that no longer exists in Plex 400s, and history keeps referencing
    it forever. Without a tombstone the "not in media_items" filter would
    re-request every deleted item on every single sync."""
    return {"rating_key": rating_key, "synced_at": datetime.now(UTC)}


def file_details(meta: dict) -> dict:
    """What the file is, from get_metadata's media_info. Empty values for an
    item with no file (a show, a season, live TV)."""
    media = meta.get("media_info") or []
    first = media[0] if media else {}
    parts = first.get("parts") or []
    part = parts[0] if parts else {}
    streams = part.get("streams") or []
    video = next((s for s in streams if str(s.get("type")) == "1"), {})
    audio = [s for s in streams if str(s.get("type")) == "2"]
    subs = [s for s in streams if str(s.get("type")) == "3"]
    return {
        "file_bitrate": _int(first.get("bitrate")),
        "file_container": first.get("container") or None,
        "file_size": _int(part.get("file_size")),
        "file_path": part.get("file") or None,
        "versions": len(media) or None,
        "video_codec": first.get("video_codec") or video.get("video_codec") or None,
        "video_resolution": first.get("video_full_resolution") or None,
        "video_bit_depth": _int(video.get("video_bit_depth")),
        "video_dynamic_range": video.get("video_dynamic_range") or None,
        "audio_codec": first.get("audio_codec") or None,
        "audio_channels": _int(first.get("audio_channels")),
        "audio_tracks": json.dumps([
            {
                "codec": a.get("audio_codec") or None,
                "channels": _int(a.get("audio_channels")),
                "language": a.get("audio_language_code") or a.get("audio_language") or None,
                "bitrate": _int(a.get("audio_bitrate")),
            }
            for a in audio
        ]) if media else None,
        "subtitle_tracks": json.dumps([
            {
                "codec": s.get("subtitle_codec") or None,
                "language": s.get("subtitle_language_code") or s.get("subtitle_language") or None,
                "forced": bool(_int(s.get("subtitle_forced"))),
                "location": s.get("subtitle_location") or None,
            }
            for s in subs
        ]) if media else None,
        "file_checked_at": datetime.now(UTC),
    }


async def metadata_row(client: TautulliClient, rating_key: int) -> dict:
    """One media_items row from Tautulli, or a tombstone if Plex has no such item."""
    try:
        meta = await client.call("get_metadata", rating_key=rating_key)
    except Exception as exc:  # noqa: BLE001 - one bad item shouldn't stop the batch
        log.debug("metadata unavailable for %s: %s", rating_key, exc)
        return _tombstone(rating_key)
    if not meta or not meta.get("title"):
        return _tombstone(rating_key)
    return {
        "rating_key": rating_key,
        "parent_rating_key": _int(meta.get("parent_rating_key")),
        "grandparent_rating_key": _int(meta.get("grandparent_rating_key")),
        "section_id": _int(meta.get("section_id")),
        "media_type": meta.get("media_type") or None,
        "title": meta.get("title") or None,
        "full_title": meta.get("full_title") or None,
        "grandparent_title": meta.get("grandparent_title") or None,
        "parent_media_index": _int(meta.get("parent_media_index")),
        "media_index": _int(meta.get("media_index")),
        "year": _int(meta.get("year")),
        "thumb": meta.get("thumb") or None,
        "grandparent_thumb": meta.get("grandparent_thumb") or None,
        "parent_thumb": meta.get("parent_thumb") or None,
        "art": meta.get("art") or None,
        "duration": _int(meta.get("duration")),
        "content_rating": meta.get("content_rating") or None,
        "summary": meta.get("summary") or None,
        **_split_guids(meta.get("guids")),
        **file_details(meta),
        "synced_at": datetime.now(UTC),
    }


async def cache_one(rating_key: int) -> None:
    """Fetch and store one item now, for something playing that history has
    not caught up with yet."""
    client = TautulliClient(current_settings())
    try:
        row = await metadata_row(client, rating_key)
    finally:
        await client.aclose()
    with session_scope() as session:
        _upsert(session, MediaItem, [row])


def _copy_episode_numbers() -> None:
    """Episode numbers for titles cached before they were kept. History has
    them, so copying is free where fetching again would be thousands of calls."""
    with session_scope() as session:
        session.execute(
            text(
                "UPDATE media_items SET "
                "  grandparent_title = (SELECT h.grandparent_title FROM history h WHERE h.rating_key = media_items.rating_key AND h.media_index IS NOT NULL LIMIT 1),"
                "  parent_media_index = (SELECT h.parent_media_index FROM history h WHERE h.rating_key = media_items.rating_key AND h.media_index IS NOT NULL LIMIT 1),"
                "  media_index = (SELECT h.media_index FROM history h WHERE h.rating_key = media_items.rating_key AND h.media_index IS NOT NULL LIMIT 1) "
                "WHERE media_type = 'episode' AND media_index IS NULL "
                "AND EXISTS (SELECT 1 FROM history h WHERE h.rating_key = media_items.rating_key AND h.media_index IS NOT NULL)"
            )
        )


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

    _copy_episode_numbers()
    if not missing:
        return 0

    semaphore = asyncio.Semaphore(settings.metadata_concurrency)

    async def fetch(rating_key: int) -> dict | None:
        async with semaphore:
            return await metadata_row(client, rating_key)

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
    # History synced before episode numbers were kept has none. Read it all
    # again once, which fills them in; the upsert makes it safe to repeat.
    with session_scope() as session:
        needs_numbers = _state(session, EPISODE_NUMBERS) is None
    history = await sync_history(client, settings, full=full or needs_numbers)
    if needs_numbers:
        with session_scope() as session:
            _set_state(session, EPISODE_NUMBERS, "1")
    # Cheap when nobody is missing, and a new unknown user should get a name
    # on this sync rather than waiting for the slow one.
    await sync_missing_users(client)
    metadata = await cache_new_metadata(client, settings)
    devices = refresh_devices()

    resolver = GeoResolver(settings.geoip_dir)
    try:
        ips = geocode_new_ips(resolver)
    finally:
        resolver.close()

    # After geocoding, so newly placed addresses are considered straight away.
    flags = travel.find_flags(settings)

    # A stall that looked like a one-off can become a pattern later.
    from app.services import stalls, streams

    try:
        stalls.reclassify()
        streams.prune()
    except Exception:  # noqa: BLE001 - housekeeping must not fail the sync
        log.exception("stall and sample housekeeping failed")

    result = {
        "history": history,
        "metadata": metadata,
        "devices": devices,
        "ips": ips,
        "travel_flags": flags,
    }
    with session_scope() as session:
        # For monitoring: a container that is up but has not synced in hours
        # looks healthy to everything else.
        _set_state(session, "last_sync_at", str(int(datetime.now(UTC).timestamp())))
    await _heartbeat(result)
    return result


async def _heartbeat(result: dict) -> None:
    """Tell Uptime Kuma the sync ran.

    Monitors the sync rather than the container, because a container that is up
    but has not synced in six hours looks perfectly healthy to every other kind
    of check.
    """
    url = current_settings().uptime_kuma_push_url
    if not url:
        return
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            await client.get(
                url, params={"status": "up", "msg": f"synced {result['history']} rows"}
            )
    except Exception as exc:  # noqa: BLE001 - a missed ping must not fail a sync
        log.debug("uptime kuma ping failed: %s", exc)


async def run_slow_sync(client: TautulliClient) -> dict:
    """Users and libraries. Rarely change, own schedule."""
    from app.services.streams import read_plex_upload

    result = {"users": await sync_users(client), "libraries": await sync_libraries(client)}
    await read_plex_upload(client)
    return result

"""Read endpoints. All of them share app.filters.Filters."""

from __future__ import annotations


from datetime import UTC
from urllib.parse import quote
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Select, desc, func, select, update
from sqlalchemy.orm import Session

from app import audit
from app.auth.deps import AdminUser, CurrentUser
from app.db import SessionLocal, session_scope
from app.filters import Filters
from app.models import Device, History, IpLocation, Library, MediaItem, User
from app.integrations import arr, seerr
from app.services import capabilities
from app.services.sync import geocode_ips
from app.settings_store import current, is_configured
from app.tautulli.client import TautulliClient

router = APIRouter(prefix="/api")


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


Db = Annotated[Session, Depends(get_session)]
from app import privacy
from app.privacy import ScopedFilt, ViewerScope

# Filters narrowed to what the signed-in viewer may see (app/privacy.py).
Filt = ScopedFilt

SORTABLE = {
    "started": History.started,
    "user_id": History.user_id,
    "full_title": History.full_title,
    "media_type": History.media_type,
    "platform": History.platform,
    "player": History.player,
    "percent_complete": History.percent_complete,
}


def _filtered(filters: Filters, *columns) -> Select:
    """Base select with the location join added only when a filter needs it."""
    stmt = select(*columns)
    if filters.needs_location_join:
        stmt = stmt.join(IpLocation, IpLocation.ip == History.ip_address)
    conditions = filters.conditions()
    return stmt.where(*conditions) if conditions else stmt


# ---- map -------------------------------------------------------------------

@router.get("/map/points")
def map_points(filters: Filt, db: Db) -> dict:
    """GeoJSON, aggregated server-side by location.

    Aggregating here rather than shipping 13k rows to the browser: the map only
    ever draws one pin per place, so the rows are collapsed before they travel.
    """
    stmt = (
        select(
            IpLocation.lat,
            IpLocation.lon,
            IpLocation.city,
            IpLocation.region,
            IpLocation.country,
            IpLocation.country_code,
            IpLocation.is_hosting,
            IpLocation.asn_org,
            # GeoLite2 places an IP at a city or postal centroid, not an
            # address. Carrying the radius lets the map draw how uncertain
            # each point actually is instead of implying a rooftop.
            func.max(IpLocation.accuracy_radius).label("accuracy_km"),
            func.count().label("plays"),
            func.count(func.distinct(History.user_id)).label("users"),
            func.count(func.distinct(History.machine_id)).label("devices"),
            func.count(func.distinct(History.ip_address)).label("ips"),
            func.max(History.started).label("last_play"),
        )
        .join(IpLocation, IpLocation.ip == History.ip_address)
        .where(IpLocation.lat.is_not(None), IpLocation.lon.is_not(None))
        .group_by(IpLocation.lat, IpLocation.lon)
    )
    conditions = filters.conditions()
    if conditions:
        stmt = stmt.where(*conditions)

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [row.lon, row.lat]},
            "properties": {
                # Repeated from the geometry because MapLibre quantises a
                # clicked feature's coordinates to the tile grid, and the
                # detail lookup matches on the stored value exactly.
                "lat": row.lat,
                "lon": row.lon,
                "city": row.city,
                "region": row.region,
                "country": row.country,
                "country_code": row.country_code,
                "is_hosting": row.is_hosting,
                "asn_org": row.asn_org,
                "accuracy_km": row.accuracy_km,
                "plays": row.plays,
                "users": row.users,
                "devices": row.devices,
                "ips": row.ips,
                "last_play": row.last_play,
            },
        }
        for row in db.execute(stmt).all()
    ]
    return {"type": "FeatureCollection", "features": features}


# ---- history ---------------------------------------------------------------

@router.get("/history")
def history(
    filters: Filt,
    scope: ViewerScope,
    db: Db,
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=1000),
    sort: str = Query("started"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
) -> dict:
    column = SORTABLE.get(sort)
    if column is None:
        raise HTTPException(400, f"Cannot sort by {sort!r}. Try: {', '.join(SORTABLE)}")

    total = db.execute(_filtered(filters, func.count()).select_from(History)).scalar_one()

    stmt = (
        _filtered(filters, History)
        .order_by(desc(column) if order == "desc" else column)
        .limit(size)
        .offset((page - 1) * size)
    )
    rows = db.execute(stmt).scalars().all()

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            privacy.scrub_play(scope, {c.name: getattr(row, c.name) for c in History.__table__.columns}) for row in rows
        ],
    }


@router.get("/history/{row_id}")
async def history_detail(row_id: int, db: Db, scope: ViewerScope) -> dict:
    """Full stream detail for one row.

    Codec/bitrate/resolution are fetched live rather than synced: they need a
    per-row get_stream_data call, and nothing pays for rows nobody opens.
    """
    row = db.get(History, row_id)
    if row is None:
        raise HTTPException(404, "No such history row")
    privacy.require_self(scope, row.user_id)

    base = {c.name: getattr(row, c.name) for c in History.__table__.columns}

    # Everything the expanded row links to, so the page does not need a
    # second round of lookups: who, where, which library, whether banned.
    from app.models import BannedDevice

    user = db.get(User, row.user_id) if row.user_id is not None else None
    base["user_name"] = (user.friendly_name or user.username) if user else None
    loc = db.get(IpLocation, row.ip_address) if row.ip_address else None
    base["place"] = (
        None
        if loc is None
        else {
            "city": loc.city,
            "region": loc.region,
            "country": loc.country,
            "lat": loc.lat,
            "lon": loc.lon,
            "accuracy_km": loc.accuracy_radius,
            "asn_org": loc.asn_org,
            "is_hosting": loc.is_hosting,
            "is_private": loc.is_private,
        }
    )
    library = db.get(Library, row.section_id) if row.section_id is not None else None
    base["library_name"] = library.name if library else None
    base["device_banned"] = bool(row.machine_id and db.get(BannedDevice, row.machine_id))

    if not is_configured():
        base["stream"] = None
        base["stream_error"] = "Tautulli is not configured"
        return base

    client = TautulliClient(current())
    try:
        base["stream"] = await client.call("get_stream_data", row_id=row_id)
    except Exception as exc:  # noqa: BLE001 - detail is a bonus, not the row
        base["stream"] = None
        base["stream_error"] = str(exc)
    finally:
        await client.aclose()
    return base


# ---- media -----------------------------------------------------------------

def _deep_links(item: MediaItem, settings, show: MediaItem | None = None) -> dict[str, str]:
    """External links. Only ones we can build with what's cached. A missing
    id means no button, never a broken one.

    For an episode or season, Plex reports that episode's own TMDB and TVDB
    ids, and a show page built from those lands on the wrong show or on Not
    Found. So TMDB and Trakt link to the show, using the show's ids. Plex and
    IMDb keep the episode itself, since both have real pages for episodes.
    """
    links: dict[str, str] = {}
    episodic = item.media_type in ("show", "season", "episode")
    kind = "tv" if episodic else "movie"
    title_ids = show if (episodic and show is not None) else item

    # Tautulli reports the server id, so the Plex link works without anyone
    # having to find and paste it. An explicit setting still wins.
    server_id = settings.plex_machine_identifier or (
        capabilities.get().get("machine_identifier") or ""
    )
    if server_id:
        links["plex"] = (
            f"https://app.plex.tv/desktop/#!/server/{server_id}"
            f"/details?key=%2Flibrary%2Fmetadata%2F{item.rating_key}"
        )
    if item.imdb_id:
        links["imdb"] = f"https://www.imdb.com/title/{item.imdb_id}/"
    # An episode with no cached show gets no TMDB or Trakt button rather than
    # one that goes somewhere wrong.
    resolved = not episodic or item.media_type == "show" or show is not None
    if title_ids.tmdb_id and resolved:
        links["tmdb"] = f"https://www.themoviedb.org/{kind}/{title_ids.tmdb_id}"
    # Trakt's new site no longer opens a title from a TMDB or IMDb id (those
    # routes 404), and its title pages need a slug only its API gives out. Its
    # search page does work, so the button searches for the title.
    if title_ids.title and resolved:
        links["trakt"] = f"https://app.trakt.tv/search?query={quote(title_ids.title)}"
    return links


async def _cached(db: Session, rating_key: int | None) -> MediaItem | None:
    """A media item, fetched from Tautulli first if it is not cached yet."""
    if rating_key is None:
        return None
    item = db.get(MediaItem, rating_key)
    if item is None and is_configured():
        from app.services.sync import cache_one

        await cache_one(rating_key)
        db.expire_all()
        item = db.get(MediaItem, rating_key)
    return item if item is not None and item.title is not None else None


@router.get("/media/{rating_key}/image")
async def media_image(rating_key: int, db: Db, width: int = 300, height: int = 450):
    """Poster art, proxied through Tautulli.

    Plex image URLs need a token, so the browser cannot fetch them directly and
    handing the token to the browser would be worse. Tautulli already has one,
    and pms_image_proxy resizes on the way through.
    """
    if not is_configured():
        raise HTTPException(409, "Tautulli is not configured")
    item = db.get(MediaItem, rating_key)
    if item is None:
        # Playing now but newer than the last sync. The poster and the links
        # load at the same moment, so this cannot rely on the links request
        # having cached the item first.
        from app.services.sync import cache_one

        await cache_one(rating_key)
        db.expire_all()
        item = db.get(MediaItem, rating_key)
    if item is None or item.title is None:
        raise HTTPException(404, "No artwork for that item")

    art = item.poster_thumb
    if (
        item.media_type in ("episode", "season")
        and item.grandparent_thumb is None
        and item.parent_thumb is None
    ):
        # Cached before show posters were stored, so poster_thumb is falling
        # back to the episode still. Fetch the missing field once rather than
        # making everyone resync years of metadata.
        art = await _backfill_poster(item)
    if not art:
        raise HTTPException(404, "No artwork for that item")

    settings = current()
    base = (settings.tautulli_url or "").rstrip("/")
    params = {
        "apikey": settings.tautulli_api_key,
        "cmd": "pms_image_proxy",
        "img": art,
        "width": width,
        "height": height,
        "fallback": "poster",
    }

    async with httpx.AsyncClient(
        timeout=settings.tautulli_timeout, verify=settings.tautulli_verify_ssl
    ) as client:
        try:
            upstream = await client.get(f"{base}/api/v2", params=params)
            upstream.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"Could not fetch artwork: {exc}") from exc

    return Response(
        content=upstream.content,
        media_type=upstream.headers.get("content-type", "image/jpeg"),
        # Artwork for a given rating_key does not change, so let the browser
        # keep it rather than re-proxying on every panel open.
        headers={"Cache-Control": "public, max-age=86400"},
    )


async def _backfill_poster(item: MediaItem) -> str | None:
    """Fill in the show poster for an episode cached before it was stored."""
    client = TautulliClient(current())
    try:
        meta = await client.call("get_metadata", rating_key=item.rating_key) or {}
    except Exception:  # noqa: BLE001 - fall back to the episode still
        return item.thumb
    finally:
        await client.aclose()

    art = meta.get("grandparent_thumb") or meta.get("parent_thumb") or None
    # Written even when Plex has neither, as an empty string, so an item that
    # genuinely has no show poster is not looked up again on every panel open.
    with session_scope() as db:
        stored = db.get(MediaItem, item.rating_key)
        if stored is not None:
            stored.grandparent_thumb = meta.get("grandparent_thumb") or ""
            stored.parent_thumb = meta.get("parent_thumb") or ""
    return art or item.thumb


@router.get("/media/search")
def media_search(db: Db, q: str = Query(min_length=1), limit: int = Query(20, le=100)) -> list:
    stmt = (
        select(MediaItem)
        .where(MediaItem.title.is_not(None), MediaItem.full_title.ilike(f"%{q}%"))
        .limit(limit)
    )
    return [
        {
            "rating_key": m.rating_key,
            "title": m.full_title or m.title,
            "year": m.year,
            "media_type": m.media_type,
        }
        for m in db.execute(stmt).scalars().all()
    ]


@router.get("/media/{rating_key}")
async def media_detail(rating_key: int, db: Db) -> dict:
    # Something playing right now can be newer than the last sync, so a
    # missing item is fetched once rather than leaving it without links.
    item = await _cached(db, rating_key)
    if item is None:
        raise HTTPException(404, "Not cached, or no longer in Plex")

    # The show an episode or season belongs to. Sonarr, Seerr, TMDB and Trakt
    # all know shows, not episodes, and need the show's ids.
    show = None
    if item.media_type == "episode":
        show = await _cached(db, item.grandparent_rating_key)
    elif item.media_type == "season":
        show = await _cached(db, item.parent_rating_key)
    title_item = show if show is not None else item
    usable_for_title = item.media_type in ("movie", "show") or show is not None

    links = _deep_links(item, current(), show)

    # Radarr and Sonarr link by slug, not by id, so this may need a lookup the
    # first time a title is opened. The result is cached on the item.
    service = arr.for_media_type(item.media_type)
    if service.configured() and usable_for_title:
        link = await service.link_for(title_item)
        if link:
            links[service.name] = link

    link = seerr.seerr.link_for(title_item) if usable_for_title else None
    if link:
        links["seerr"] = link

    return {
        **{c.name: getattr(item, c.name) for c in MediaItem.__table__.columns},
        "links": links,
        "request": await seerr.seerr.request_for(title_item) if usable_for_title else None,
    }


@router.get("/location")
def location_detail(
    db: Db,
    scope: ViewerScope,
    lat: float | None = None,
    lon: float | None = None,
    city: str | None = None,
    country: str | None = None,
    limit: int = Query(25, le=200),
) -> dict:
    """Who watched from a place, on what, from which addresses.

    Matched on coordinates, which is how the map groups pins. Keying on city
    was wrong twice over: plenty of addresses resolve to a country with no city
    at all, leaving the panel empty, and two separate networks in one city
    would be merged even though they are drawn as one pin anyway.
    """
    where = []
    if lat is not None and lon is not None:
        where = [IpLocation.lat == lat, IpLocation.lon == lon]
    elif city:
        where = [IpLocation.city == city]
        if country:
            where.append(IpLocation.country == country)
    if not where:
        raise HTTPException(400, "Give coordinates, or a city")
    me = scope.plex_user_id if scope and scope.plex_user_id is not None else -1
    if scope is not None and scope.own_only:
        where.append(History.user_id == me)

    joined = select(History).join(IpLocation, IpLocation.ip == History.ip_address).where(*where)

    users = db.execute(
        select(
            History.user_id,
            func.coalesce(User.friendly_name, User.username).label("name"),
            func.count().label("plays"),
            func.max(History.started).label("last_play"),
        )
        .join(IpLocation, IpLocation.ip == History.ip_address)
        .join(User, User.user_id == History.user_id, isouter=True)
        .where(*where)
        .group_by(History.user_id)
        .order_by(desc(func.count()))
        .limit(limit)
    ).all()

    devices = db.execute(
        select(
            History.machine_id,
            func.max(History.player).label("player"),
            func.max(History.platform).label("platform"),
            History.user_id,
            func.count().label("plays"),
            func.max(History.started).label("last_play"),
        )
        .join(IpLocation, IpLocation.ip == History.ip_address)
        .where(*where, History.machine_id.is_not(None))
        .group_by(History.machine_id)
        .order_by(desc(func.count()))
        .limit(limit)
    ).all()

    addresses = db.execute(
        select(
            History.ip_address,
            IpLocation.asn_org,
            IpLocation.is_hosting,
            func.count().label("plays"),
            func.max(History.started).label("last_play"),
        )
        .join(IpLocation, IpLocation.ip == History.ip_address)
        .where(*where)
        .group_by(History.ip_address)
        .order_by(desc(func.count()))
        .limit(limit)
    ).all()

    total = db.execute(select(func.count()).select_from(joined.subquery())).scalar_one()

    if scope is not None and not scope.own_only:
        # Anonymised: the viewer's own rows, and everyone else folded into one
        # line with a count, so the place still reads as busy without naming.
        own = [u for u in users if u.user_id == me]
        others = sum(u.plays for u in users if u.user_id != me)
        users = own
        devices = [d for d in devices if d.user_id == me]
        mine = {
            ip for (ip,) in db.execute(
                select(History.ip_address).where(History.user_id == me).distinct()
            ).all()
        }
        addresses = [a for a in addresses if a.ip_address in mine]
    else:
        others = 0

    return {
        "city": city,
        "country": country,
        "other_viewers_plays": others,
        "plays": total,
        "users": [
            {
                "user_id": u.user_id,
                "name": u.name or (str(u.user_id) if u.user_id else "Unknown"),
                "plays": u.plays,
                "last_play": u.last_play,
            }
            for u in users
        ],
        "devices": [
            {
                "machine_id": d.machine_id,
                "player": d.player,
                "platform": d.platform,
                "user_id": d.user_id,
                "plays": d.plays,
                "last_play": d.last_play,
            }
            for d in devices
        ],
        "addresses": [
            {
                "ip_address": a.ip_address,
                "asn_org": a.asn_org,
                "is_hosting": a.is_hosting,
                "plays": a.plays,
                "last_play": a.last_play,
            }
            for a in addresses
        ],
    }


@router.get("/location/plays")
def location_plays(
    db: Db,
    scope: ViewerScope,
    lat: float,
    lon: float,
    size: int = Query(12, le=200),
) -> dict:
    """What was watched from one pin, most recent first."""
    stmt = (
        select(History)
        .join(IpLocation, IpLocation.ip == History.ip_address)
        .where(IpLocation.lat == lat, IpLocation.lon == lon)
        .where(*([History.user_id == (scope.plex_user_id or -1)] if scope is not None and scope.own_only else []))
        .order_by(desc(History.started))
        .limit(size)
    )
    return {
        "items": [
            privacy.scrub_play(scope, {c.name: getattr(row, c.name) for c in History.__table__.columns})
            for row in db.execute(stmt).scalars()
        ]
    }


# ---- directories -----------------------------------------------------------

@router.get("/users")
def users(db: Db, scope: ViewerScope) -> list:
    """Everyone who has ever had access, deleted or not.

    Plays and the last play come from history here rather than from Tautulli,
    which stops reporting last seen for anyone it has marked deleted.
    """
    stats = (
        select(
            History.user_id,
            func.count().label("plays"),
            func.max(History.started).label("last_play"),
        )
        .group_by(History.user_id)
        .subquery()
    )
    stmt = (
        select(User, stats.c.plays, stats.c.last_play)
        .outerjoin(stats, stats.c.user_id == User.user_id)
        .order_by(User.friendly_name)
    )
    if scope is not None:
        # Private modes list only the viewer. Nobody else is named.
        stmt = stmt.where(User.user_id == (scope.plex_user_id if scope.plex_user_id is not None else -1))
    return [
        {
            **{c.name: getattr(u, c.name) for c in User.__table__.columns},
            "plays": plays or 0,
            "last_seen": max(filter(None, (u.last_seen, last_play)), default=None),
        }
        for u, plays, last_play in db.execute(stmt).all()
    ]


@router.post("/users/{user_id}/restore-in-tautulli")
async def restore_in_tautulli(user_id: int, admin: AdminUser, db: Db) -> dict:
    """Clear Tautulli's deleted flag, which puts someone back in its user
    list and dropdowns. History Tautulli erased when they were deleted does
    not come back."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "No such user")
    if not user.deleted_in_tautulli:
        raise HTTPException(409, "Tautulli does not have them marked deleted")
    if not user.username:
        raise HTTPException(409, "Tautulli has no record of this account left to restore")

    name = user.friendly_name or user.username
    client = TautulliClient(current())
    try:
        await client.call("undelete_user", user_id=user_id, username=user.username)
        after = await client.call("get_user", user_id=user_id) or {}
    except Exception as exc:  # noqa: BLE001
        audit.record(admin, "user.restore", f"Tried to restore {name} in Tautulli",
                     target=str(user_id), result=f"failed: {exc}")
        raise HTTPException(502, f"Tautulli refused: {exc}") from exc
    finally:
        await client.aclose()

    if str(after.get("deleted_user")) not in ("0", "False", "false"):
        audit.record(admin, "user.restore", f"Tried to restore {name} in Tautulli",
                     target=str(user_id), result="failed: still marked deleted")
        raise HTTPException(502, "Tautulli still has them marked deleted")

    with session_scope() as session:
        session.execute(update(User).where(User.user_id == user_id).values(deleted_in_tautulli=False))
    audit.record(admin, "user.restore", f"Restored {name} in Tautulli", target=str(user_id))
    return {"user_id": user_id, "deleted_in_tautulli": False}


def _profile(db: Session, where: list) -> dict:
    """Everything history says about one user or one device.

    Shared by both profiles, so a person and a device are described the same
    way: totals, where from, on which networks, and what they watched.
    """
    totals = db.execute(
        select(
            func.count(),
            func.sum(History.play_duration),
            func.count(func.distinct(History.machine_id)),
            func.count(func.distinct(History.ip_address)),
            func.min(History.started),
            func.max(History.started),
            func.count(func.distinct(History.user_id)),
        ).where(*where)
    ).one()

    places = db.execute(
        select(
            IpLocation.city,
            IpLocation.region,
            IpLocation.country,
            func.max(IpLocation.lat).label("lat"),
            func.max(IpLocation.lon).label("lon"),
            func.max(IpLocation.is_hosting).label("is_hosting"),
            func.count().label("plays"),
            func.max(History.started).label("last_play"),
        )
        .join(History, History.ip_address == IpLocation.ip)
        .where(*where)
        .group_by(IpLocation.city, IpLocation.region, IpLocation.country)
        .order_by(desc(func.count()))
        .limit(25)
    ).all()

    addresses = db.execute(
        select(
            History.ip_address,
            func.max(IpLocation.asn_org).label("asn_org"),
            func.max(IpLocation.city).label("city"),
            func.max(IpLocation.is_hosting).label("is_hosting"),
            func.max(History.location).label("location"),
            func.count().label("plays"),
            func.min(History.started).label("first_play"),
            func.max(History.started).label("last_play"),
        )
        .join(IpLocation, IpLocation.ip == History.ip_address, isouter=True)
        .where(*where, History.ip_address.is_not(None))
        .group_by(History.ip_address)
        .order_by(desc(func.max(History.started)))
        .limit(50)
    ).all()

    # Grouped by show rather than episode, named from the cached show where
    # there is one. History itself only stores the episode's own title.
    show_key = func.coalesce(History.grandparent_rating_key, History.rating_key)
    top = db.execute(
        select(
            show_key.label("key"),
            func.max(History.full_title).label("full_title"),
            func.max(History.media_type).label("media_type"),
            func.count().label("plays"),
            func.sum(History.play_duration).label("seconds"),
            func.max(History.started).label("last_play"),
        )
        .where(*where)
        .group_by(show_key)
        .order_by(desc(func.count()))
        .limit(12)
    ).all()
    names = {
        m.rating_key: m.title
        for m in db.execute(
            select(MediaItem).where(MediaItem.rating_key.in_([t.key for t in top if t.key]))
        ).scalars()
    }

    def title_of(t) -> str | None:
        if t.key in names and names[t.key]:
            return names[t.key]
        # "Show - Episode" falls back to the show part.
        full = t.full_title or ""
        return full.split(" - ")[0] if t.media_type == "episode" else full or None

    return {
        "totals": {
            "plays": totals[0],
            "seconds": totals[1] or 0,
            "devices": totals[2],
            "ips": totals[3],
            "first_play": totals[4],
            "last_play": totals[5],
            "users": totals[6],
        },
        "places": [
            {
                "city": x.city,
                "region": x.region,
                "country": x.country,
                "lat": x.lat,
                "lon": x.lon,
                "is_hosting": bool(x.is_hosting),
                "plays": x.plays,
                "last_play": x.last_play,
            }
            for x in places
        ],
        "addresses": [
            {
                "ip_address": a.ip_address,
                "asn_org": a.asn_org,
                "city": a.city,
                "is_hosting": bool(a.is_hosting),
                "location": a.location,
                "plays": a.plays,
                "first_play": a.first_play,
                "last_play": a.last_play,
            }
            for a in addresses
        ],
        "top_media": [
            {
                "rating_key": t.key,
                "title": title_of(t),
                "media_type": "show" if t.media_type == "episode" else t.media_type,
                "plays": t.plays,
                "seconds": t.seconds or 0,
                "last_play": t.last_play,
            }
            for t in top
        ],
    }


@router.get("/users/{user_id}")
def user_detail(user_id: int, db: Db, scope: ViewerScope) -> dict:
    privacy.require_self(scope, user_id)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "No such user")

    devices = db.execute(
        select(Device).where(Device.user_id == user_id).order_by(desc(Device.last_seen))
    ).scalars().all()

    return {
        **{c.name: getattr(user, c.name) for c in User.__table__.columns},
        **_profile(db, [History.user_id == user_id]),
        "devices": [
            {c.name: getattr(d, c.name) for c in Device.__table__.columns} for d in devices
        ],
    }


@router.get("/devices/{machine_id}")
def device_detail(machine_id: str, db: Db, scope: ViewerScope) -> dict:
    """One device, across everyone who has used it. The same install can be
    signed in to more than one account, which is itself worth seeing."""
    rows = db.execute(
        select(Device).where(Device.machine_id == machine_id).order_by(desc(Device.last_seen))
    ).scalars().all()
    if not rows:
        raise HTTPException(404, "No such device")
    if scope is not None:
        # Only a device the viewer has used, and only their own use of it.
        rows = [d for d in rows if scope.is_self(d.user_id)]
        if not rows:
            raise HTTPException(403, "You can only see your own devices")

    names = {
        u.user_id: u.friendly_name or u.username
        for u in db.execute(select(User).where(User.user_id.in_([d.user_id for d in rows]))).scalars()
    }
    # Per account on this device: how much, from where, and what they watched
    # last, so a shared device can be read account by account.
    per_user = {
        uid: (plays, seconds, first, last, ips)
        for uid, plays, seconds, first, last, ips in db.execute(
            select(
                History.user_id,
                func.count(),
                func.sum(History.play_duration),
                func.min(History.started),
                func.max(History.started),
                func.count(func.distinct(History.ip_address)),
            )
            .where(History.machine_id == machine_id)
            .group_by(History.user_id)
        ).all()
    }
    places: dict[int, list[dict]] = {}
    for uid, city, region, country, hosting, plays in db.execute(
        select(
            History.user_id,
            IpLocation.city,
            IpLocation.region,
            IpLocation.country,
            func.max(IpLocation.is_hosting),
            func.count(),
        )
        .join(IpLocation, IpLocation.ip == History.ip_address)
        .where(History.machine_id == machine_id)
        .group_by(History.user_id, IpLocation.city, IpLocation.region, IpLocation.country)
        .order_by(desc(func.count()))
    ).all():
        places.setdefault(uid, []).append(
            {"city": city, "region": region, "country": country, "is_hosting": bool(hosting), "plays": plays}
        )
    last_titles = {}
    for uid, title, started in db.execute(
        select(History.user_id, History.full_title, History.started)
        .where(History.machine_id == machine_id)
        .order_by(desc(History.started))
    ).all():
        last_titles.setdefault(uid, {"title": title, "started": started})
    deleted = {
        u.user_id: bool(u.deleted_in_tautulli)
        for u in db.execute(select(User).where(User.user_id.in_([d.user_id for d in rows]))).scalars()
    }

    latest = rows[0]
    return {
        "machine_id": machine_id,
        "player": latest.player,
        "platform": latest.platform,
        "product": latest.product,
        "first_seen": min((d.first_seen for d in rows if d.first_seen), default=None),
        "last_seen": max((d.last_seen for d in rows if d.last_seen), default=None),
        "is_new_unreviewed": any(d.is_new_unreviewed for d in rows),
        "owners": [
            {
                "user_id": d.user_id,
                "name": names.get(d.user_id) or str(d.user_id),
                "play_count": per_user.get(d.user_id, (d.play_count,))[0],
                "seconds": (per_user.get(d.user_id) or (0, 0))[1] or 0,
                "first_seen": d.first_seen,
                "last_seen": d.last_seen,
                "addresses": (per_user.get(d.user_id) or (0, 0, 0, 0, 0))[4],
                "places": places.get(d.user_id, [])[:5],
                "last_watched": last_titles.get(d.user_id),
                "deleted_in_tautulli": deleted.get(d.user_id, False),
            }
            for d in rows
        ],
        **_profile(
            db,
            [History.machine_id == machine_id]
            + ([History.user_id == scope.plex_user_id] if scope is not None else []),
        ),
    }


@router.get("/addresses/{ip}")
def address_detail(ip: str, db: Db, scope: ViewerScope) -> dict:
    """One IP address: where it is, whose network, and everyone and every
    device that has played from it."""
    only = [History.user_id == scope.plex_user_id] if scope is not None else []
    plays = db.execute(select(func.count()).where(History.ip_address == ip, *only)).scalar_one()
    if not plays:
        if scope is not None:
            raise HTTPException(403, "You can only see addresses you have played from")
        raise HTTPException(404, "No plays from that address")
    loc = db.get(IpLocation, ip)

    names = {u.user_id: u.friendly_name or u.username for u in db.execute(select(User)).scalars()}
    accounts = db.execute(
        select(
            History.user_id,
            func.count(),
            func.sum(History.play_duration),
            func.min(History.started),
            func.max(History.started),
        )
        .where(History.ip_address == ip, *only)
        .group_by(History.user_id)
        .order_by(desc(func.max(History.started)))
    ).all()
    devices = db.execute(
        select(
            History.machine_id,
            func.max(History.player),
            func.max(History.platform),
            func.max(History.user_id),
            func.count(),
            func.max(History.started),
        )
        .where(History.ip_address == ip, History.machine_id.is_not(None), *only)
        .group_by(History.machine_id)
        .order_by(desc(func.max(History.started)))
    ).all()

    return {
        "ip_address": ip,
        "place": None
        if loc is None
        else {
            "city": loc.city,
            "region": loc.region,
            "country": loc.country,
            "lat": loc.lat,
            "lon": loc.lon,
            "accuracy_km": loc.accuracy_radius,
            "asn": loc.asn,
            "asn_org": loc.asn_org,
            "is_hosting": loc.is_hosting,
            "is_private": loc.is_private,
        },
        **_profile(db, [History.ip_address == ip, *only]),
        "accounts": [
            {
                "user_id": uid,
                "name": names.get(uid) or str(uid),
                "plays": count,
                "seconds": seconds or 0,
                "first_play": first,
                "last_play": last,
            }
            for uid, count, seconds, first, last in accounts
        ],
        "devices": [
            {
                "machine_id": mid,
                "player": player,
                "platform": platform,
                "user_id": uid,
                "user_name": names.get(uid),
                "plays": count,
                "last_play": last,
            }
            for mid, player, platform, uid, count, last in devices
        ],
    }


@router.get("/people/activity")
def person_activity(
    db: Db,
    user: CurrentUser,
    user_id: int | None = None,
    machine_id: str | None = None,
    limit: int = Query(100, le=500),
) -> list[dict]:
    """Everything that happened to one user or device, newest first: sharing
    signals, stream actions, and changes made about them.

    Stream actions and changes are admin only, the same as the Log tab.
    """
    from app.models import AuditLog, EnforcementLog, TravelFlag

    if user_id is None and machine_id is None:
        raise HTTPException(400, "Give a user_id or a machine_id")
    scope = privacy.scope_for(user)
    if scope is not None:
        if user_id is not None:
            privacy.require_self(scope, user_id)
        if machine_id is not None and not db.execute(
            select(func.count()).select_from(Device).where(
                Device.machine_id == machine_id, Device.user_id == (scope.plex_user_id or -1)
            )
        ).scalar_one():
            raise HTTPException(403, "You can only see your own devices")

    out: list[dict] = []

    if user_id is not None:
        for flag in db.execute(
            select(TravelFlag).where(TravelFlag.user_id == user_id).order_by(desc(TravelFlag.to_started)).limit(limit)
        ).scalars():
            columns = {c.name: getattr(flag, c.name) for c in TravelFlag.__table__.columns}
            # A flag has its own kind (travel or concurrent), which would
            # otherwise overwrite the event kind this list is sorted by.
            columns["signal_kind"] = columns.pop("kind")
            out.append({**columns, "kind": "signal", "at": flag.to_started})

    if user.role == "admin":
        stream_where = []
        if user_id is not None:
            stream_where.append(EnforcementLog.user_id == user_id)
        if machine_id is not None:
            stream_where.append(EnforcementLog.machine_id == machine_id)
        for row in db.execute(
            select(EnforcementLog).where(*stream_where).order_by(desc(EnforcementLog.acted_at)).limit(limit)
        ).scalars():
            out.append(
                {
                    "kind": "stream",
                    "at": row.acted_at,
                    **{c.name: getattr(row, c.name) for c in EnforcementLog.__table__.columns},
                }
            )

        targets = set()
        if user_id is not None:
            targets.add(str(user_id))
            person = db.get(User, user_id)
            if person and person.username:
                targets.add(person.username)
        if machine_id is not None:
            targets.add(machine_id)
        for row in db.execute(
            select(AuditLog).where(AuditLog.target.in_(targets)).order_by(desc(AuditLog.created_at)).limit(limit)
        ).scalars():
            out.append(
                {
                    "kind": "change",
                    "at": row.created_at,
                    **{c.name: getattr(row, c.name) for c in AuditLog.__table__.columns},
                }
            )

    def stamp(row: dict) -> float:
        at = row["at"]
        if at is None:
            return 0
        if isinstance(at, (int, float)):
            return float(at)
        return at.replace(tzinfo=at.tzinfo or UTC).timestamp()

    for row in out:
        # One clock for the page: signals store epoch seconds, the logs store
        # datetimes.
        row["at_epoch"] = stamp(row)
    out.sort(key=lambda r: r["at_epoch"], reverse=True)
    return out[:limit]


@router.get("/devices")
def devices(db: Db, scope: ViewerScope, user_id: int | None = None, new_only: bool = False) -> list:
    stmt = select(Device).order_by(desc(Device.last_seen))
    if scope is not None:
        stmt = stmt.where(Device.user_id == (scope.plex_user_id if scope.plex_user_id is not None else -1))
    if user_id is not None:
        stmt = stmt.where(Device.user_id == user_id)
    if new_only:
        stmt = stmt.where(Device.is_new_unreviewed.is_(True))
    from app.models import BannedDevice

    banned = {mid for (mid,) in db.execute(select(BannedDevice.machine_id)).all()}
    return [
        {**{c.name: getattr(d, c.name) for c in Device.__table__.columns}, "banned": d.machine_id in banned}
        for d in db.execute(stmt).scalars().all()
    ]


@router.post("/devices/{machine_id}/review")
def review_device(machine_id: str, admin: AdminUser, reviewed: bool = True) -> dict:
    """Clear (or restore) the "new device" flag.

    Admin only: acknowledging a device is how the alert gets dismissed, and a
    viewer dismissing it for everyone would defeat the point.
    """
    with session_scope() as db:
        rows = db.execute(
            update(Device)
            .where(Device.machine_id == machine_id)
            .values(is_new_unreviewed=not reviewed)
        )
        if not rows.rowcount:
            raise HTTPException(404, "No such device")
        device = db.execute(
            select(Device).where(Device.machine_id == machine_id).limit(1)
        ).scalar_one_or_none()
        label = (device.player if device else None) or machine_id[:12]
        owner = device.user_id if device else None

    audit.record(
        admin,
        "device.review" if reviewed else "device.unreview",
        f"Marked {label} as reviewed" if reviewed else f"Marked {label} as new again",
        target=machine_id,
        detail={"player": label, "user_id": owner},
    )
    return {"machine_id": machine_id, "is_new_unreviewed": not reviewed}


@router.get("/libraries")
def libraries(db: Db) -> list:
    stmt = select(Library).order_by(Library.name)
    return [{c.name: getattr(x, c.name) for c in Library.__table__.columns}
            for x in db.execute(stmt).scalars().all()]


@router.get("/filter-options")
def filter_options(db: Db) -> dict[str, list[Any]]:
    """Distinct values for the filter UI, straight from what's actually in
    history, so no hardcoded lists to drift out of date."""

    def distinct(column):
        return [
            v for (v,) in db.execute(
                select(column).where(column.is_not(None)).distinct().order_by(column)
            ).all()
        ]

    return {
        "media_type": distinct(History.media_type),
        "platform": distinct(History.platform),
        "product": distinct(History.product),
        "transcode_decision": distinct(History.transcode_decision),
        "location": distinct(History.location),
        "country_code": distinct(IpLocation.country_code),
    }


# ---- stats -----------------------------------------------------------------

@router.get("/stats/summary")
def stats_summary(filters: Filt, db: Db) -> dict:
    row = db.execute(
        _filtered(
            filters,
            func.count().label("plays"),
            func.count(func.distinct(History.user_id)).label("users"),
            func.count(func.distinct(History.machine_id)).label("devices"),
            func.count(func.distinct(History.ip_address)).label("ips"),
            func.sum(History.play_duration).label("seconds"),
        ).select_from(History)
    ).one()
    return {
        "plays": row.plays,
        "users": row.users,
        "devices": row.devices,
        "ips": row.ips,
        "seconds": row.seconds or 0,
    }


@router.get("/stats/by")
def stats_by(filters: Filt, db: Db, field: str = Query("media_type")) -> list:
    groupable = {
        "media_type": History.media_type,
        "platform": History.platform,
        "product": History.product,
        "player": History.player,
        "transcode_decision": History.transcode_decision,
        "user_id": History.user_id,
        "section_id": History.section_id,
    }
    column = groupable.get(field)
    if column is None:
        raise HTTPException(400, f"Cannot group by {field!r}. Try: {', '.join(groupable)}")

    stmt = (
        _filtered(filters, column.label("key"), func.count().label("plays"))
        .select_from(History)
        .group_by(column)
        .order_by(desc(func.count()))
    )
    return [{"key": row.key, "plays": row.plays} for row in db.execute(stmt).all()]


@router.get("/stats/over-time")
def stats_over_time(filters: Filt, db: Db) -> list:
    day = func.date(History.started, "unixepoch", "localtime").label("day")
    stmt = (
        _filtered(filters, day, func.count().label("plays"))
        .select_from(History)
        .group_by(day)
        .order_by(day)
    )
    return [{"day": row.day, "plays": row.plays} for row in db.execute(stmt).all()]

"""Read endpoints. All of them share app.filters.Filters."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, desc, func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.filters import Filters
from app.models import Device, History, IpLocation, Library, MediaItem, User
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
Filt = Annotated[Filters, Depends()]

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
                "city": row.city,
                "region": row.region,
                "country": row.country,
                "country_code": row.country_code,
                "is_hosting": row.is_hosting,
                "asn_org": row.asn_org,
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
            {c.name: getattr(row, c.name) for c in History.__table__.columns} for row in rows
        ],
    }


@router.get("/history/{row_id}")
async def history_detail(row_id: int, db: Db) -> dict:
    """Full stream detail for one row.

    Codec/bitrate/resolution are fetched live rather than synced: they need a
    per-row get_stream_data call, and nothing pays for rows nobody opens.
    """
    row = db.get(History, row_id)
    if row is None:
        raise HTTPException(404, "No such history row")

    base = {c.name: getattr(row, c.name) for c in History.__table__.columns}
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

def _deep_links(item: MediaItem, settings) -> dict[str, str]:
    """External links. Only ones we can build with what's cached — a missing
    id means no button, never a broken one."""
    links: dict[str, str] = {}
    kind = "tv" if item.media_type in ("show", "season", "episode") else "movie"

    if settings.plex_machine_identifier:
        links["plex"] = (
            f"https://app.plex.tv/desktop/#!/server/{settings.plex_machine_identifier}"
            f"/details?key=%2Flibrary%2Fmetadata%2F{item.rating_key}"
        )
    if item.imdb_id:
        links["imdb"] = f"https://www.imdb.com/title/{item.imdb_id}/"
    if item.tmdb_id:
        links["tmdb"] = f"https://www.themoviedb.org/{kind}/{item.tmdb_id}"
        links["trakt"] = (
            f"https://trakt.tv/search/tmdb/{item.tmdb_id}"
            f"?id_type={'show' if kind == 'tv' else 'movie'}"
        )
    return links


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
def media_detail(rating_key: int, db: Db) -> dict:
    item = db.get(MediaItem, rating_key)
    if item is None or item.title is None:
        raise HTTPException(404, "Not cached, or no longer in Plex")
    return {
        **{c.name: getattr(item, c.name) for c in MediaItem.__table__.columns},
        "links": _deep_links(item, current()),
    }


# ---- directories -----------------------------------------------------------

@router.get("/users")
def users(db: Db) -> list:
    stmt = select(User).order_by(User.friendly_name)
    return [{c.name: getattr(u, c.name) for c in User.__table__.columns}
            for u in db.execute(stmt).scalars().all()]


@router.get("/devices")
def devices(db: Db, user_id: int | None = None, new_only: bool = False) -> list:
    stmt = select(Device).order_by(desc(Device.last_seen))
    if user_id is not None:
        stmt = stmt.where(Device.user_id == user_id)
    if new_only:
        stmt = stmt.where(Device.is_new_unreviewed.is_(True))
    return [{c.name: getattr(d, c.name) for c in Device.__table__.columns}
            for d in db.execute(stmt).scalars().all()]


@router.get("/libraries")
def libraries(db: Db) -> list:
    stmt = select(Library).order_by(Library.name)
    return [{c.name: getattr(x, c.name) for c in Library.__table__.columns}
            for x in db.execute(stmt).scalars().all()]


@router.get("/filter-options")
def filter_options(db: Db) -> dict[str, list[Any]]:
    """Distinct values for the filter UI, straight from what's actually in
    history — no hardcoded lists to drift out of date."""

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

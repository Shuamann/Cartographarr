"""Impossible travel: one account, two places, not enough time in between.

The clearest evidence of a shared password, and the reason the map carries
locations at all. The work is in not crying wolf: GeoLite2 puts an IP at a city
centroid with a stated error of anywhere from 5 km to 1000 km, so a naive
distance check would flag half the library.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from app.config import Settings
from app.db import session_scope
from app.models import History, IpLocation, TravelFlag

log = logging.getLogger(__name__)

EARTH_KM = 6371.0088

CONCURRENT_WINDOW_SECONDS = 120
"""Below this gap, two plays count as happening at the same time."""


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def find_flags(settings: Settings) -> int:
    """Walk each account's plays in order and flag the impossible jumps."""
    with session_scope() as db:
        rows = db.execute(
            select(
                History.row_id,
                History.user_id,
                History.started,
                History.stopped,
                History.ip_address,
                IpLocation.lat,
                IpLocation.lon,
                IpLocation.city,
                IpLocation.accuracy_radius,
                IpLocation.is_hosting,
            )
            .join(IpLocation, IpLocation.ip == History.ip_address)
            .where(
                History.user_id.is_not(None),
                History.started.is_not(None),
                IpLocation.lat.is_not(None),
                IpLocation.is_private.is_(False),
            )
            .order_by(History.user_id, History.started)
        ).all()

    found: list[dict] = []
    previous_by_user: dict[int, tuple] = {}

    for row in rows:
        last = previous_by_user.get(row.user_id)
        previous_by_user[row.user_id] = row
        if last is None or last.ip_address == row.ip_address:
            continue

        # Too vague to draw a conclusion from. A 1000 km stated error can
        # manufacture a 1000 km "journey" out of two plays on the same sofa.
        if max(last.accuracy_radius or 0, row.accuracy_radius or 0) > settings.impossible_max_accuracy_km:
            continue
        if last.city and row.city and last.city == row.city:
            continue

        km = haversine_km(last.lat, last.lon, row.lat, row.lon)
        if km < settings.impossible_min_km:
            continue

        # Measured from the end of the earlier play, since someone can travel
        # while it is running. Using its start would invent journeys.
        departed = last.stopped or last.started
        hours = (row.started - departed) / 3600

        # A gap of seconds is the same phenomenon as an overlap: nobody
        # finished a film and resumed 800 km away half a minute later. Without
        # this floor the speed divides by almost nothing and reports figures
        # like a million kilometres an hour, which reads as a broken feature
        # rather than a real finding.
        if hours * 3600 < CONCURRENT_WINDOW_SECONDS:
            # The earlier play was still running. That is not travel, it is one
            # account playing in two places at once, which is a stronger
            # finding and deserves its own name. Speed means nothing here, so
            # it is not invented.
            kind, kmh = "concurrent", None
        else:
            kmh = km / hours
            if kmh < settings.impossible_kmh:
                continue
            kind = "travel"

        found.append(
            {
                "user_id": row.user_id,
                "from_history_id": last.row_id,
                "to_history_id": row.row_id,
                "from_city": last.city,
                "to_city": row.city,
                "from_ip": last.ip_address,
                "to_ip": row.ip_address,
                "from_started": last.started,
                "to_started": row.started,
                "kind": kind,
                "km": round(km, 1),
                "hours": round(hours, 2) if hours > 0 else 0.0,
                "kmh": round(kmh, 1) if kmh is not None else None,
                "hosting_involved": bool(last.is_hosting or row.is_hosting),
                "created_at": datetime.now(UTC),
            }
        )

    if found:
        with session_scope() as db:
            # Keyed on the later play, so re-running never duplicates a flag
            # and never resets one that has been reviewed.
            stmt = insert(TravelFlag).on_conflict_do_nothing(index_elements=["to_history_id"])
            db.execute(stmt, found)

    log.info("travel: %d flagged pairs", len(found))
    return len(found)

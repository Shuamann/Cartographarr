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
from app.models import History, IpLocation, SignalIgnore, TravelFlag

log = logging.getLogger(__name__)

EARTH_KM = 6371.0088

CONCURRENT_WINDOW_SECONDS = 120
"""Below this gap, two plays count as happening at the same time."""

PAUSE_SLACK_SECONDS = 600
"""Allowed on top of watch time for ordinary pauses when working out when a
play last had anyone watching it."""


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def place_key(city: str | None, asn_org: str | None, is_hosting: bool | None, ip: str | None) -> str:
    """What one end of a signal is, for matching an ignore pattern.

    A VPN or hosting network is named by the network: its exit can land in a
    different city every day, and ignoring "their VPN" should keep working.
    Anywhere else is named by the city. An address with neither falls back to
    the address itself, which is narrow but never matches too much.
    """
    if is_hosting and asn_org:
        return f"network:{asn_org}"
    if city:
        return f"city:{city}"
    return f"ip:{ip}"


def pair(a: str, b: str) -> tuple[str, str]:
    """Order-free, so moving either way between two places is one pattern."""
    return (a, b) if a <= b else (b, a)


def where_of(flag) -> tuple[str, str]:
    """The two ends of a flag, as something that can be counted.

    The stored keys are filled in the first time a signal is opened, so older
    flags fall back to the city and then to the address. Order free, because
    Topeka to Chicago and Chicago to Topeka are the same route.
    """
    ends = (
        (flag.from_key or flag.from_city or flag.from_ip or "?"),
        (flag.to_key or flag.to_city or flag.to_ip or "?"),
    )
    return pair(*ends)


def times_seen(db, user_ids: list[int]) -> dict[tuple[int, str, str], int]:
    """How often each account has been flagged between the same two places.

    A pair that keeps coming back is nearly always how that connection routes:
    a phone on a carrier network that lands in a different city each evening,
    or a VPN with a favourite exit. Genuine sharing does not repeat the same
    two cities twenty times. Shown rather than hidden, because it is the
    person looking who knows which of their friends travels.
    """
    from app.models import TravelFlag

    if not user_ids:
        return {}
    counts: dict[tuple[int, str, str], int] = {}
    for flag in db.execute(select(TravelFlag).where(TravelFlag.user_id.in_(user_ids))).scalars():
        a, b = where_of(flag)
        counts[(flag.user_id, a, b)] = counts.get((flag.user_id, a, b), 0) + 1
    return counts


def ignore_patterns() -> dict[tuple[int, str, str], int]:
    with session_scope() as db:
        return {
            (i.user_id, i.key_a, i.key_b): i.id
            for i in db.execute(select(SignalIgnore)).scalars()
        }


def find_flags(settings: Settings) -> int:
    """Walk each account's plays in order and flag the impossible jumps."""
    with session_scope() as db:
        rows = db.execute(
            select(
                History.row_id,
                History.user_id,
                History.started,
                History.stopped,
                History.play_duration,
                History.ip_address,
                IpLocation.lat,
                IpLocation.lon,
                IpLocation.city,
                IpLocation.accuracy_radius,
                IpLocation.is_hosting,
                IpLocation.asn_org,
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
    patterns = ignore_patterns()

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
        #
        # The end is when it was last actually watched, not when the session
        # closed. A phone left paused keeps its session open for hours or days,
        # and measuring from that made a person pausing on their phone and
        # later watching on their TV look like two people at once. Watch time
        # after the start is the most that can have been watched, plus a few
        # minutes of slack for pauses along the way.
        departed = last.stopped or last.started
        if last.play_duration:
            departed = min(departed, last.started + last.play_duration + PAUSE_SLACK_SECONDS)
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

        from_key = place_key(last.city, last.asn_org, last.is_hosting, last.ip_address)
        to_key = place_key(row.city, row.asn_org, row.is_hosting, row.ip_address)
        ignored_by = patterns.get((row.user_id, *pair(from_key, to_key)))

        found.append(
            {
                "user_id": row.user_id,
                "from_key": from_key,
                "to_key": to_key,
                "status": "ignored" if ignored_by else "new",
                "ignore_id": ignored_by,
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

    with session_scope() as db:
        if found:
            # Keyed on the later play, so re-running never duplicates a flag
            # and never resets one that has been reviewed.
            stmt = insert(TravelFlag).on_conflict_do_nothing(index_elements=["to_history_id"])
            db.execute(stmt, found)

        # Every run walks all of history, so an open signal that is not found
        # again no longer qualifies: the detection got stricter, or history
        # changed. Those are cleared. Anything a person reviewed or ignored is
        # left alone, since that decision is theirs.
        still = {f["to_history_id"] for f in found}
        stale = [
            flag
            for flag in db.execute(select(TravelFlag).where(TravelFlag.status == "new")).scalars()
            if flag.to_history_id not in still
        ]
        for flag in stale:
            db.delete(flag)
        if stale:
            log.info("travel: cleared %d open signal(s) that no longer qualify", len(stale))

    log.info("travel: %d flagged pairs", len(found))
    return len(found)

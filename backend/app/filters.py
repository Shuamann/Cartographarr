"""One filter model, one predicate builder.

Every read endpoint takes the same query parameters and runs them through
`conditions()`. Adding a filter here makes it work on the map, the history
table and the stats at once.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated

from fastapi import Query
from sqlalchemy import ColumnElement, or_

from app.models import History, IpLocation

ListParam = Annotated[list[str] | None, Query()]
IntListParam = Annotated[list[int] | None, Query()]


def _epoch(day: date) -> int:
    """Midnight local time as a unix timestamp.

    Not strftime("%s"), which is glibc-only and silently absent on Windows.
    Local rather than UTC because "plays on the 14th" means the user's 14th.
    """
    return int(datetime.combine(day, time.min).timestamp())


class Filters:
    """FastAPI dependency. Declared as a plain class so the query parameters
    stay visible in the OpenAPI schema without a second duplicated model."""

    def __init__(
        self,
        start: Annotated[date | None, Query(description="Plays on or after this date")] = None,
        end: Annotated[date | None, Query(description="Plays on or before this date")] = None,
        user_id: IntListParam = None,
        media_type: ListParam = None,
        platform: ListParam = None,
        player: ListParam = None,
        product: ListParam = None,
        machine_id: ListParam = None,
        ip_address: ListParam = None,
        section_id: IntListParam = None,
        rating_key: int | None = None,
        transcode_decision: ListParam = None,
        location: Annotated[str | None, Query(description="lan or wan")] = None,
        secure: bool | None = None,
        relayed: bool | None = None,
        country_code: ListParam = None,
        city: str | None = None,
        is_hosting: Annotated[
            bool | None, Query(description="Stream came from a hosting/VPN ASN")
        ] = None,
        watched: Annotated[
            bool | None, Query(description="Finished (percent_complete >= 90)")
        ] = None,
        search: Annotated[str | None, Query(description="Substring of the title")] = None,
    ) -> None:
        self.start = start
        self.end = end
        self.user_id = user_id
        self.media_type = media_type
        self.platform = platform
        self.player = player
        self.product = product
        self.machine_id = machine_id
        self.ip_address = ip_address
        self.section_id = section_id
        self.rating_key = rating_key
        self.transcode_decision = transcode_decision
        self.location = location
        self.secure = secure
        self.relayed = relayed
        self.country_code = country_code
        self.city = city
        self.is_hosting = is_hosting
        self.watched = watched
        self.search = search

    @property
    def needs_location_join(self) -> bool:
        return any((self.country_code, self.city, self.is_hosting is not None))

    def conditions(self) -> list[ColumnElement[bool]]:
        where: list[ColumnElement[bool]] = []

        if self.start:
            where.append(History.started >= _epoch(self.start))
        if self.end:
            # Inclusive of the whole end day.
            where.append(History.started < _epoch(self.end) + 86400)

        for column, values in (
            (History.user_id, self.user_id),
            (History.media_type, self.media_type),
            (History.platform, self.platform),
            (History.player, self.player),
            (History.product, self.product),
            (History.machine_id, self.machine_id),
            (History.ip_address, self.ip_address),
            (History.section_id, self.section_id),
            (History.transcode_decision, self.transcode_decision),
        ):
            if values:
                where.append(column.in_(values))

        if self.rating_key is not None:
            # Match the episode itself or anything under its show/season, so
            # picking a series on the map shows every episode's plays.
            where.append(
                or_(
                    History.rating_key == self.rating_key,
                    History.parent_rating_key == self.rating_key,
                    History.grandparent_rating_key == self.rating_key,
                )
            )

        if self.location:
            where.append(History.location == self.location)
        if self.secure is not None:
            where.append(History.secure.is_(self.secure))
        if self.relayed is not None:
            where.append(History.relayed.is_(self.relayed))
        if self.watched is not None:
            threshold = History.percent_complete >= 90
            where.append(threshold if self.watched else ~threshold)
        if self.search:
            where.append(History.full_title.ilike(f"%{self.search}%"))

        if self.country_code:
            where.append(IpLocation.country_code.in_(self.country_code))
        if self.city:
            where.append(IpLocation.city.ilike(f"%{self.city}%"))
        if self.is_hosting is not None:
            where.append(IpLocation.is_hosting.is_(self.is_hosting))

        return where

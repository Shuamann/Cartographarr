"""Reports: one query builder over everything Cartographarr records.

A report is a source (plays, buffering, rule matches), a measure (how many,
how long, how many different), a dimension to group by and optionally a
second one to split each row by. Every source shares the same dimensions
where it has the data, so "by device" means the same thing for plays and for
buffering, and a new source only has to say which columns it has.

Filters are the same query parameters as the map and History. A filter a
source cannot apply is reported back as ignored rather than silently dropped,
so a report never looks narrower than it is.

Presets are ordinary report specs. Each one is run in the tests, so a preset
cannot rot into an error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import ColumnElement, and_, case, func, literal, or_, select
from sqlalchemy.orm import Session

from app.filters import Filters, _epoch
from app.models import Device, EnforcementLog, History, IpLocation, Library, MediaItem, StreamEvent, User

OTHER = "__other__"
TIME_FORMATS = {
    "day": "%Y-%m-%d",
    "week": "%Y-W%W",
    "month": "%Y-%m",
    "hour": "%H",
    "weekday": "%w",
}
WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


@dataclass(frozen=True)
class Measure:
    key: str
    label: str
    unit: str  # count, hours, minutes, seconds, percent
    expr: Callable[[], ColumnElement]
    hint: str | None = None


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str
    group: str
    # How the page links a row: user, device, address, media, or nothing.
    kind: str | None = None
    # Shown to viewers only as their own, since it names someone or something they watched.
    identifying: bool = False
    requires: tuple[str, ...] = ()
    hint: str | None = None


@dataclass
class Source:
    key: str
    label: str
    blurb: str
    table: Any
    admin_only: bool
    measures: list[Measure]
    # Dimension key to column expression. A dimension absent here is not offered.
    columns: dict[str, Callable[[], ColumnElement]]
    # Filter name to column, for sources other than plays.
    filter_columns: dict[str, Callable[[], ColumnElement]] = field(default_factory=dict)
    time_column: Callable[[], ColumnElement] | None = None
    epoch_time: bool = False
    joins_location: bool = False


DIMENSIONS: list[Dimension] = [
    Dimension("user", "User", "Who", kind="user", identifying=True),
    Dimension("device", "Device", "Who", kind="device", identifying=True),
    Dimension("player", "Player name", "Who", identifying=True),
    Dimension("platform", "Platform", "Device"),
    Dimension("product", "App", "Device"),
    Dimension("address", "Address", "Where", kind="address", identifying=True),
    Dimension("network", "Network", "Where", identifying=True, requires=("geoip",)),
    Dimension("city", "City", "Where", requires=("geoip",)),
    Dimension("country", "Country", "Where", requires=("geoip",)),
    Dimension("vpn", "VPN or hosting", "Where", requires=("geoip",)),
    Dimension("location", "Local or remote", "Where"),
    Dimension("title", "Title", "What", kind="media", identifying=True),
    Dimension("show", "Show or movie", "What", kind="media", identifying=True,
              hint="Episodes grouped under their show."),
    Dimension("media_type", "Media type", "What"),
    Dimension("library", "Library", "What"),
    Dimension("transcode_decision", "Direct play or transcode", "Quality"),
    Dimension("video_resolution", "Resolution", "Quality"),
    Dimension("quality_profile", "Quality profile", "Quality"),
    Dimension("rule", "Rule", "Rules"),
    Dimension("outcome", "Outcome", "Rules"),
    Dimension("day", "Day", "When"),
    Dimension("week", "Week", "When"),
    Dimension("month", "Month", "When"),
    Dimension("hour", "Hour of day", "When"),
    Dimension("weekday", "Day of week", "When"),
]
DIMENSION = {d.key: d for d in DIMENSIONS}


def _count() -> ColumnElement:
    return func.count()


SOURCES: dict[str, Source] = {
    "plays": Source(
        key="plays",
        label="Plays",
        blurb="Finished plays synced from Tautulli.",
        table=History,
        admin_only=False,
        joins_location=True,
        epoch_time=True,
        time_column=lambda: History.started,
        measures=[
            Measure("plays", "Plays", "count", _count),
            Measure("hours", "Watch time", "hours", lambda: func.coalesce(func.sum(History.play_duration), 0) / 3600.0),
            Measure("users", "Different users", "count", lambda: func.count(func.distinct(History.user_id))),
            Measure("devices", "Different devices", "count", lambda: func.count(func.distinct(History.machine_id))),
            Measure("addresses", "Different addresses", "count", lambda: func.count(func.distinct(History.ip_address))),
            Measure("titles", "Different titles", "count", lambda: func.count(func.distinct(History.rating_key))),
            Measure("transcodes", "Transcoded plays", "count",
                    lambda: func.sum(case((History.transcode_decision == "transcode", 1), else_=0))),
            Measure("completion", "Average completion", "percent", lambda: func.avg(History.percent_complete)),
        ],
        columns={
            "user": lambda: History.user_id,
            "device": lambda: History.machine_id,
            "player": lambda: History.player,
            "platform": lambda: History.platform,
            "product": lambda: History.product,
            "address": lambda: History.ip_address,
            "network": lambda: IpLocation.asn_org,
            "city": lambda: IpLocation.city,
            "country": lambda: IpLocation.country,
            "vpn": lambda: IpLocation.is_hosting,
            "location": lambda: History.location,
            "title": lambda: History.rating_key,
            "show": lambda: func.coalesce(History.grandparent_rating_key, History.rating_key),
            "media_type": lambda: History.media_type,
            "library": lambda: History.section_id,
            "transcode_decision": lambda: History.transcode_decision,
        },
    ),
    "buffering": Source(
        key="buffering",
        label="Buffering",
        blurb="Stalls seen while watching live activity. Recorded from the moment this feature was installed.",
        table=StreamEvent,
        admin_only=True,
        joins_location=True,
        time_column=lambda: StreamEvent.started_at,
        measures=[
            Measure("episodes", "Times buffered", "count", _count),
            Measure("minutes", "Time spent buffering", "minutes",
                    lambda: func.coalesce(func.sum(StreamEvent.seconds), 0) / 60.0),
            Measure("average", "Average stall", "seconds", lambda: func.avg(StreamEvent.seconds)),
            Measure("longest", "Longest stall", "seconds", lambda: func.max(StreamEvent.seconds)),
            Measure("streams", "Streams affected", "count", lambda: func.count(func.distinct(StreamEvent.session_key))),
            Measure("users", "Different users", "count", lambda: func.count(func.distinct(StreamEvent.user_id))),
            Measure("devices", "Different devices", "count", lambda: func.count(func.distinct(StreamEvent.machine_id))),
            Measure("bandwidth", "Average bandwidth", "kbps", lambda: func.avg(StreamEvent.bandwidth),
                    hint="Plex's bandwidth estimate for the stream when it stalled."),
        ],
        columns={
            "user": lambda: StreamEvent.user_id,
            "device": lambda: StreamEvent.machine_id,
            "player": lambda: StreamEvent.player,
            "platform": lambda: StreamEvent.platform,
            "product": lambda: StreamEvent.product,
            "address": lambda: StreamEvent.ip_address,
            "network": lambda: IpLocation.asn_org,
            "city": lambda: IpLocation.city,
            "country": lambda: IpLocation.country,
            "vpn": lambda: IpLocation.is_hosting,
            "location": lambda: StreamEvent.location,
            "title": lambda: StreamEvent.rating_key,
            "media_type": lambda: StreamEvent.media_type,
            "transcode_decision": lambda: StreamEvent.transcode_decision,
            "video_resolution": lambda: StreamEvent.video_resolution,
            "quality_profile": lambda: StreamEvent.quality_profile,
        },
        filter_columns={
            "user_id": lambda: StreamEvent.user_id,
            "machine_id": lambda: StreamEvent.machine_id,
            "ip_address": lambda: StreamEvent.ip_address,
            "platform": lambda: StreamEvent.platform,
            "product": lambda: StreamEvent.product,
            "player": lambda: StreamEvent.player,
            "media_type": lambda: StreamEvent.media_type,
            "transcode_decision": lambda: StreamEvent.transcode_decision,
            "location": lambda: StreamEvent.location,
            "rating_key": lambda: StreamEvent.rating_key,
            "search": lambda: StreamEvent.full_title,
            "country_code": lambda: IpLocation.country_code,
            "city": lambda: IpLocation.city,
            "is_hosting": lambda: IpLocation.is_hosting,
        },
    ),
    "matches": Source(
        key="matches",
        label="Rule matches",
        blurb="Streams a rule matched or someone stopped by hand, from the Log.",
        table=EnforcementLog,
        admin_only=True,
        time_column=lambda: EnforcementLog.acted_at,
        measures=[
            Measure("matches", "Matches", "count", _count),
            Measure("stopped", "Streams stopped", "count", lambda: func.sum(
                case((and_(EnforcementLog.dry_run.is_(False), EnforcementLog.result.ilike("%terminated%")), 1), else_=0)
            )),
            Measure("recorded", "Recorded only", "count",
                    lambda: func.sum(case((EnforcementLog.dry_run.is_(True), 1), else_=0))),
            Measure("users", "Different users", "count", lambda: func.count(func.distinct(EnforcementLog.user_id))),
            Measure("devices", "Different devices", "count", lambda: func.count(func.distinct(EnforcementLog.machine_id))),
        ],
        columns={
            "user": lambda: EnforcementLog.user_id,
            "device": lambda: EnforcementLog.machine_id,
            "player": lambda: EnforcementLog.player,
            "platform": lambda: EnforcementLog.platform,
            "product": lambda: EnforcementLog.product,
            "address": lambda: EnforcementLog.ip_address,
            "network": lambda: EnforcementLog.asn_org,
            "city": lambda: EnforcementLog.city,
            "country": lambda: EnforcementLog.country,
            "vpn": lambda: EnforcementLog.is_hosting,
            "location": lambda: EnforcementLog.location,
            "title": lambda: EnforcementLog.rating_key,
            "show": lambda: func.coalesce(EnforcementLog.grandparent_rating_key, EnforcementLog.rating_key),
            "media_type": lambda: EnforcementLog.media_type,
            "library": lambda: EnforcementLog.library_name,
            "transcode_decision": lambda: EnforcementLog.transcode_decision,
            "video_resolution": lambda: EnforcementLog.video_resolution,
            "quality_profile": lambda: EnforcementLog.quality_profile,
            "rule": lambda: EnforcementLog.rule_name,
            "outcome": lambda: case(
                (EnforcementLog.dry_run.is_(True), literal("Recorded only")),
                (EnforcementLog.result.ilike("refused%"), literal("Refused")),
                (EnforcementLog.result.ilike("%failed%"), literal("Failed")),
                (EnforcementLog.result.ilike("%terminated%"), literal("Stopped")),
                else_=literal("Acted"),
            ),
        },
        filter_columns={
            "user_id": lambda: EnforcementLog.user_id,
            "machine_id": lambda: EnforcementLog.machine_id,
            "ip_address": lambda: EnforcementLog.ip_address,
            "platform": lambda: EnforcementLog.platform,
            "product": lambda: EnforcementLog.product,
            "player": lambda: EnforcementLog.player,
            "media_type": lambda: EnforcementLog.media_type,
            "transcode_decision": lambda: EnforcementLog.transcode_decision,
            "location": lambda: EnforcementLog.location,
            "rating_key": lambda: EnforcementLog.rating_key,
            "search": lambda: EnforcementLog.full_title,
            "city": lambda: EnforcementLog.city,
            "is_hosting": lambda: EnforcementLog.is_hosting,
        },
    ),
}

# Starting points. Ordinary specs: open one, change it, save it as your own.
PRESETS: list[dict[str, Any]] = [
    {"id": "buffering-device", "name": "Buffering by device", "source": "buffering", "measure": "episodes",
     "group": "device", "then": "transcode_decision", "range": "30"},
    {"id": "buffering-network", "name": "Buffering by network", "source": "buffering", "measure": "minutes",
     "group": "network", "then": None, "range": "30"},
    {"id": "buffering-user", "name": "Buffering by user", "source": "buffering", "measure": "episodes",
     "group": "user", "then": "video_resolution", "range": "30"},
    {"id": "buffering-daily", "name": "Buffering per day", "source": "buffering", "measure": "episodes",
     "group": "day", "then": None, "range": "30"},
    {"id": "watch-time-user", "name": "Watch time by user", "source": "plays", "measure": "hours",
     "group": "user", "then": "media_type", "range": "30"},
    {"id": "plays-hour", "name": "When people watch", "source": "plays", "measure": "plays",
     "group": "hour", "then": None, "range": "90"},
    {"id": "transcodes-device", "name": "Transcodes by device", "source": "plays", "measure": "plays",
     "group": "device", "then": "transcode_decision", "range": "30"},
    {"id": "top-shows", "name": "Most watched", "source": "plays", "measure": "hours",
     "group": "show", "then": None, "range": "30"},
    {"id": "vpn-users", "name": "Plays from VPNs, by user", "source": "plays", "measure": "plays",
     "group": "user", "then": "network", "range": "90", "filters": "is_hosting=true"},
    {"id": "matches-rule", "name": "Rule matches by rule", "source": "matches", "measure": "matches",
     "group": "rule", "then": "outcome", "range": "30"},
]


def catalog(*, admin: bool, geoip: bool) -> dict[str, Any]:
    """What the builder can offer this person."""
    sources = []
    for s in SOURCES.values():
        if s.admin_only and not admin:
            continue
        dims = [d for d in DIMENSIONS if d.key in s.columns or (d.key in TIME_FORMATS and s.time_column)]
        sources.append({
            "key": s.key,
            "label": s.label,
            "blurb": s.blurb,
            "measures": [{"key": m.key, "label": m.label, "unit": m.unit, "hint": m.hint} for m in s.measures],
            "dimensions": [
                {
                    "key": d.key, "label": d.label, "group": d.group, "kind": d.kind, "hint": d.hint,
                    "unavailable": ("Needs GeoIP set up" if "geoip" in d.requires and not geoip else None),
                }
                for d in dims
            ],
        })
    allowed = {s["key"] for s in sources}
    return {"sources": sources, "presets": [p for p in PRESETS if p["source"] in allowed]}


def validate(source: str, measure: str, group: str, then: str | None) -> Source:
    s = SOURCES.get(source)
    if s is None:
        raise ValueError(f"No report source called {source!r}")
    if not any(m.key == measure for m in s.measures):
        raise ValueError(f"{s.label} has no measure called {measure!r}")
    for dim in (group, then):
        if dim is None:
            continue
        if dim not in s.columns and not (dim in TIME_FORMATS and s.time_column):
            raise ValueError(f"{s.label} cannot be grouped by {dim!r}")
    if then is not None and then == group:
        raise ValueError("Split by must be different from group by")
    return s


def _dimension_expr(s: Source, key: str) -> ColumnElement:
    if key in TIME_FORMATS:
        assert s.time_column is not None
        if s.epoch_time:
            return func.strftime(TIME_FORMATS[key], s.time_column(), "unixepoch", "localtime")
        return func.strftime(TIME_FORMATS[key], s.time_column(), "localtime")
    return s.columns[key]()


def _where(s: Source, filters: Filters) -> tuple[list[ColumnElement[bool]], list[str], bool]:
    """Predicates for the filters, the filters that could not apply, and
    whether the location table is needed."""
    if s.key == "plays":
        return filters.conditions(), [], filters.needs_location_join

    where: list[ColumnElement[bool]] = []
    ignored: list[str] = []
    needs_location = False
    time_col = s.time_column() if s.time_column else None

    if filters.start and time_col is not None:
        where.append(time_col >= datetime.fromtimestamp(_epoch(filters.start), UTC))
    if filters.end and time_col is not None:
        where.append(time_col < datetime.fromtimestamp(_epoch(filters.end) + 86400, UTC))

    for name in (
        "user_id", "machine_id", "ip_address", "platform", "product", "player", "media_type",
        "transcode_decision", "section_id", "country_code",
    ):
        values = getattr(filters, name)
        if not values:
            continue
        column = s.filter_columns.get(name)
        if column is None:
            ignored.append(name)
            continue
        col = column()
        needs_location |= getattr(col, "table", None) is IpLocation.__table__
        where.append(col.in_(values))

    for name in ("location", "city", "search", "is_hosting", "rating_key"):
        value = getattr(filters, name)
        if value is None or value == "":
            continue
        column = s.filter_columns.get(name)
        if column is None:
            ignored.append(name)
            continue
        col = column()
        needs_location |= getattr(col, "table", None) is IpLocation.__table__
        if name in ("city", "search"):
            where.append(col.ilike(f"%{value}%"))
        elif name == "is_hosting":
            where.append(col.is_(value))
        else:
            where.append(col == value)

    for name in ("secure", "relayed", "watched"):
        if getattr(filters, name) is not None:
            ignored.append(name)
    return where, ignored, needs_location


def _base(s: Source, columns: list[ColumnElement], where: list, needs_location: bool):
    stmt = select(*columns).select_from(s.table)
    if needs_location and s.joins_location:
        ip_col = History.ip_address if s.table is History else StreamEvent.ip_address
        stmt = stmt.outerjoin(IpLocation, IpLocation.ip == ip_col)
    if where:
        stmt = stmt.where(*where)
    return stmt


def run(
    db: Session,
    filters: Filters,
    *,
    source: str,
    measure: str,
    group: str,
    then: str | None = None,
    limit: int = 25,
    columns_limit: int = 8,
) -> dict[str, Any]:
    s = validate(source, measure, group, then)
    m = next(x for x in s.measures if x.key == measure)
    where, ignored, needs_location = _where(s, filters)
    uses_location = any(
        d in ("network", "city", "country", "vpn") for d in (group, then) if d
    ) and s.joins_location
    needs_location = needs_location or uses_location

    is_time = group in TIME_FORMATS
    g = _dimension_expr(s, group).label("grp")
    value = m.expr().label("val")

    # Row totals come from their own grouping, not by adding up the split, since
    # averages and "different" counts do not add up.
    stmt = _base(s, [g, value], where, needs_location).group_by(g)
    stmt = stmt.order_by(g) if is_time else stmt.order_by(value.desc(), g)
    rows = db.execute(stmt).all()
    truncated = False
    if not is_time and len(rows) > limit:
        rows, truncated = rows[:limit], True

    grand = db.execute(_base(s, [m.expr().label("val")], where, needs_location)).scalar()

    result_rows = [{"key": r.grp, "value": _num(r.val)} for r in rows]
    columns: list[dict[str, Any]] = []
    if then:
        t = _dimension_expr(s, then).label("split")
        t_is_time = then in TIME_FORMATS
        col_stmt = _base(s, [t, m.expr().label("val")], where, needs_location).group_by(t)
        col_stmt = col_stmt.order_by(t) if t_is_time else col_stmt.order_by(m.expr().desc(), t)
        col_rows = db.execute(col_stmt).all()
        kept = [r.split for r in (col_rows if t_is_time else col_rows[:columns_limit])]
        has_other = not t_is_time and len(col_rows) > columns_limit
        columns = [{"key": k} for k in kept] + ([{"key": OTHER}] if has_other else [])

        cell_stmt = _base(s, [g, t, m.expr().label("val")], where, needs_location).group_by(g, t)
        cells: dict[Any, dict[Any, float]] = {}
        additive = _additive(m)
        kept_set = set(kept)
        for r in db.execute(cell_stmt).all():
            gk, tk = r.grp, r.split
            bucket = tk if tk in kept_set else OTHER
            row = cells.setdefault(gk, {})
            if bucket == OTHER:
                # "Other" can only be summed for additive measures. For the
                # rest it is left out rather than shown wrong.
                if additive:
                    row[OTHER] = row.get(OTHER, 0) + (_num(r.val) or 0)
            else:
                row[bucket] = _num(r.val)
        if has_other and not additive:
            columns = [c for c in columns if c["key"] != OTHER]
        for row in result_rows:
            row["cells"] = cells.get(row["key"], {})

    if is_time:
        result_rows = _fill_gaps(group, result_rows, _additive(m))

    labels = _labels(db, group, [r["key"] for r in result_rows])
    for row in result_rows:
        row["label"] = labels.get(row["key"], _plain_label(group, row["key"]))
    if then:
        col_labels = _labels(db, then, [c["key"] for c in columns])
        for c in columns:
            c["label"] = "Other" if c["key"] == OTHER else col_labels.get(c["key"], _plain_label(then, c["key"]))

    dim = DIMENSION[group]
    return {
        "source": s.key,
        "measure": {"key": m.key, "label": m.label, "unit": m.unit, "additive": _additive(m)},
        "group": {"key": dim.key, "label": dim.label, "kind": dim.kind, "time": is_time},
        "then": None if not then else {"key": then, "label": DIMENSION[then].label, "kind": DIMENSION[then].kind},
        "rows": result_rows,
        "columns": columns,
        "total": _num(grand),
        "truncated": truncated,
        "ignored": ignored,
    }


def _fill_gaps(dim: str, rows: list[dict[str, Any]], additive: bool) -> list[dict[str, Any]]:
    """Time with nothing in it still gets a row, so a chart does not close up
    the quiet hours or days and make the busy ones look adjacent."""
    empty = 0 if additive else None
    have = {r["key"]: r for r in rows}
    if dim == "hour":
        keys = [f"{h:02d}" for h in range(24)]
    elif dim == "weekday":
        keys = [str(d) for d in range(7)]
    elif dim == "day" and rows:
        first = datetime.strptime(rows[0]["key"], "%Y-%m-%d").date()
        last = datetime.strptime(rows[-1]["key"], "%Y-%m-%d").date()
        if (last - first).days > 3660:
            return rows
        keys = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    else:
        return rows
    filler = {"cells": {}} if rows and "cells" in rows[0] else {}
    return [have.get(k) or {"key": k, "value": empty, **filler} for k in keys]


def _additive(m: Measure) -> bool:
    """Whether parts add up to the whole. Sums and counts do; averages, maxima
    and counts of different things do not."""
    return m.unit in ("count", "hours", "minutes") and m.key not in ("users", "devices", "addresses", "titles", "streams")


def _num(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    f = float(value)
    return int(f) if f.is_integer() else round(f, 2)


def _plain_label(dim: str, key: Any) -> str:
    if key is None or key == "":
        return {"vpn": "Not looked up", "location": "Unknown"}.get(dim, "Unknown")
    if dim == "vpn":
        return "VPN or hosting" if key in (True, 1, "1") else "Home or mobile network"
    if dim == "location":
        return {"lan": "Local", "wan": "Remote"}.get(str(key), str(key))
    if dim == "hour":
        return f"{int(key):02d}:00"
    if dim == "weekday":
        return WEEKDAYS[int(key)]
    if dim == "transcode_decision":
        return {"direct play": "Direct play", "copy": "Direct stream", "transcode": "Transcode"}.get(str(key), str(key))
    return str(key)


def _labels(db: Session, dim: str, keys: list[Any]) -> dict[Any, str]:
    """Names for ids: users, devices, libraries and titles."""
    present = [k for k in keys if k not in (None, OTHER)]
    if not present:
        return {}
    if dim == "user":
        rows = db.execute(select(User.user_id, User.friendly_name, User.username).where(User.user_id.in_(present))).all()
        return {r.user_id: r.friendly_name or r.username or f"User {r.user_id}" for r in rows}
    if dim == "device":
        rows = db.execute(
            select(Device.machine_id, Device.player, Device.platform)
            .where(Device.machine_id.in_(present))
            .order_by(Device.last_seen.desc())
        ).all()
        out: dict[Any, str] = {}
        for r in rows:
            out.setdefault(r.machine_id, f"{r.player or r.machine_id}{f' ({r.platform})' if r.platform else ''}")
        return out
    if dim == "library":
        ints = [k for k in present if isinstance(k, int)]
        rows = db.execute(select(Library.section_id, Library.name).where(Library.section_id.in_(ints))).all()
        return {r.section_id: r.name or f"Library {r.section_id}" for r in rows}
    if dim in ("title", "show"):
        ints = [int(k) for k in present if str(k).isdigit()]
        rows = db.execute(select(MediaItem.rating_key, MediaItem.full_title, MediaItem.title).where(
            MediaItem.rating_key.in_(ints)
        )).all()
        found = {r.rating_key: (r.full_title or r.title) for r in rows}
        if dim == "title":
            # Episodes read with their number, as everywhere else.
            for r in db.execute(
                select(History.rating_key, History.grandparent_title, History.title,
                       History.parent_media_index, History.media_index)
                .where(History.rating_key.in_(ints), History.media_index.is_not(None),
                       History.parent_media_index.is_not(None))
                .group_by(History.rating_key)
            ).all():
                found[r.rating_key] = " - ".join(
                    x for x in (r.grandparent_title, f"S{r.parent_media_index:02d}E{r.media_index:02d}", r.title) if x
                )
        # Titles not in the metadata cache fall back to what the play recorded.
        missing = [k for k in ints if not found.get(k)]
        if missing:
            for r in db.execute(
                select(History.rating_key, History.grandparent_rating_key, History.full_title, History.title)
                .where(or_(History.rating_key.in_(missing), History.grandparent_rating_key.in_(missing)))
            ).all():
                if r.rating_key in missing and not found.get(r.rating_key):
                    found[r.rating_key] = r.full_title or r.title
                if dim == "show" and r.grandparent_rating_key in missing and not found.get(r.grandparent_rating_key):
                    full = r.full_title or ""
                    found[r.grandparent_rating_key] = full.split(" - ")[0] if " - " in full else full
        return {k: v for k, v in found.items() if v}
    return {}

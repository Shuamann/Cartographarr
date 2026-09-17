"""Rule conditions: a tree of groups and conditions.

    {"type": "group", "op": "and" | "or", "negate": false, "items": [
        {"type": "condition", "field": "platform", "op": "any", "value": ["Roku"]},
        {"type": "group", "op": "or", "items": [...]},
    ]}

A group is ALL or ANY of its items, optionally negated, and groups nest, which
covers "this AND (that OR the other)" without a query language. Every field
is described once in FIELDS: its type decides the operators, the value editor
in the UI, and how it is compared here.

Safety over cleverness:
- A rule with no conditions anywhere matches nothing.
- A condition on a value the session does not have is false, never true.
  "Country is none of X" on a stream with no known country does not match,
  because an unknown location is not evidence of being somewhere else.
- A rule using a field whose requirement is missing (no GeoIP database, no
  Seerr) is refused as a whole rather than evaluated with that part skipped,
  since dropping one condition from an AND makes the rule broader.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

Session = dict[str, Any]
Context = dict[str, Any]
Tree = dict[str, Any]

OPS: dict[str, list[tuple[str, str]]] = {
    "choice": [("any", "is any of"), ("none", "is none of")],
    "text": [
        ("contains", "contains"),
        ("not_contains", "does not contain"),
        ("equals", "is"),
        ("not_equals", "is not"),
        ("starts", "starts with"),
    ],
    "number": [("gt", "more than"), ("gte", "at least"), ("lt", "less than"), ("lte", "at most"), ("eq", "exactly")],
    "bool": [("is", "is")],
    "cidr": [("in", "is in"), ("not_in", "is not in")],
    "time": [("between", "is between"), ("not_between", "is not between")],
    "weekday": [("any", "is any of"), ("none", "is none of")],
    # A count over a time window: the value is [count, hours].
    "window": [("gt", "more than"), ("gte", "at least"), ("lt", "fewer than"), ("lte", "at most"), ("eq", "exactly")],
}


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    group: str
    type: str
    get: Callable[[Session, Context], Any]
    requires: tuple[str, ...] = ()
    hint: str | None = None
    # Where the UI gets choices from: a name the /rules/fields endpoint fills
    # in, or fixed pairs.
    options: str | None = None
    fixed: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    unit: str | None = None


def _geo(ctx: Context, key: str) -> Any:
    return (ctx.get("geo") or {}).get(key)


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolution(session: Session, _ctx: Context) -> list[str]:
    # Tautulli reports "4k", "1080", "720", "sd" in one field and "1080p" in
    # another depending on version, so both are offered and trailing p dropped.
    values = {session.get("video_full_resolution"), session.get("video_resolution")}
    return [str(v).lower().rstrip("p") for v in values if v]


FIELDS: list[Field] = [
    # ---- who -----------------------------------------------------------------
    Field("user", "User", "Who", "choice", lambda s, c: s.get("user_id"), options="users"),
    Field("username", "Username", "Who", "text", lambda s, c: s.get("friendly_name") or s.get("username")),
    Field(
        "user_streams", "Streams by this user right now", "Who", "number",
        lambda s, c: c.get("user_stream_count"),
        hint="Counts every stream the same account has open, on any device",
    ),
    Field(
        "sharing_signal", "User has an open sharing signal", "Who", "bool",
        lambda s, c: c.get("open_travel_flag"),
        hint="Set when the account was seen in two places too far apart to travel between",
    ),
    # ---- device --------------------------------------------------------------
    Field(
        "device", "Device", "Device", "choice", lambda s, c: s.get("machine_id"), options="devices",
        hint="Matched on the device id, so renaming the player does not escape it",
    ),
    Field("player", "Player name", "Device", "text", lambda s, c: s.get("player"), hint="The viewer can rename this"),
    Field("platform", "Platform", "Device", "choice", lambda s, c: s.get("platform"), options="platforms"),
    Field("product", "App", "Device", "choice", lambda s, c: s.get("product"), options="products"),
    Field(
        "device_new", "Device is new and unreviewed", "Device", "bool",
        lambda s, c: c.get("device_unreviewed"),
    ),
    # ---- media ---------------------------------------------------------------
    Field("library", "Library", "Media", "choice", lambda s, c: s.get("section_id"), options="libraries"),
    Field(
        "media_type", "Type", "Media", "choice", lambda s, c: s.get("media_type"),
        fixed=(("movie", "Movie"), ("episode", "Episode"), ("track", "Music"), ("clip", "Clip"), ("photo", "Photo")),
    ),
    Field("title", "Title", "Media", "text", lambda s, c: s.get("full_title")),
    Field("content_rating", "Content rating", "Media", "choice", lambda s, c: s.get("content_rating"), options="content_ratings"),
    Field("year", "Year", "Media", "number", lambda s, c: s.get("year")),
    Field(
        "requested_by_viewer", "Viewer requested this title", "Media", "bool",
        lambda s, c: c.get("requested_by_viewer"),
        requires=("integration:seerr",),
        hint="Compares the Seerr requester with the Plex account watching",
    ),
    # ---- playback ------------------------------------------------------------
    Field(
        "stream", "Stream", "Playback", "choice", lambda s, c: s.get("transcode_decision"),
        fixed=(("direct play", "Direct play"), ("copy", "Direct stream"), ("transcode", "Transcode")),
    ),
    Field(
        "resolution", "Source resolution", "Playback", "choice", _resolution,
        fixed=(("4k", "4K"), ("1080", "1080p"), ("720", "720p"), ("576", "576p"), ("480", "480p"), ("sd", "SD")),
    ),
    Field(
        "state", "State", "Playback", "choice", lambda s, c: s.get("state"),
        fixed=(("playing", "Playing"), ("paused", "Paused"), ("buffering", "Buffering")),
    ),
    Field("paused_minutes", "Paused for", "Playback", "number", lambda s, c: c.get("paused_minutes"), unit="minutes"),
    Field(
        "buffering_seconds", "Buffering right now for", "Playback", "number",
        lambda s, c: c.get("buffering_seconds"), unit="seconds",
        hint="How long this stall has lasted. Measured each activity check, so accurate to a few seconds.",
    ),
    Field(
        "buffer_count", "Times buffered, this stream", "Playback", "number",
        lambda s, c: c.get("buffer_count"), unit="times",
        hint="Stalls since Cartographarr first saw this stream, including one happening now.",
    ),
    Field(
        "buffer_total_seconds", "Time spent buffering, this stream", "Playback", "number",
        lambda s, c: c.get("buffer_total_seconds"), unit="seconds",
    ),
    Field(
        "tracked_seconds", "Stream running for", "Playback", "number",
        lambda s, c: c.get("tracked_seconds"), unit="seconds",
        hint="Time since Cartographarr first saw this stream. Pair with buffering to catch stalls at the start.",
    ),
    Field("progress", "Progress", "Playback", "number", lambda s, c: s.get("progress_percent"), unit="%"),
    Field("bandwidth", "Bandwidth", "Playback", "number", lambda s, c: s.get("bandwidth"), unit="kbps"),
    Field("quality", "Quality profile", "Playback", "text", lambda s, c: s.get("quality_profile")),
    Field("server_streams", "Streams on the server right now", "Playback", "number", lambda s, c: c.get("server_stream_count")),
    # ---- network and place ---------------------------------------------------
    Field(
        "location", "Network", "Where", "choice", lambda s, c: s.get("location"),
        fixed=(("lan", "Local (LAN)"), ("wan", "Remote (WAN)")),
    ),
    Field(
        "ip", "IP address", "Where", "cidr", lambda s, c: s.get("ip_address"),
        hint="Addresses or ranges, comma separated, for example 203.0.113.0/24",
    ),
    Field("relayed", "Through the Plex relay", "Where", "bool", lambda s, c: _bool(s.get("relayed"))),
    Field("country", "Country", "Where", "choice", lambda s, c: _geo(c, "country_code"), options="countries", requires=("geoip",)),
    Field("region", "Region or state", "Where", "text", lambda s, c: _geo(c, "region"), requires=("geoip",)),
    Field("city", "City", "Where", "text", lambda s, c: _geo(c, "city"), requires=("geoip",)),
    Field(
        "vpn", "VPN or hosting provider", "Where", "bool",
        lambda s, c: _geo(c, "is_hosting") if c.get("geo") else c.get("is_hosting"),
        requires=("geoip",),
    ),
    Field("isp", "Internet provider", "Where", "text", lambda s, c: _geo(c, "asn_org"), requires=("geoip",)),
    # ---- recent history --------------------------------------------------------
    # Counts over the last N hours. Plays are finished plays from history, so a
    # stream still running is not counted until it ends and syncs.
    Field("user_plays_window", "Plays by this user", "Recent history", "window", lambda s, c: None),
    Field("user_devices_window", "Devices this user used", "Recent history", "window", lambda s, c: None),
    Field("user_addresses_window", "Addresses this user used", "Recent history", "window", lambda s, c: None),
    Field(
        "user_cities_window", "Cities this user played from", "Recent history", "window",
        lambda s, c: None, requires=("geoip",),
        hint="Several cities in a short time is a sign of a shared account.",
    ),
    Field(
        "user_buffering_window", "Times this user buffered", "Recent history", "window", lambda s, c: None,
        hint="Stalls Cartographarr recorded across all of this user's streams.",
    ),
    Field("device_buffering_window", "Times this device buffered", "Recent history", "window", lambda s, c: None),
    # ---- when ------------------------------------------------------------------
    Field(
        "time", "Time of day", "When", "time", lambda s, c: c.get("now"),
        hint="Server time. A range can cross midnight, for example 23:00 to 06:00",
    ),
    Field(
        "weekday", "Day of the week", "When", "weekday", lambda s, c: c.get("now"),
        fixed=(("0", "Mon"), ("1", "Tue"), ("2", "Wed"), ("3", "Thu"), ("4", "Fri"), ("5", "Sat"), ("6", "Sun")),
    ),
]

BY_KEY = {f.key: f for f in FIELDS}


def _bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes")


# ---- evaluation --------------------------------------------------------------


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _norm(value: Any) -> str:
    return str(value).strip().lower()


def _minutes(hhmm: str) -> int | None:
    try:
        h, m = str(hhmm).split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, TypeError):
        return None


def _condition(node: Tree, session: Session, ctx: Context) -> bool:
    spec = BY_KEY.get(node.get("field", ""))
    if spec is None:
        return False
    op = node.get("op")
    want = node.get("value")
    have = spec.get(session, ctx)

    if spec.type == "choice":
        haves = {_norm(v) for v in _as_list(have) if v is not None and v != ""}
        wants = {_norm(v) for v in _as_list(want)}
        if not haves or not wants:
            return False
        hit = bool(haves & wants)
        return hit if op == "any" else (not hit if op == "none" else False)

    if spec.type == "text":
        if have is None or want in (None, ""):
            return False
        h, w = _norm(have), _norm(want)
        return {
            "contains": w in h,
            "not_contains": w not in h,
            "equals": h == w,
            "not_equals": h != w,
            "starts": h.startswith(w),
        }.get(op, False)

    if spec.type == "number":
        h, w = _num(have), _num(want)
        if h is None or w is None:
            return False
        return {"gt": h > w, "gte": h >= w, "lt": h < w, "lte": h <= w, "eq": h == w}.get(op, False)

    if spec.type == "bool":
        if have is None or want is None:
            return False
        return bool(have) is bool(want)

    if spec.type == "cidr":
        if not have:
            return False
        try:
            address = ipaddress.ip_address(str(have))
        except ValueError:
            return False
        networks = []
        for raw in _as_list(want):
            for part in str(raw).replace("\n", ",").split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    networks.append(ipaddress.ip_network(part, strict=False))
                except ValueError:
                    continue
        if not networks:
            return False
        inside = any(address.version == n.version and address in n for n in networks)
        return inside if op == "in" else (not inside if op == "not_in" else False)

    if spec.type == "time":
        now: datetime | None = have
        bounds = _as_list(want)
        if now is None or len(bounds) != 2:
            return False
        start, end = _minutes(bounds[0]), _minutes(bounds[1])
        if start is None or end is None:
            return False
        minute = now.hour * 60 + now.minute
        # A window that wraps past midnight is the two halves either side of it.
        inside = start <= minute < end if start <= end else (minute >= start or minute < end)
        return inside if op == "between" else (not inside if op == "not_between" else False)

    if spec.type == "window":
        bounds = _as_list(want)
        counter = ctx.get("window_count")
        if len(bounds) != 2 or not callable(counter):
            return False
        n, hours = _num(bounds[0]), _num(bounds[1])
        if n is None or hours is None or hours <= 0:
            return False
        h = counter(spec.key, session, hours)
        if h is None:
            return False
        return {"gt": h > n, "gte": h >= n, "lt": h < n, "lte": h <= n, "eq": h == n}.get(op, False)

    if spec.type == "weekday":
        now = have
        days = {str(d) for d in _as_list(want)}
        if now is None or not days:
            return False
        hit = str(now.weekday()) in days
        return hit if op == "any" else (not hit if op == "none" else False)

    return False


def _group(node: Tree, session: Session, ctx: Context) -> bool | None:
    """True or False, or None for a group with nothing in it, which is left
    out of its parent rather than counting either way."""
    results = [
        r
        for item in node.get("items") or []
        if (r := (_group(item, session, ctx) if item.get("type") == "group" else _condition(item, session, ctx)))
        is not None
    ]
    if not results:
        return None
    outcome = all(results) if node.get("op", "and") == "and" else any(results)
    return not outcome if node.get("negate") else outcome


def evaluate(tree: Tree | None, session: Session, ctx: Context) -> bool:
    """Whether a session matches. A tree with no conditions matches nothing."""
    if not tree or not count(tree):
        return False
    return bool(_group(tree, session, ctx))


def count(tree: Tree | None) -> int:
    if not tree:
        return 0
    if tree.get("type") == "condition":
        return 1
    return sum(count(i) for i in tree.get("items") or [])


def fields_used(tree: Tree | None) -> set[str]:
    if not tree:
        return set()
    if tree.get("type") == "condition":
        return {tree.get("field", "")}
    return set().union(*(fields_used(i) for i in tree.get("items") or [])) if tree.get("items") else set()


# ---- validation ----------------------------------------------------------------

MAX_DEPTH = 4


def validate(tree: Any, depth: int = 0) -> Tree:
    """Raise ValueError with something a person can act on."""
    if not isinstance(tree, dict) or tree.get("type") != "group":
        raise ValueError("Conditions must start with a group")
    if depth >= MAX_DEPTH:
        raise ValueError(f"Groups can nest {MAX_DEPTH} deep at most")
    if tree.get("op", "and") not in ("and", "or"):
        raise ValueError("A group is either all or any of its conditions")

    items = []
    for item in tree.get("items") or []:
        if not isinstance(item, dict):
            raise ValueError("Unreadable condition")
        if item.get("type") == "group":
            items.append(validate(item, depth + 1))
            continue
        spec = BY_KEY.get(item.get("field", ""))
        if spec is None:
            raise ValueError(f"Unknown condition {item.get('field')!r}")
        ops = {o for o, _ in OPS[spec.type]}
        if item.get("op") not in ops:
            raise ValueError(f"{spec.label}: pick how to compare it")
        value = item.get("value")
        if spec.type in ("choice", "weekday") and not _as_list(value):
            raise ValueError(f"{spec.label}: choose at least one")
        if spec.type in ("text", "cidr") and not str(value or "").strip():
            raise ValueError(f"{spec.label}: needs a value")
        if spec.type == "number" and _num(value) is None:
            raise ValueError(f"{spec.label}: needs a number")
        if spec.type == "bool" and not isinstance(value, bool):
            raise ValueError(f"{spec.label}: choose yes or no")
        if spec.type == "window":
            bounds = _as_list(value)
            if len(bounds) != 2 or _num(bounds[0]) is None or _num(bounds[1]) is None:
                raise ValueError(f"{spec.label}: needs a count and a number of hours")
            if not 0 < float(bounds[1]) <= 24 * 90:
                raise ValueError(f"{spec.label}: hours must be between 1 and {24 * 90}")
        if spec.type == "time":
            bounds = _as_list(value)
            if len(bounds) != 2 or any(_minutes(b) is None for b in bounds):
                raise ValueError(f"{spec.label}: needs a start and an end time")
        if spec.type == "cidr":
            for part in str(value).replace("\n", ",").split(","):
                if part.strip():
                    try:
                        ipaddress.ip_network(part.strip(), strict=False)
                    except ValueError as exc:
                        raise ValueError(f"{spec.label}: {part.strip()!r} is not an address or range") from exc
        items.append({"type": "condition", "field": spec.key, "op": item["op"], "value": value})

    return {"type": "group", "op": tree.get("op", "and"), "negate": bool(tree.get("negate")), "items": items}


# ---- the old flat columns ----------------------------------------------------------


def from_legacy(rule: Any) -> Tree:
    """The tree equivalent of a rule saved before conditions were a tree.

    Every set column was ANDed, which is exactly one ALL group.
    """
    items: list[Tree] = []

    def add(field_key: str, op: str, value: Any) -> None:
        items.append({"type": "condition", "field": field_key, "op": op, "value": value})

    if rule.match_user_id is not None:
        add("user", "any", [rule.match_user_id])
    if rule.match_machine_id:
        add("device", "any", [rule.match_machine_id])
    if rule.match_player:
        add("player", "equals", rule.match_player)
    if rule.match_platform:
        add("platform", "any", [rule.match_platform])
    if rule.match_product:
        add("product", "any", [rule.match_product])
    if rule.match_ip_cidr:
        add("ip", "in", rule.match_ip_cidr)
    if rule.match_transcode_decision:
        add("stream", "any", [rule.match_transcode_decision])
    if rule.match_video_resolution:
        add("resolution", "any", [str(rule.match_video_resolution).lower().rstrip("p")])
    if rule.match_location:
        add("location", "any", [rule.match_location])
    if rule.match_is_hosting is not None:
        add("vpn", "is", bool(rule.match_is_hosting))
    if rule.match_concurrent_streams_gt is not None:
        add("user_streams", "gt", rule.match_concurrent_streams_gt)
    if rule.match_paused_minutes_gt is not None:
        add("paused_minutes", "gt", rule.match_paused_minutes_gt)

    return {"type": "group", "op": "and", "negate": False, "items": items}


def catalogue() -> list[dict[str, Any]]:
    """FIELDS for the UI, without the getters."""
    return [
        {
            "key": f.key,
            "label": f.label,
            "group": f.group,
            "type": f.type,
            "ops": [{"value": v, "label": label} for v, label in OPS[f.type]],
            "requires": list(f.requires),
            "hint": f.hint,
            "options": f.options,
            "fixed": [{"value": v, "label": label} for v, label in f.fixed],
            "unit": f.unit,
        }
        for f in FIELDS
    ]

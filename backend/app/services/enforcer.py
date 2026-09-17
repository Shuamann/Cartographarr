"""Rule evaluation against live sessions.

Plex has no API to ban a shared user's device, so blocking is behavioural:
poll get_activity, match the session, run the action. This is what Tautulli's
kill-stream notification agents do, with a rule table and an audit trail.

Ships in dry run. Turning that off is a deliberate act after reading the log.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.actions import registry
from app.db import session_scope
from app.models import BannedDevice, Device, EnforcementLog, IpLocation, Rule, TravelFlag
from app.services import conditions, tracker
from app.settings_store import current, is_configured, locked_keys
from app.tautulli.client import TautulliClient

log = logging.getLogger(__name__)

Session = dict[str, Any]

# One session shouldn't spam the log while a stubborn client retries.
_recent: dict[tuple[int, str], float] = {}

# Rule and stream pairs already dealt with for the life of the stream. A rule
# that only records or notifies stays true while the stream runs (a count over
# the last day stays true for hours), so without this it would log and notify
# again every cooldown. Stopping is left to the cooldown, so a failed stop is
# retried. Keyed on record only as well, so switching a rule to act still acts.
_done: set[tuple[int, str, bool]] = set()


def _ip_in_cidr(ip: str | None, cidr: str | None) -> bool:
    if not ip or not cidr:
        return False
    try:
        # A bare address is a valid /32, so "match this one IP" needs no
        # special case.
        return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False


def _equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    return str(left).strip().lower() == str(right).strip().lower()


def rule_tree(rule: Rule) -> conditions.Tree:
    if rule.conditions:
        try:
            return json.loads(rule.conditions)
        except ValueError:
            log.warning("rule %s has unreadable conditions, treating as empty", rule.id)
            return {"type": "group", "op": "and", "items": []}
    return conditions.from_legacy(rule)


def rule_actions(rule: Rule) -> list[dict[str, Any]]:
    if rule.actions:
        try:
            parsed = json.loads(rule.actions)
            if isinstance(parsed, list):
                return parsed
        except ValueError:
            log.warning("rule %s has unreadable actions", rule.id)
            return []
    return [{"name": rule.action, "params": {"message": rule.message}}]


def matches(rule: Rule, session: Session, context: dict[str, Any]) -> bool:
    """Whether a rule matches a session. A rule with no conditions matches
    nothing: an empty rule silently killing every stream would be the worst
    possible default."""
    return conditions.evaluate(rule_tree(rule), session, context)


def unmet_requirements(tree: conditions.Tree) -> list[str]:
    """Requirements of the fields a tree uses that are not met right now."""
    needed = {
        requirement
        for key in conditions.fields_used(tree)
        if (spec := conditions.BY_KEY.get(key))
        for requirement in spec.requires
    }
    missing = []
    if "geoip" in needed and not (current().geoip_dir / "city.mmdb").exists():
        missing.append("geoip")
    if "integration:seerr" in needed:
        from app.integrations.seerr import seerr

        if not seerr.configured():
            missing.append("integration:seerr")
    return sorted(missing)


def _hosting_ips(ips: set[str]) -> set[str]:
    if not ips:
        return set()
    with session_scope() as session:
        rows = session.execute(
            select(IpLocation.ip).where(IpLocation.ip.in_(ips), IpLocation.is_hosting.is_(True))
        ).all()
    return {ip for (ip,) in rows}


def _paused_minutes(session: Session) -> float | None:
    """How long this session has been paused, if it is.

    Tautulli doesn't report a paused-since timestamp on live sessions, so this
    uses the accumulated pause counter. It answers "has this been sitting
    paused" well enough to free a transcode slot, which is the point.
    """
    if str(session.get("state")).lower() != "paused":
        return None
    try:
        return float(session.get("paused_counter") or 0) / 60.0
    except (TypeError, ValueError):
        return None


def _build_context(sessions: list[Session]) -> dict[str, dict[str, Any]]:
    """What conditions need beyond the session itself, per session_key."""
    per_user: dict[Any, int] = {}
    for s in sessions:
        per_user[s.get("user_id")] = per_user.get(s.get("user_id"), 0) + 1

    ips = {s["ip_address"] for s in sessions if s.get("ip_address")}
    users = {_int(s.get("user_id")) for s in sessions} - {None}
    machines = {s.get("machine_id") for s in sessions if s.get("machine_id")}

    with session_scope() as db:
        places = {
            row.ip: {
                "city": row.city,
                "region": row.region,
                "country": row.country,
                "country_code": row.country_code,
                "is_hosting": row.is_hosting,
                "asn_org": row.asn_org,
            }
            for row in db.execute(select(IpLocation).where(IpLocation.ip.in_(ips))).scalars()
        } if ips else {}
        flagged = {
            uid
            for (uid,) in db.execute(
                select(TravelFlag.user_id).where(
                    TravelFlag.user_id.in_(users), TravelFlag.status == "new"
                )
            ).all()
        } if users else set()
        unreviewed = {
            (mid, uid)
            for mid, uid in db.execute(
                select(Device.machine_id, Device.user_id).where(
                    Device.machine_id.in_(machines), Device.is_new_unreviewed.is_(True)
                )
            ).all()
        } if machines else set()

    now = datetime.now()
    return {
        str(s.get("session_key")): {
            "user_stream_count": per_user.get(s.get("user_id"), 0),
            "server_stream_count": len(sessions),
            "geo": places.get(s.get("ip_address")),
            "is_hosting": bool((places.get(s.get("ip_address")) or {}).get("is_hosting")),
            "paused_minutes": _paused_minutes(s),
            "open_travel_flag": _int(s.get("user_id")) in flagged,
            "device_unreviewed": (s.get("machine_id"), _int(s.get("user_id"))) in unreviewed,
            "now": now,
        }
        for s in sessions
    }


async def _add_requests(sessions: list[Session], context: dict[str, dict[str, Any]]) -> None:
    """Whether the person watching is who asked for it in Seerr.

    Only looked up when a rule uses it, since it costs a Seerr call per stream.
    """
    from app.integrations.seerr import seerr
    from app.models import MediaItem

    if not seerr.configured():
        return
    for s in sessions:
        key = _int(s.get("grandparent_rating_key")) or _int(s.get("rating_key"))
        if key is None:
            continue
        with session_scope() as db:
            item = db.get(MediaItem, key)
            if item is not None:
                db.expunge(item)
        if item is None:
            continue
        request = await seerr.request_for(item)
        viewer = {
            str(v).strip().lower()
            for v in (s.get("friendly_name"), s.get("username"))
            if v
        }
        requester = str((request or {}).get("requested_by") or "").strip().lower()
        context[str(s.get("session_key"))]["requested_by_viewer"] = (
            bool(requester) and requester in viewer if request is not None else False
        )


async def live_context() -> tuple[list[Session], dict[str, dict[str, Any]], str | None]:
    """Current sessions and their context, for the enforcer and for previews."""
    client = TautulliClient(current())
    try:
        activity = await client.call("get_activity") or {}
    except Exception as exc:  # noqa: BLE001
        return [], {}, str(exc)
    finally:
        await client.aclose()
    sessions: list[Session] = activity.get("sessions") or []
    tracker.observe(sessions)
    context = _build_context(sessions)
    counter = window_counter()
    for s in sessions:
        ctx = context[str(s.get("session_key"))]
        ctx.update(tracker.metrics(s.get("session_key")))
        ctx["window_count"] = counter
    return sessions, context, None


def window_counter():
    """Counts over the last N hours, for the "recent history" conditions.

    Built per poll and memoised, so several rules asking the same question of
    the same user cost one query.
    """
    from app.models import History, StreamEvent

    cache: dict[tuple, int | None] = {}

    def count(kind: str, session: Session, hours: float) -> int | None:
        uid = _int(session.get("user_id"))
        mid = session.get("machine_id")
        key = (kind, uid, mid, hours)
        if key in cache:
            return cache[key]
        since = int(time.time() - hours * 3600)
        since_dt = datetime.fromtimestamp(since, UTC)
        with session_scope() as db:
            if kind == "device_buffering_window":
                value = None if not mid else db.execute(
                    select(func.count()).select_from(StreamEvent).where(
                        StreamEvent.machine_id == mid, StreamEvent.started_at >= since_dt
                    )
                ).scalar_one()
            elif uid is None:
                value = None
            elif kind == "user_plays_window":
                value = db.execute(
                    select(func.count()).select_from(History).where(History.user_id == uid, History.started >= since)
                ).scalar_one()
            elif kind == "user_devices_window":
                value = db.execute(
                    select(func.count(func.distinct(History.machine_id))).where(
                        History.user_id == uid, History.started >= since
                    )
                ).scalar_one()
            elif kind == "user_addresses_window":
                value = db.execute(
                    select(func.count(func.distinct(History.ip_address))).where(
                        History.user_id == uid, History.started >= since
                    )
                ).scalar_one()
            elif kind == "user_cities_window":
                value = db.execute(
                    select(func.count(func.distinct(IpLocation.city)))
                    .join(History, History.ip_address == IpLocation.ip)
                    .where(History.user_id == uid, History.started >= since, IpLocation.city.is_not(None))
                ).scalar_one()
            elif kind == "user_buffering_window":
                value = db.execute(
                    select(func.count()).select_from(StreamEvent).where(
                        StreamEvent.user_id == uid, StreamEvent.started_at >= since_dt
                    )
                ).scalar_one()
            else:
                value = None
        cache[key] = value
        return value

    return count


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def snapshot(session: Session) -> dict[str, Any]:
    """Everything worth keeping about a live session, as log columns."""
    ip = session.get("ip_address")
    place = None
    if ip:
        with session_scope() as db:
            row = db.get(IpLocation, ip)
            if row is not None:
                place = {
                    "city": row.city,
                    "region": row.region,
                    "country": row.country,
                    "lat": row.lat,
                    "lon": row.lon,
                    "is_hosting": row.is_hosting,
                    "asn_org": row.asn_org,
                }

    return {
        "session_key": str(session.get("session_key")),
        "user_id": _int(session.get("user_id")),
        "username": session.get("friendly_name") or session.get("username"),
        "machine_id": session.get("machine_id"),
        "player": session.get("player"),
        "platform": session.get("platform"),
        "product": session.get("product"),
        "ip_address": ip,
        "full_title": session.get("full_title"),
        "media_type": session.get("media_type"),
        "rating_key": _int(session.get("rating_key")),
        "grandparent_rating_key": _int(session.get("grandparent_rating_key")),
        "grandparent_title": session.get("grandparent_title"),
        "parent_media_index": _int(session.get("parent_media_index")),
        "media_index": _int(session.get("media_index")),
        "library_name": session.get("library_name"),
        "year": _int(session.get("year")),
        "state": session.get("state"),
        "progress_percent": _int(session.get("progress_percent")),
        "view_offset": _int(session.get("view_offset")),
        "duration": _int(session.get("duration")),
        "transcode_decision": session.get("transcode_decision"),
        "video_resolution": session.get("video_full_resolution"),
        "quality_profile": session.get("quality_profile"),
        "bandwidth": _int(session.get("bandwidth")),
        "location": session.get("location"),
        **(place or {}),
    }


def _record(rule: Rule, session: Session, dry_run: bool, result: str) -> None:
    steps = rule_actions(rule)
    message = next(
        (step.get("params", {}).get("message") for step in steps if step.get("name") == "terminate"),
        None,
    )
    with session_scope() as db:
        db.add(
            EnforcementLog(
                **snapshot(session),
                rule_id=rule.id,
                rule_name=rule.name,
                action=", ".join(str(step.get("name")) for step in steps) or rule.action,
                source="rule",
                actor=f"Rule: {rule.name}",
                message=message or rule.message,
                dry_run=dry_run,
                result=result,
                acted_at=datetime.now(UTC),
            )
        )


BAN_RULE_NAME = "Banned devices"


def dry_run_locked() -> bool:
    """ENFORCE_DRY_RUN=true in the container config forces every rule to
    record only, whatever the Rules page says. A way to make certain nothing
    gets stopped, for example while testing a new install."""
    return "enforce_dry_run" in locked_keys() and bool(current().enforce_dry_run)


def record_only(rule: Rule) -> bool:
    """Whether a rule only records what it would have done."""
    if dry_run_locked():
        return True
    settings = current()
    value = settings.ban_record_only if rule.id == 0 else rule.record_only
    return bool(settings.enforce_dry_run) if value is None else bool(value)


def ban_rule() -> Rule | None:
    """The ban list as a rule, or None when nothing is banned.

    Never saved. Built fresh each sweep so it can go through exactly the same
    matching, cooldown, dry run, requirement and logging path as any rule,
    rather than a second enforcement path that could drift from the first.
    """
    with session_scope() as db:
        ids = [mid for (mid,) in db.execute(select(BannedDevice.machine_id)).all()]
    if not ids:
        return None
    settings = current()
    return Rule(
        id=0,
        name=BAN_RULE_NAME,
        enabled=True,
        action="terminate",
        message=settings.ban_message,
        conditions=json.dumps(
            {
                "type": "group",
                "op": "and",
                "items": [{"type": "condition", "field": "device", "op": "any", "value": ids}],
            }
        ),
        actions=json.dumps([{"name": "terminate", "params": {"message": settings.ban_message}}]),
    )


async def run_once() -> dict[str, Any]:
    """Evaluate every enabled rule against current activity."""
    settings = current()
    if not is_configured():
        return {"checked": 0, "matched": 0, "acted": 0}

    # Read activity first, whatever happens next: the tracker has to see every
    # poll to time buffering and record it, even with no rules or rules off.
    sessions, context, error = await live_context()
    if error:
        log.warning("enforcer could not read activity: %s", error)
        return {"checked": 0, "matched": 0, "acted": 0, "error": error}
    if not settings.enforce_enabled:
        return {"checked": len(sessions), "matched": 0, "acted": 0}

    with session_scope() as db:
        rules = list(db.execute(select(Rule).where(Rule.enabled.is_(True)).order_by(Rule.id)).scalars())
        for rule in rules:
            db.expunge(rule)
    # First, so a ban wins over any other rule that would also match.
    banned = ban_rule()
    if banned is not None:
        rules.insert(0, banned)
    if not rules:
        return {"checked": len(sessions), "matched": 0, "acted": 0}

    # Refuse rules that lean on something missing. Evaluating them with that
    # condition dropped would make them match more than was written.
    usable = []
    refused = []
    for rule in rules:
        missing = unmet_requirements(rule_tree(rule))
        if missing:
            refused.append({"rule": rule.name, "requires": missing})
            log.warning("rule %r skipped: requires %s", rule.name, ", ".join(missing))
        else:
            usable.append(rule)

    if any("requested_by_viewer" in conditions.fields_used(rule_tree(r)) for r in usable):
        await _add_requests(sessions, context)

    now = time.monotonic()

    matched = acted = 0
    for session in sessions:
        key = str(session.get("session_key"))
        for rule in usable:
            if not matches(rule, session, context.get(key, {})):
                continue
            matched += 1

            dry_run = record_only(rule)
            if (rule.id, key, dry_run) in _done:
                break

            cooldown_key = (rule.id, key)
            last = _recent.get(cooldown_key)
            if last is not None and now - last < settings.enforce_cooldown_seconds:
                break
            _recent[cooldown_key] = now
            steps = rule_actions(rule)
            specs = [(step, registry.get(str(step.get("name")))) for step in steps]
            unknown = [str(step.get("name")) for step, spec in specs if spec is None]
            if unknown or not specs:
                _record(rule, session, dry_run, f"unknown action {', '.join(unknown) or '(none)'}")
                _done.add((rule.id, key, dry_run))
                break

            missing = sorted({m for _, spec in specs for m in registry.unmet(spec)})
            if missing:
                # Refused, not silently skipped, and the log says why.
                _record(rule, session, dry_run, f"refused: requires {', '.join(missing)}")
                _done.add((rule.id, key, dry_run))
                break

            if dry_run:
                _record(rule, session, True, "would " + ", ".join(spec.name for _, spec in specs))
                _done.add((rule.id, key, True))
                break

            results = []
            for step, spec in specs:
                try:
                    results.append(await spec.execute(session, step.get("params") or {}))
                    acted += 1
                except Exception as exc:  # noqa: BLE001 - one failure mustn't stop the sweep
                    results.append(f"{spec.name} failed: {exc}")
                    log.warning("action %s failed: %s", spec.name, exc)
            _record(rule, session, False, "; ".join(results))
            if not any(spec.name == "terminate" for _, spec in specs):
                _done.add((rule.id, key, False))
            break  # first matching rule wins; don't double-act on one session

    # Keep the cooldown map from growing forever.
    cutoff = now - 3600
    for k, seen in list(_recent.items()):
        if seen < cutoff:
            del _recent[k]
    live = {str(s.get("session_key")) for s in sessions}
    _done.difference_update({d for d in _done if d[1] not in live})

    return {
        "checked": len(sessions),
        "matched": matched,
        "acted": acted,
        "dry_run_locked": dry_run_locked(),
        "refused": refused,
    }

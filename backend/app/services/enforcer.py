"""Rule evaluation against live sessions.

Plex has no API to ban a shared user's device, so blocking is behavioural:
poll get_activity, match the session, run the action. This is what Tautulli's
kill-stream notification agents do, with a rule table and an audit trail.

Ships in dry run. Turning that off is a deliberate act after reading the log.
"""

from __future__ import annotations

import ipaddress
import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.actions import registry
from app.db import session_scope
from app.models import EnforcementLog, IpLocation, Rule
from app.settings_store import current, is_configured
from app.tautulli.client import TautulliClient

log = logging.getLogger(__name__)

Session = dict[str, Any]

# One session shouldn't spam the log while a stubborn client retries.
_recent: dict[tuple[int, str], float] = {}


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


def matches(rule: Rule, session: Session, context: dict[str, Any]) -> bool:
    """Every matcher that is set must hold. A rule with none set matches
    nothing. An empty rule silently killing every stream would be the worst
    possible default."""
    checks: list[bool] = []

    def require(condition: bool) -> None:
        checks.append(condition)

    if rule.match_user_id is not None:
        require(_equal(rule.match_user_id, session.get("user_id")))
    if rule.match_machine_id:
        require(_equal(rule.match_machine_id, session.get("machine_id")))
    if rule.match_player:
        require(_equal(rule.match_player, session.get("player")))
    if rule.match_platform:
        require(_equal(rule.match_platform, session.get("platform")))
    if rule.match_product:
        require(_equal(rule.match_product, session.get("product")))
    if rule.match_ip_cidr:
        require(_ip_in_cidr(session.get("ip_address"), rule.match_ip_cidr))
    if rule.match_transcode_decision:
        require(_equal(rule.match_transcode_decision, session.get("transcode_decision")))
    if rule.match_video_resolution:
        require(
            _equal(rule.match_video_resolution, session.get("video_full_resolution"))
            or _equal(rule.match_video_resolution, session.get("video_resolution"))
        )
    if rule.match_location:
        require(_equal(rule.match_location, session.get("location")))
    if rule.match_is_hosting is not None:
        require(bool(context.get("is_hosting")) is bool(rule.match_is_hosting))
    if rule.match_concurrent_streams_gt is not None:
        require(context.get("user_stream_count", 0) > rule.match_concurrent_streams_gt)
    if rule.match_paused_minutes_gt is not None:
        paused = context.get("paused_minutes")
        require(paused is not None and paused > rule.match_paused_minutes_gt)

    return bool(checks) and all(checks)


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
    per_user: dict[Any, int] = {}
    for s in sessions:
        per_user[s.get("user_id")] = per_user.get(s.get("user_id"), 0) + 1

    hosting = _hosting_ips({s["ip_address"] for s in sessions if s.get("ip_address")})

    return {
        str(s.get("session_key")): {
            "user_stream_count": per_user.get(s.get("user_id"), 0),
            "is_hosting": s.get("ip_address") in hosting,
            "paused_minutes": _paused_minutes(s),
        }
        for s in sessions
    }


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
    with session_scope() as db:
        db.add(
            EnforcementLog(
                **snapshot(session),
                rule_id=rule.id,
                rule_name=rule.name,
                action=rule.action,
                source="rule",
                actor=f"Rule: {rule.name}",
                message=rule.message,
                dry_run=dry_run,
                result=result,
                acted_at=datetime.now(UTC),
            )
        )


async def run_once() -> dict[str, Any]:
    """Evaluate every enabled rule against current activity."""
    settings = current()
    if not (is_configured() and settings.enforce_enabled):
        return {"checked": 0, "matched": 0, "acted": 0}

    with session_scope() as db:
        rules = list(db.execute(select(Rule).where(Rule.enabled.is_(True))).scalars())
    if not rules:
        return {"checked": 0, "matched": 0, "acted": 0}

    client = TautulliClient(settings)
    try:
        activity = await client.call("get_activity") or {}
    except Exception as exc:  # noqa: BLE001
        log.warning("enforcer could not read activity: %s", exc)
        return {"checked": 0, "matched": 0, "acted": 0, "error": str(exc)}
    finally:
        await client.aclose()

    sessions: list[Session] = activity.get("sessions") or []
    context = _build_context(sessions)
    dry_run = settings.enforce_dry_run
    now = time.monotonic()

    matched = acted = 0
    for session in sessions:
        key = str(session.get("session_key"))
        for rule in rules:
            if not matches(rule, session, context.get(key, {})):
                continue
            matched += 1

            cooldown_key = (rule.id, key)
            last = _recent.get(cooldown_key)
            if last is not None and now - last < settings.enforce_cooldown_seconds:
                break
            _recent[cooldown_key] = now

            action = registry.get(rule.action)
            if action is None:
                _record(rule, session, dry_run, f"unknown action {rule.action!r}")
                break

            missing = registry.unmet(action)
            if missing:
                # Refused, not silently skipped, and the log says why.
                _record(rule, session, dry_run, f"refused: requires {', '.join(missing)}")
                break

            if dry_run:
                _record(rule, session, True, f"would {action.name}")
                break

            try:
                result = await action.execute(session, {"message": rule.message})
                acted += 1
            except Exception as exc:  # noqa: BLE001 - one failure mustn't stop the sweep
                result = f"failed: {exc}"
                log.warning("action %s failed: %s", action.name, exc)
            _record(rule, session, False, result)
            break  # first matching rule wins; don't double-act on one session

    # Keep the cooldown map from growing forever.
    cutoff = now - 3600
    for k, seen in list(_recent.items()):
        if seen < cutoff:
            del _recent[k]

    return {"checked": len(sessions), "matched": matched, "acted": acted, "dry_run": dry_run}

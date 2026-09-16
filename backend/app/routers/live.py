"""Capabilities, live activity, rules, enforcement log, and the dashboard."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app import audit
from app.actions import registry
from app.integrations import arr, kuma, notify, seerr, tmdb
from app.integrations.base import Health
from app.auth.deps import AdminUser
from app.db import SessionLocal, session_scope
from app.filters import Filters
from app.models import (
    Device,
    EnforcementLog,
    History,
    IpLocation,
    MediaItem,
    Rule,
    TravelFlag,
    User,
)
from app.services import capabilities, enforcer
from app.settings_store import current, is_configured, trial
from app.tautulli.client import TautulliClient

router = APIRouter(prefix="/api")


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


Db = Annotated[Session, Depends(get_session)]
log = logging.getLogger(__name__)

Filt = Annotated[Filters, Depends()]

# What the UI needs from a live session. get_activity returns ~250 fields per
# stream; sending them all would make the 5-second poll heavier than the map.
SESSION_FIELDS = (
    "session_key session_id user_id username friendly_name user_thumb "
    "machine_id player platform product device ip_address ip_address_public "
    "location secure relayed state progress_percent view_offset duration "
    "media_type full_title title grandparent_title parent_title year thumb "
    "art rating_key section_id library_name transcode_decision "
    "video_decision audio_decision video_full_resolution stream_video_full_resolution "
    "quality_profile bandwidth container transcode_speed throttled "
    "summary content_rating grandparent_rating_key originally_available_at "
    "video_codec stream_video_codec audio_codec stream_audio_codec audio_channel_layout "
    "stream_container stream_bitrate subtitle_decision"
).split()


def _trim(session: dict[str, Any]) -> dict[str, Any]:
    return {key: session.get(key) for key in SESSION_FIELDS}


# ---- capabilities ----------------------------------------------------------

@router.get("/capabilities")
async def get_capabilities(refresh: bool = False) -> dict:
    if refresh or capabilities.is_stale():
        await capabilities.refresh()
    return capabilities.as_map()


@router.get("/actions")
def list_actions() -> list[dict]:
    """The action registry, with what each one needs. The rule editor builds
    its form from `param_schema` and greys out anything unavailable."""
    return [
        {
            "name": a.name,
            "label": a.label,
            "description": a.description,
            "requires": list(a.requires),
            "unmet": registry.unmet(a),
            "param_schema": a.param_schema,
        }
        for a in registry.all_actions()
    ]


# ---- live activity ---------------------------------------------------------

@router.get("/activity")
async def activity(db: Db) -> dict:
    if not is_configured():
        return {"stream_count": 0, "sessions": [], "error": "Tautulli is not configured"}

    client = TautulliClient(current())
    try:
        data = await client.call("get_activity") or {}
    except Exception as exc:  # noqa: BLE001
        return {"stream_count": 0, "sessions": [], "error": str(exc)}
    finally:
        await client.aclose()

    sessions = [_trim(s) for s in data.get("sessions") or []]

    # Annotate with what we know locally that Tautulli doesn't: whether the
    # origin is a hosting/VPN address, and where it is on the map.
    ips = {s["ip_address"] for s in sessions if s.get("ip_address")}
    locations = {
        row.ip: row
        for row in db.execute(select(IpLocation).where(IpLocation.ip.in_(ips))).scalars()
    }
    for s in sessions:
        place = locations.get(s.get("ip_address"))
        s["geo"] = (
            None
            if place is None
            else {
                "city": place.city,
                "region": place.region,
                "country": place.country,
                "lat": place.lat,
                "lon": place.lon,
                "is_hosting": place.is_hosting,
                "asn_org": place.asn_org,
            }
        )

    return {
        "stream_count": data.get("stream_count"),
        "total_bandwidth": data.get("total_bandwidth"),
        "wan_bandwidth": data.get("wan_bandwidth"),
        "transcode_count": data.get("stream_count_transcode"),
        "sessions": sessions,
    }


@router.post("/activity/{session_key}/terminate")
async def terminate(
    session_key: str, admin: AdminUser, message: str = Body("", embed=True)
) -> dict:
    """Stop one stream. Refused without Plex Pass, whatever the UI showed."""
    action = registry.get("terminate")
    assert action is not None
    missing = registry.unmet(action)
    if missing:
        raise HTTPException(409, f"Unavailable: requires {', '.join(missing)}")

    # Read the stream first. Once it is stopped there is nothing left to ask
    # about, and the log would only know a session key.
    session: dict[str, Any] = {"session_key": session_key}
    client = TautulliClient(current())
    try:
        activity = await client.call("get_activity") or {}
        for live in activity.get("sessions") or []:
            if str(live.get("session_key")) == str(session_key):
                session = live
                break
    except Exception:  # noqa: BLE001 - a thinner log beats refusing to stop it
        log.debug("could not snapshot session %s before stopping it", session_key)
    finally:
        await client.aclose()

    try:
        result = await action.execute({"session_key": session_key}, {"message": message})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Plex refused: {exc}") from exc

    with session_scope() as db:
        db.add(
            EnforcementLog(
                **enforcer.snapshot(session),
                rule_name="(manual)",
                action="terminate",
                source="manual",
                actor=admin.username,
                message=message or None,
                dry_run=False,
                result=result,
                acted_at=datetime.now(UTC),
            )
        )
    return {"result": result}


# ---- rules -----------------------------------------------------------------

EDITABLE = {c.name for c in Rule.__table__.columns} - {"id", "created_at"}


def _rule_dict(rule: Rule) -> dict:
    return {c.name: getattr(rule, c.name) for c in Rule.__table__.columns}


@router.get("/rules")
def list_rules(db: Db) -> list[dict]:
    stmt = select(Rule).order_by(Rule.id)
    return [_rule_dict(r) for r in db.execute(stmt).scalars()]


@router.post("/rules")
def create_rule(admin: AdminUser, values: dict[str, Any] = Body(...)) -> dict:
    payload = _validate_rule(values)
    with session_scope() as db:
        rule = Rule(**payload, created_at=datetime.now(UTC))
        db.add(rule)
        db.flush()
        saved = _rule_dict(rule)
    audit.record(
        admin, "rule.create", f"Created rule {saved['name']!r}",
        target=str(saved["id"]), detail={"after": saved},
    )
    return saved


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, admin: AdminUser, values: dict[str, Any] = Body(...)) -> dict:
    payload = _validate_rule(values, partial=True)
    with session_scope() as db:
        rule = db.get(Rule, rule_id)
        if rule is None:
            raise HTTPException(404, "No such rule")
        before = _rule_dict(rule)
        for key, value in payload.items():
            setattr(rule, key, value)
        db.flush()
        saved = _rule_dict(rule)

    changed = {k: {"before": before.get(k), "after": v} for k, v in saved.items() if before.get(k) != v}
    if set(changed) == {"enabled"}:
        summary = f"{'Enabled' if saved['enabled'] else 'Disabled'} rule {saved['name']!r}"
    else:
        summary = f"Edited rule {saved['name']!r}: {', '.join(sorted(changed)) or 'no changes'}"
    audit.record(admin, "rule.update", summary, target=str(rule_id), detail=changed)
    return saved


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, admin: AdminUser) -> dict:
    with session_scope() as db:
        rule = db.get(Rule, rule_id)
        if rule is None:
            raise HTTPException(404, "No such rule")
        before = _rule_dict(rule)
        db.delete(rule)
    audit.record(
        admin, "rule.delete", f"Deleted rule {before['name']!r}",
        target=str(rule_id), detail={"before": before},
    )
    return {"deleted": rule_id}


def _validate_rule(values: dict[str, Any], partial: bool = False) -> dict[str, Any]:
    unknown = set(values) - EDITABLE
    if unknown:
        raise HTTPException(400, f"Unknown fields: {', '.join(sorted(unknown))}")

    payload = {k: v for k, v in values.items() if k in EDITABLE}
    if not partial and not payload.get("name"):
        raise HTTPException(400, "A rule needs a name")

    action_name = payload.get("action", "terminate")
    if registry.get(action_name) is None:
        known = ", ".join(a.name for a in registry.all_actions())
        raise HTTPException(400, f"Unknown action {action_name!r}. Known: {known}")

    # A rule with no matchers would match every stream. Refusing here is the
    # difference between a blocklist and an outage.
    if not partial and not any(k.startswith("match_") and v not in (None, "") for k, v in payload.items()):
        raise HTTPException(400, "A rule needs at least one condition, or it would match everything")

    return payload


@router.get("/enforcement-log")
def enforcement_log(db: Db, limit: int = 100) -> list[dict]:
    stmt = select(EnforcementLog).order_by(desc(EnforcementLog.acted_at)).limit(limit)
    return [
        {c.name: getattr(row, c.name) for c in EnforcementLog.__table__.columns}
        for row in db.execute(stmt).scalars()
    ]


@router.get("/log")
def combined_log(
    db: Db,
    _: AdminUser,
    kind: str = "all",
    limit: int = 200,
) -> list[dict]:
    """Stream actions and admin changes on one timeline.

    Two tables because they record different things: a stream action keeps a
    snapshot of the stream, a change keeps what it was before. The page wants
    them in one list, so they are merged here, newest first.
    """
    from app.models import AuditLog

    limit = max(1, min(limit, 1000))
    out: list[dict] = []
    if kind in ("all", "streams"):
        rows = db.execute(
            select(EnforcementLog).order_by(desc(EnforcementLog.acted_at)).limit(limit)
        ).scalars()
        out += [
            {
                "kind": "stream",
                "at": row.acted_at,
                **{c.name: getattr(row, c.name) for c in EnforcementLog.__table__.columns},
            }
            for row in rows
        ]
    if kind in ("all", "changes"):
        rows = db.execute(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)).scalars()
        out += [
            {
                "kind": "change",
                "at": row.created_at,
                **{c.name: getattr(row, c.name) for c in AuditLog.__table__.columns},
            }
            for row in rows
        ]
    out.sort(key=lambda r: r["at"] or datetime.min, reverse=True)
    return out[:limit]


@router.post("/rules/run")
async def run_rules_now(admin: AdminUser) -> dict:
    """Evaluate rules immediately instead of waiting for the next sweep."""
    result = await enforcer.run_once()
    audit.record(
        admin, "rule.run",
        f"Ran rules now: {result.get('matched', 0)} matched, {result.get('acted', 0)} acted",
        detail=result,
    )
    return result


# ---- integrations ----------------------------------------------------------

INTEGRATIONS = {
    i.name: i
    for i in (
        arr.radarr,
        arr.sonarr,
        seerr.seerr,
        tmdb.tmdb,
        notify.apprise_notifier,
        notify.webhook_notifier,
        kuma.uptime_kuma,
    )
}


async def _tautulli_health() -> Health:
    settings = current()
    if not (settings.tautulli_url and settings.tautulli_api_key):
        return Health(False, "Needs a URL and an API key")
    client = TautulliClient(settings)
    try:
        info = await client.call("get_server_info") or {}
    except Exception as exc:  # noqa: BLE001 - the failure is the answer
        return Health(False, str(exc))
    finally:
        await client.aclose()
    name = info.get("pms_name")
    return Health(True, f"Connected to {name}" if name else "Connected", info.get("pms_version"))


async def _plex_health() -> Health:
    import asyncio

    from app.plex import sharing

    if not sharing.configured():
        return Health(False, "Needs a Plex token")
    status = await asyncio.to_thread(sharing.status)
    return Health(bool(status.get("ok")), str(status.get("detail") or ""))


async def _maxmind_health() -> Health:
    import asyncio

    from app.geo.lookup import ensure_databases

    settings = current()
    if not (settings.maxmind_account_id and settings.maxmind_license_key):
        return Health(False, "Needs an account ID and a license key")
    try:
        await asyncio.to_thread(
            ensure_databases,
            settings.geoip_dir,
            settings.maxmind_account_id,
            settings.maxmind_license_key,
            max_age_days=0,
        )
    except Exception as exc:  # noqa: BLE001
        return Health(False, str(exc))
    if not (settings.geoip_dir / "city.mmdb").exists():
        return Health(False, "Download failed. A new key can take a few minutes to work.")
    return Health(True, "Databases downloaded")


# Not integrations in the optional sense, but they are tested the same way.
CORE_TESTS = {
    "tautulli": _tautulli_health,
    "plex": _plex_health,
    "maxmind": _maxmind_health,
}


@router.get("/integrations")
async def list_integrations() -> list[dict]:
    out = []
    for integration in INTEGRATIONS.values():
        health = await integration.health() if integration.configured() else None
        out.append(
            {
                "name": integration.name,
                "label": integration.label,
                "configured": integration.configured(),
                "ok": bool(health and health.ok),
                "detail": health.detail if health else "Not set up",
                "version": health.version if health else None,
            }
        )
    return out


@router.post("/integrations/{name}/test")
async def test_integration(
    name: str,
    _: AdminUser,
    values: dict[str, Any] = Body(default_factory=dict, embed=True),
) -> dict:
    """Check a connection, using what is on the page rather than what is saved.

    Anything not sent falls back to the saved value, which is how a masked key
    that was never retyped still gets used.
    """
    check = CORE_TESTS.get(name)
    if check is None:
        integration = INTEGRATIONS.get(name)
        if integration is None:
            raise HTTPException(404, f"No integration called {name!r}")
        check = integration.health

    try:
        with trial(values):
            health = await check()
    except ValueError as exc:  # a value on the page that does not parse
        raise HTTPException(400, str(exc)) from exc
    return {"ok": health.ok, "detail": health.detail, "version": health.version}


# ---- impossible travel -----------------------------------------------------

@router.get("/travel-flags")
def travel_flags(db: Db, status: str | None = None, limit: int = 100) -> list[dict]:
    stmt = select(TravelFlag, func.coalesce(User.friendly_name, User.username).label("name")).join(
        User, User.user_id == TravelFlag.user_id, isouter=True
    )
    if status:
        stmt = stmt.where(TravelFlag.status == status)
    stmt = stmt.order_by(desc(TravelFlag.to_started)).limit(limit)

    return [
        {
            **{c.name: getattr(flag, c.name) for c in TravelFlag.__table__.columns},
            "user_name": name or str(flag.user_id),
        }
        for flag, name in db.execute(stmt).all()
    ]


@router.patch("/travel-flags/{flag_id}")
def review_flag(flag_id: int, admin: AdminUser, status: str = Body(..., embed=True)) -> dict:
    if status not in {"new", "reviewed", "ignored"}:
        raise HTTPException(400, "Status must be new, reviewed or ignored")
    with session_scope() as db:
        flag = db.get(TravelFlag, flag_id)
        if flag is None:
            raise HTTPException(404, "No such flag")
        before = flag.status
        flag.status = status
        user = db.get(User, flag.user_id)
        who = (user.friendly_name or user.username) if user else str(flag.user_id)
    verb = {"reviewed": "Reviewed", "ignored": "Ignored", "new": "Reopened"}[status]
    audit.record(
        admin, "travel.review", f"{verb} a sharing signal for {who}",
        target=str(flag_id), detail={"before": before, "after": status, "user_id": flag.user_id},
    )
    return {"id": flag_id, "status": status}


# ---- dashboard -------------------------------------------------------------

@router.get("/dashboard")
async def dashboard(db: Db, filters: Filt) -> dict:
    """Everything the landing screen needs, composed in one call.

    Deliberately one endpoint rather than a widget-per-request: the layout is
    still being worked out, and a dashboard that fans out to eight endpoints
    gets slow and hard to change. New sources get added to this payload.
    """
    # Everything counted from history respects the filters, so the dashboard
    # answers the same question the map and tables are answering. Live
    # activity, capabilities and the device backlog deliberately do not: they
    # describe right now, not a slice of the past.
    def filtered(*columns):
        stmt = select(*columns).select_from(History)
        if filters.needs_location_join:
            stmt = stmt.join(IpLocation, IpLocation.ip == History.ip_address)
        conditions = filters.conditions()
        return stmt.where(*conditions) if conditions else stmt

    totals = db.execute(
        filtered(
            func.count(),
            func.count(func.distinct(History.user_id)),
            func.count(func.distinct(History.machine_id)),
            func.count(func.distinct(History.rating_key)),
            func.count(func.distinct(History.ip_address)),
        )
    ).one()

    # Always joins, so a location filter can be applied here too. Kept
    # separate from the totals above because those must not join and lose rows
    # for addresses that were never geocoded.
    hosting_ips = db.execute(
        select(func.count(func.distinct(History.ip_address)))
        .select_from(History)
        .join(IpLocation, IpLocation.ip == History.ip_address)
        .where(*filters.conditions(), IpLocation.is_hosting.is_(True))
    ).scalar_one()

    day = func.date(History.started, "unixepoch", "localtime").label("day")
    recent = db.execute(
        filtered(day, func.count().label("plays"))
        .group_by(day)
        .order_by(desc(day))
        .limit(30)
    ).all()

    top_users = db.execute(
        filtered(
            History.user_id,
            func.coalesce(User.friendly_name, User.username).label("name"),
            func.count().label("plays"),
        )
        .join(User, User.user_id == History.user_id, isouter=True)
        .group_by(History.user_id)
        .order_by(desc(func.count()))
        .limit(5)
    ).all()

    new_devices = db.execute(
        select(func.count()).select_from(Device).where(Device.is_new_unreviewed.is_(True))
    ).scalar_one()

    open_flags = db.execute(
        select(func.count()).select_from(TravelFlag).where(TravelFlag.status == "new")
    ).scalar_one()

    last_enforcement = db.execute(
        select(EnforcementLog).order_by(desc(EnforcementLog.acted_at)).limit(5)
    ).scalars()

    live = await activity(db)

    return {
        "capabilities": capabilities.as_map(),
        "settings": {
            "enforce_enabled": current().enforce_enabled,
            "enforce_dry_run": current().enforce_dry_run,
        },
        "totals": {
            "plays": totals[0],
            "users": totals[1],
            "devices": totals[2],
            "media_items": totals[3],
            "ip_locations": totals[4],
            "hosting_ips": hosting_ips,
            "new_devices": new_devices,
            "travel_flags": open_flags,
        },
        "filtered": bool(filters.conditions()),
        "live": {
            "stream_count": live.get("stream_count") or 0,
            "transcode_count": live.get("transcode_count") or 0,
            "total_bandwidth": live.get("total_bandwidth"),
            "sessions": live.get("sessions", []),
            "error": live.get("error"),
        },
        "plays_by_day": [{"day": r.day, "plays": r.plays} for r in reversed(recent)],
        "top_users": [
            {"user_id": r.user_id, "name": r.name or str(r.user_id), "plays": r.plays}
            for r in top_users
        ],
        "recent_enforcement": [
            {c.name: getattr(e, c.name) for c in EnforcementLog.__table__.columns}
            for e in last_enforcement
        ],
        # Filled in when integrations land; shape fixed now so the dashboard
        # doesn't need reworking to show them.
        "integrations": {},
    }

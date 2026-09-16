"""Capabilities, live activity, rules, enforcement log, and the dashboard."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.actions import registry
from app.integrations import arr, notify
from app.auth.deps import AdminUser
from app.db import SessionLocal, session_scope
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

# What the UI needs from a live session. get_activity returns ~250 fields per
# stream; sending them all would make the 5-second poll heavier than the map.
SESSION_FIELDS = (
    "session_key session_id user_id username friendly_name user_thumb "
    "machine_id player platform product device ip_address ip_address_public "
    "location secure relayed state progress_percent view_offset duration "
    "media_type full_title title grandparent_title parent_title year thumb "
    "art rating_key section_id library_name transcode_decision "
    "video_decision audio_decision video_full_resolution stream_video_full_resolution "
    "quality_profile bandwidth container transcode_speed throttled"
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
    session_key: str, _: AdminUser, message: str = Body("", embed=True)
) -> dict:
    """Stop one stream. Refused without Plex Pass, whatever the UI showed."""
    action = registry.get("terminate")
    assert action is not None
    missing = registry.unmet(action)
    if missing:
        raise HTTPException(409, f"Unavailable: requires {', '.join(missing)}")

    try:
        result = await action.execute({"session_key": session_key}, {"message": message})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Plex refused: {exc}") from exc

    with session_scope() as db:
        db.add(
            EnforcementLog(
                rule_name="(manual)",
                action="terminate",
                session_key=session_key,
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
def create_rule(_: AdminUser, values: dict[str, Any] = Body(...)) -> dict:
    payload = _validate_rule(values)
    with session_scope() as db:
        rule = Rule(**payload, created_at=datetime.now(UTC))
        db.add(rule)
        db.flush()
        return _rule_dict(rule)


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, _: AdminUser, values: dict[str, Any] = Body(...)) -> dict:
    payload = _validate_rule(values, partial=True)
    with session_scope() as db:
        rule = db.get(Rule, rule_id)
        if rule is None:
            raise HTTPException(404, "No such rule")
        for key, value in payload.items():
            setattr(rule, key, value)
        db.flush()
        return _rule_dict(rule)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, _: AdminUser) -> dict:
    with session_scope() as db:
        rule = db.get(Rule, rule_id)
        if rule is None:
            raise HTTPException(404, "No such rule")
        db.delete(rule)
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


@router.post("/rules/run")
async def run_rules_now(_: AdminUser) -> dict:
    """Evaluate rules immediately instead of waiting for the next sweep."""
    return await enforcer.run_once()


# ---- integrations ----------------------------------------------------------

INTEGRATIONS = {
    i.name: i
    for i in (arr.radarr, arr.sonarr, notify.apprise_notifier, notify.webhook_notifier)
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
async def test_integration(name: str, _: AdminUser) -> dict:
    integration = INTEGRATIONS.get(name)
    if integration is None:
        raise HTTPException(404, f"No integration called {name!r}")
    health = await integration.health()
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
def review_flag(flag_id: int, _: AdminUser, status: str = Body(..., embed=True)) -> dict:
    if status not in {"new", "reviewed", "ignored"}:
        raise HTTPException(400, "Status must be new, reviewed or ignored")
    with session_scope() as db:
        flag = db.get(TravelFlag, flag_id)
        if flag is None:
            raise HTTPException(404, "No such flag")
        flag.status = status
    return {"id": flag_id, "status": status}


# ---- dashboard -------------------------------------------------------------

@router.get("/dashboard")
async def dashboard(db: Db) -> dict:
    """Everything the landing screen needs, composed in one call.

    Deliberately one endpoint rather than a widget-per-request: the layout is
    still being worked out, and a dashboard that fans out to eight endpoints
    gets slow and hard to change. New sources get added to this payload.
    """
    totals = db.execute(
        select(
            select(func.count()).select_from(History).scalar_subquery(),
            select(func.count()).select_from(User).scalar_subquery(),
            select(func.count()).select_from(Device).scalar_subquery(),
            select(func.count()).select_from(MediaItem).where(
                MediaItem.title.is_not(None)
            ).scalar_subquery(),
            select(func.count()).select_from(IpLocation).scalar_subquery(),
            select(func.count()).select_from(IpLocation).where(
                IpLocation.is_hosting.is_(True)
            ).scalar_subquery(),
        )
    ).one()

    day = func.date(History.started, "unixepoch", "localtime").label("day")
    recent = db.execute(
        select(day, func.count().label("plays")).group_by(day).order_by(desc(day)).limit(30)
    ).all()

    top_users = db.execute(
        select(
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
            "hosting_ips": totals[5],
            "new_devices": new_devices,
            "travel_flags": open_flags,
        },
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
            {
                "rule_name": e.rule_name,
                "action": e.action,
                "username": e.username,
                "player": e.player,
                "full_title": e.full_title,
                "dry_run": e.dry_run,
                "result": e.result,
                "acted_at": e.acted_at,
            }
            for e in last_enforcement
        ],
        # Filled in when integrations land; shape fixed now so the dashboard
        # doesn't need reworking to show them.
        "integrations": {},
    }

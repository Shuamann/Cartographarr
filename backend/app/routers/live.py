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
from app.plays import plays
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

from app import privacy
from app.privacy import ScopedFilt, ViewerScope
from app.redact import redact

Filt = ScopedFilt

# What the UI needs from a live session. get_activity returns ~250 fields per
# stream; sending them all would make the 5-second poll heavier than the map.
SESSION_FIELDS = (
    "session_key session_id user_id username friendly_name user_thumb "
    "machine_id player platform product device ip_address ip_address_public "
    "location secure relayed state progress_percent view_offset duration "
    "media_type full_title title grandparent_title parent_title media_index parent_media_index year thumb "
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
def list_actions(_: AdminUser) -> list[dict]:
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
async def activity_endpoint(db: Db, scope: ViewerScope) -> dict:
    return await activity(db, scope)


async def activity(db: Session, scope: "privacy.Scope | None" = None) -> dict:
    if not is_configured():
        return {"stream_count": 0, "sessions": [], "error": "Tautulli is not configured"}

    client = TautulliClient(current())
    try:
        data = await client.call("get_activity") or {}
    except Exception as exc:  # noqa: BLE001
        return {"stream_count": 0, "sessions": [], "error": redact(exc)}
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

    if scope is not None:
        if scope.own_only:
            sessions = [x for x in sessions if scope.is_self(x.get("user_id"))]
        else:
            sessions = [privacy.scrub_session(scope, x) for x in sessions]

    return {
        "stream_count": data.get("stream_count") if scope is None or not scope.own_only else len(sessions),
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
        raise HTTPException(502, f"Plex refused: {redact(exc)}") from exc

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
    """A rule as the UI edits it: always a condition tree and an action list,
    whether it was saved that way or with the older flat columns."""
    import json

    out = {c.name: getattr(rule, c.name) for c in Rule.__table__.columns}
    out["conditions"] = enforcer.rule_tree(rule)
    out["actions"] = enforcer.rule_actions(rule)
    out["unmet"] = enforcer.unmet_requirements(out["conditions"])
    out["record_only_effective"] = enforcer.record_only(rule)
    return out


@router.get("/rules")
def list_rules(_: AdminUser, db: Db) -> list[dict]:
    # Admin only: conditions name devices, addresses and people.
    stmt = select(Rule).order_by(Rule.id)
    return [_rule_dict(r) for r in db.execute(stmt).scalars()]


@router.post("/rules")
def create_rule(admin: AdminUser, values: dict[str, Any] = Body(...)) -> dict:
    payload = _validate_rule(values)
    # A new rule records only until someone decides it should act, the same
    # caution the whole app used to apply with its single dry run switch.
    payload.setdefault("record_only", True)
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

    # Stored fields only. The rule dict also carries values worked out on read
    # (the effective record only state, unmet requirements), which are not edits.
    columns = {c.name for c in Rule.__table__.columns}
    changed = {
        k: {"before": before.get(k), "after": v}
        for k, v in saved.items()
        if k in columns and before.get(k) != v
    }
    if set(changed) == {"enabled"}:
        summary = f"{'Enabled' if saved['enabled'] else 'Disabled'} rule {saved['name']!r}"
    elif set(changed) == {"record_only"}:
        summary = (
            f"Set rule {saved['name']!r} to record only"
            if saved["record_only"]
            else f"Set rule {saved['name']!r} to act"
        )
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
    import json

    from app.services import conditions as cond

    unknown = set(values) - EDITABLE
    if unknown:
        raise HTTPException(400, f"Unknown fields: {', '.join(sorted(unknown))}")

    payload = {k: v for k, v in values.items() if k in EDITABLE and k not in ("conditions", "actions")}

    if not partial and not str(values.get("name") or "").strip():
        raise HTTPException(400, "Give the rule a name")

    if "action" in payload and "actions" not in values and registry.get(str(payload["action"])) is None:
        known = ", ".join(a.name for a in registry.all_actions())
        raise HTTPException(400, f"Unknown action {payload['action']!r}. Known: {known}")

    if "conditions" in values:
        tree = values["conditions"]
        if isinstance(tree, str):
            try:
                tree = json.loads(tree)
            except ValueError as exc:
                raise HTTPException(400, "Conditions are not readable") from exc
        try:
            tree = cond.validate(tree)
        except ValueError as exc:
            raise HTTPException(400, redact(exc)) from exc
        if not cond.count(tree):
            raise HTTPException(400, "Add at least one condition. An empty rule would match every stream.")
        payload["conditions"] = json.dumps(tree)
        # The tree replaces the flat columns, so none are left to disagree with it.
        for column in [c for c in EDITABLE if c.startswith("match_")]:
            payload[column] = None
    elif not partial and not any(values.get(c) not in (None, "") for c in EDITABLE if c.startswith("match_")):
        raise HTTPException(400, "Add at least one condition. An empty rule would match every stream.")

    if "actions" in values:
        steps = values["actions"]
        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except ValueError as exc:
                raise HTTPException(400, "Actions are not readable") from exc
        if not isinstance(steps, list) or not steps:
            raise HTTPException(400, "Choose at least one action")
        clean = []
        for step in steps:
            name = str((step or {}).get("name") or "")
            if registry.get(name) is None:
                raise HTTPException(400, f"Unknown action {name!r}")
            params = (step or {}).get("params") or {}
            if not isinstance(params, dict):
                raise HTTPException(400, f"{name}: settings are not readable")
            clean.append({"name": name, "params": {k: v for k, v in params.items() if v not in (None, "")}})
        payload["actions"] = json.dumps(clean)
        payload["action"] = clean[0]["name"]

    return payload


@router.get("/enforcement-log")
def enforcement_log(db: Db, scope: ViewerScope, limit: int = 100) -> list[dict]:
    privacy.forbid_private(scope)
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


@router.get("/bans")
def list_bans(db: Db, scope: ViewerScope) -> list[dict]:
    """Banned devices, with who they belong to, when they were last seen, and
    how often they have tried to stream since."""
    privacy.forbid_private(scope)
    from app.models import BannedDevice

    bans = db.execute(select(BannedDevice).order_by(desc(BannedDevice.banned_at))).scalars().all()
    if not bans:
        return []
    ids = [b.machine_id for b in bans]
    seen = {
        mid: last
        for mid, last in db.execute(
            select(History.machine_id, func.max(History.started)).where(History.machine_id.in_(ids)).group_by(History.machine_id)
        ).all()
    }
    attempts = {
        mid: (count, last)
        for mid, count, last in db.execute(
            select(EnforcementLog.machine_id, func.count(), func.max(EnforcementLog.acted_at))
            .where(EnforcementLog.machine_id.in_(ids), EnforcementLog.rule_name == enforcer.BAN_RULE_NAME)
            .group_by(EnforcementLog.machine_id)
        ).all()
    }
    names = {
        u.user_id: u.friendly_name or u.username
        for u in db.execute(select(User).where(User.user_id.in_([b.user_id for b in bans if b.user_id]))).scalars()
    }
    return [
        {
            **{c.name: getattr(b, c.name) for c in BannedDevice.__table__.columns},
            "user_name": names.get(b.user_id),
            "last_seen": seen.get(b.machine_id),
            "attempts": attempts.get(b.machine_id, (0, None))[0],
            "last_attempt": attempts.get(b.machine_id, (0, None))[1],
        }
        for b in bans
    ]


@router.get("/bans/settings")
def ban_settings(_: AdminUser) -> dict:
    return {
        "record_only": enforcer.record_only(enforcer.Rule(id=0, name=enforcer.BAN_RULE_NAME)),
        "dry_run_locked": enforcer.dry_run_locked(),
    }


@router.put("/bans/settings")
def set_ban_settings(admin: AdminUser, record_only: bool = Body(..., embed=True)) -> dict:
    from app.settings_store import save

    save({"ban_record_only": record_only})
    audit.record(
        admin, "rule.update",
        "Set the ban list to record only" if record_only else "Set the ban list to act",
        target="0", detail={"record_only": {"after": record_only}},
    )
    return ban_settings(admin)


@router.post("/bans")
def ban_device(
    admin: AdminUser,
    machine_id: str = Body(..., embed=True),
    reason: str = Body("", embed=True),
    hours: float | None = Body(None, embed=True),
) -> dict:
    from datetime import timedelta

    from app.models import BannedDevice

    machine_id = machine_id.strip()
    if not machine_id:
        raise HTTPException(400, "Which device?")
    if hours is not None and not 0 < hours <= 24 * 366:
        raise HTTPException(400, "A timed ban can last up to a year. Leave the length empty for a permanent ban.")
    expires = datetime.now(UTC) + timedelta(hours=hours) if hours else None
    with session_scope() as db:
        if db.get(BannedDevice, machine_id) is not None:
            raise HTTPException(409, "That device is already banned")
        device = db.execute(
            select(Device).where(Device.machine_id == machine_id).order_by(desc(Device.last_seen)).limit(1)
        ).scalar_one_or_none()
        label = (device.player if device else None) or machine_id[:12]
        db.add(
            BannedDevice(
                machine_id=machine_id,
                label=label,
                user_id=device.user_id if device else None,
                reason=reason.strip() or None,
                banned_by=admin.username,
                banned_at=datetime.now(UTC),
                expires_at=expires,
            )
        )
    audit.record(
        admin, "device.ban",
        f"Banned {label}" + (f" for {_duration(hours)}" if hours else "") + (f": {reason.strip()}" if reason.strip() else ""),
        target=machine_id,
        detail={"reason": reason.strip() or None},
    )
    return {"machine_id": machine_id, "banned": True}


def _duration(hours: float) -> str:
    if hours % (24 * 7) == 0:
        n = int(hours // (24 * 7))
        return f"{n} week{'s' if n != 1 else ''}"
    if hours % 24 == 0:
        n = int(hours // 24)
        return f"{n} day{'s' if n != 1 else ''}"
    return f"{hours:g} hour{'s' if hours != 1 else ''}"


@router.patch("/bans/{machine_id}")
def edit_ban(machine_id: str, admin: AdminUser, reason: str = Body("", embed=True)) -> dict:
    from app.models import BannedDevice

    with session_scope() as db:
        ban = db.get(BannedDevice, machine_id)
        if ban is None:
            raise HTTPException(404, "That device is not banned")
        before = ban.reason
        ban.reason = reason.strip() or None
        label = ban.label or machine_id[:12]
        after = ban.reason
    audit.record(
        admin, "device.ban_reason", f"Changed the ban reason for {label}", target=machine_id,
        detail={"before": before, "after": after},
    )
    return {"machine_id": machine_id, "reason": after}


@router.delete("/bans/{machine_id}")
def unban_device(machine_id: str, admin: AdminUser) -> dict:
    from app.models import BannedDevice

    with session_scope() as db:
        ban = db.get(BannedDevice, machine_id)
        if ban is None:
            raise HTTPException(404, "That device is not banned")
        label = ban.label or machine_id[:12]
        db.delete(ban)
    audit.record(admin, "device.unban", f"Unbanned {label}", target=machine_id)
    return {"machine_id": machine_id, "banned": False}


def _ban_only_devices(rule: Rule) -> list[str] | None:
    """The device ids of a rule that does nothing but stop those devices, or
    None if the rule does anything else.

    Only exact matches convert: one condition, "device is any of", not
    negated, and the only action is stopping the stream. A rule with a time
    window, a VPN condition or a notification is a real rule and stays one.
    """
    tree = enforcer.rule_tree(rule)
    steps = enforcer.rule_actions(rule)
    if len(steps) != 1 or steps[0].get("name") != "terminate":
        return None
    if tree.get("negate") or len(tree.get("items") or []) != 1:
        return None
    leaf = tree["items"][0]
    if leaf.get("type") != "condition" or leaf.get("field") != "device" or leaf.get("op") != "any":
        return None
    ids = [str(v) for v in (leaf.get("value") or []) if str(v).strip()]
    return ids or None


@router.get("/bans/convertible")
def convertible_rules(db: Db, _: AdminUser) -> list[dict]:
    """Rules made by the old Block button, which only stop given devices."""
    out = []
    for rule in db.execute(select(Rule).order_by(Rule.id)).scalars():
        ids = _ban_only_devices(rule)
        if ids is None:
            continue
        message = next((st.get("params", {}).get("message") for st in enforcer.rule_actions(rule)), None)
        out.append({"id": rule.id, "name": rule.name, "enabled": rule.enabled, "machine_ids": ids, "message": message})
    return out


@router.post("/bans/convert")
def convert_rules_to_bans(admin: AdminUser, rule_ids: list[int] = Body(..., embed=True)) -> dict:
    """Move device-only rules into the ban list, then delete the rules.

    A disabled rule was not stopping anything, so its devices are not banned;
    it is only removed. Devices already banned are left as they are.
    """
    from app.models import BannedDevice

    banned = removed = 0
    with session_scope() as db:
        for rule_id in rule_ids:
            rule = db.get(Rule, rule_id)
            if rule is None:
                continue
            ids = _ban_only_devices(rule)
            if ids is None:
                raise HTTPException(400, f"{rule.name!r} does more than ban devices, so it stays a rule")
            if rule.enabled:
                for mid in ids:
                    if db.get(BannedDevice, mid) is not None:
                        continue
                    device = db.execute(
                        select(Device).where(Device.machine_id == mid).order_by(desc(Device.last_seen)).limit(1)
                    ).scalar_one_or_none()
                    db.add(
                        BannedDevice(
                            machine_id=mid,
                            label=(device.player if device else None) or mid[:12],
                            user_id=device.user_id if device else None,
                            reason=f"Converted from the rule {rule.name!r}",
                            banned_by=admin.username,
                            banned_at=datetime.now(UTC),
                        )
                    )
                    banned += 1
            name = rule.name
            db.delete(rule)
            removed += 1
            audit.record(
                admin, "rule.convert", f"Moved rule {name!r} into the ban list",
                target=str(rule_id), detail={"machine_ids": ids, "was_enabled": rule.enabled},
            )
    return {"rules_removed": removed, "devices_banned": banned}


@router.get("/map/banned")
def banned_on_map(db: Db, scope: ViewerScope) -> dict:
    """Where banned devices have been seen, and where they were stopped.

    Two kinds of point: places a banned device played from (its history),
    and places it tried to stream from after the ban, taken from the
    location recorded when the stream was stopped.
    """
    privacy.forbid_private(scope)
    from app.models import BannedDevice

    bans = {b.machine_id: b for b in db.execute(select(BannedDevice)).scalars()}
    if not bans:
        return {"type": "FeatureCollection", "features": []}

    features = []
    for mid, lat, lon, city, plays, last in db.execute(
        select(
            History.machine_id,
            IpLocation.lat,
            IpLocation.lon,
            func.max(IpLocation.city),
            func.count(),
            func.max(History.started),
        )
        .join(IpLocation, IpLocation.ip == History.ip_address)
        .where(History.machine_id.in_(list(bans)), IpLocation.lat.is_not(None))
        .group_by(History.machine_id, IpLocation.lat, IpLocation.lon)
    ).all():
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "kind": "seen",
                    "machine_id": mid,
                    "label": bans[mid].label,
                    "city": city,
                    "count": plays,
                    "last": last,
                },
            }
        )

    for mid, lat, lon, city, tries, last in db.execute(
        select(
            EnforcementLog.machine_id,
            EnforcementLog.lat,
            EnforcementLog.lon,
            func.max(EnforcementLog.city),
            func.count(),
            func.max(EnforcementLog.acted_at),
        )
        .where(
            EnforcementLog.machine_id.in_(list(bans)),
            EnforcementLog.rule_name == enforcer.BAN_RULE_NAME,
            EnforcementLog.lat.is_not(None),
        )
        .group_by(EnforcementLog.machine_id, EnforcementLog.lat, EnforcementLog.lon)
    ).all():
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "kind": "attempt",
                    "machine_id": mid,
                    "label": bans[mid].label,
                    "city": city,
                    "count": tries,
                    "last": last.isoformat() if last else None,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


@router.get("/rules/fields")
def rule_fields(_: AdminUser, db: Db) -> dict:
    """Everything the rule builder needs to draw its dropdowns. Admin only:
    the options list every device and user."""
    from app.models import Library
    from app.services import conditions as cond

    unmet_by_requirement = {
        "geoip": enforcer.unmet_requirements(
            {"type": "group", "items": [{"type": "condition", "field": "country"}]}
        ),
        "integration:seerr": enforcer.unmet_requirements(
            {"type": "group", "items": [{"type": "condition", "field": "requested_by_viewer"}]}
        ),
    }
    fields = []
    for spec in cond.catalogue():
        missing = sorted({m for r in spec["requires"] for m in unmet_by_requirement.get(r, [])})
        fields.append({**spec, "unmet": missing})

    def distinct(column):
        return [v for (v,) in db.execute(select(column).where(column.is_not(None)).distinct().order_by(column)).all() if v != ""]

    users = db.execute(select(User).order_by(func.lower(func.coalesce(User.friendly_name, User.username)))).scalars()
    devices = db.execute(select(Device).order_by(desc(Device.last_seen))).scalars()
    names = {u.user_id: u.friendly_name or u.username for u in db.execute(select(User)).scalars()}
    countries = db.execute(
        select(IpLocation.country_code, func.max(IpLocation.country))
        .where(IpLocation.country_code.is_not(None))
        .group_by(IpLocation.country_code)
        .order_by(func.max(IpLocation.country))
    ).all()

    seen_devices: set[str] = set()
    device_options = []
    for d in devices:
        if d.machine_id in seen_devices:
            continue
        seen_devices.add(d.machine_id)
        owner = names.get(d.user_id)
        label = " \u00b7 ".join(x for x in (d.player or d.machine_id[:12], d.platform, owner) if x)
        device_options.append({"value": d.machine_id, "label": label})

    return {
        "fields": fields,
        "options": {
            "users": [{"value": u.user_id, "label": u.friendly_name or u.username or str(u.user_id)} for u in users],
            "devices": device_options,
            "platforms": [{"value": v, "label": v} for v in distinct(History.platform)],
            "products": [{"value": v, "label": v} for v in distinct(History.product)],
            "libraries": [
                {"value": lib.section_id, "label": lib.name or str(lib.section_id)}
                for lib in db.execute(select(Library).order_by(Library.name)).scalars()
            ],
            "countries": [{"value": code, "label": name or code} for code, name in countries],
            "content_ratings": [{"value": v, "label": v} for v in distinct(MediaItem.content_rating)],
        },
    }


@router.post("/rules/preview")
async def preview_rule(_: AdminUser, conditions: dict[str, Any] = Body(..., embed=True)) -> dict:
    """Which of the streams playing right now a set of conditions would catch.

    Nothing is acted on and nothing is logged: this is for checking a rule
    before trusting it.
    """
    from app.services import conditions as cond

    try:
        tree = cond.validate(conditions)
    except ValueError as exc:
        raise HTTPException(400, redact(exc)) from exc

    missing = enforcer.unmet_requirements(tree)
    sessions, context, error = await enforcer.live_context()
    if error:
        return {"error": error, "sessions": [], "unmet": missing}
    if "requested_by_viewer" in cond.fields_used(tree):
        await enforcer._add_requests(sessions, context)

    return {
        "unmet": missing,
        "sessions": [
            {
                "session_key": s.get("session_key"),
                "full_title": s.get("full_title"),
                "user": s.get("friendly_name") or s.get("username"),
                "player": s.get("player"),
                "platform": s.get("platform"),
                "matched": not missing and cond.evaluate(tree, s, context.get(str(s.get("session_key")), {})),
            }
            for s in sessions
        ],
    }


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
        return Health(False, redact(exc))
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
        return Health(False, redact(exc))
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
        raise HTTPException(400, redact(exc)) from exc
    return {"ok": health.ok, "detail": health.detail, "version": health.version}


# ---- impossible travel -----------------------------------------------------

@router.get("/travel-flags")
def travel_flags(db: Db, scope: ViewerScope, status: str | None = None, limit: int = 100) -> list[dict]:
    stmt = select(TravelFlag, func.coalesce(User.friendly_name, User.username).label("name")).join(
        User, User.user_id == TravelFlag.user_id, isouter=True
    )
    if status:
        stmt = stmt.where(TravelFlag.status == status)
    if scope is not None:
        stmt = stmt.where(TravelFlag.user_id == (scope.plex_user_id if scope.plex_user_id is not None else -1))
    stmt = stmt.order_by(desc(TravelFlag.to_started)).limit(limit)

    return [
        {
            **{c.name: getattr(flag, c.name) for c in TravelFlag.__table__.columns},
            "user_name": name or str(flag.user_id),
        }
        for flag, name in db.execute(stmt).all()
    ]


def _flag_keys(db: Session, flag: TravelFlag) -> tuple[str, str]:
    """A flag's place keys, worked out and stored if it predates them."""
    from app.services import travel

    if flag.from_key and flag.to_key:
        return flag.from_key, flag.to_key
    places = {
        loc.ip: loc
        for loc in db.execute(select(IpLocation).where(IpLocation.ip.in_([flag.from_ip, flag.to_ip]))).scalars()
    }

    def key(ip: str | None, city: str | None) -> str:
        loc = places.get(ip)
        return travel.place_key(
            (loc.city if loc else None) or city, loc.asn_org if loc else None, loc.is_hosting if loc else None, ip
        )

    flag.from_key = key(flag.from_ip, flag.from_city)
    flag.to_key = key(flag.to_ip, flag.to_city)
    return flag.from_key, flag.to_key


def _key_label(key: str) -> str:
    kind, _, value = key.partition(":")
    return {"network": f"the {value} network", "city": value, "ip": f"address {value}"}.get(kind, key)


@router.get("/travel-flags/{flag_id}")
def travel_flag_detail(flag_id: int, db: Db, scope: ViewerScope) -> dict:
    """Both plays behind a signal, where each was, and what separates them."""
    from app.models import SignalIgnore

    flag = db.get(TravelFlag, flag_id)
    if flag is None:
        raise HTTPException(404, "No such signal")
    privacy.require_self(scope, flag.user_id)
    user = db.get(User, flag.user_id)
    from_key, to_key = _flag_keys(db, flag)
    # Signals found before places were recorded get theirs now, so the count
    # of similar signals below is not missing the older ones.
    for other in db.execute(
        select(TravelFlag).where(TravelFlag.user_id == flag.user_id, TravelFlag.from_key.is_(None))
    ).scalars():
        _flag_keys(db, other)
    db.commit()

    def side(history_id: int, ip: str | None) -> dict:
        play = db.get(History, history_id)
        loc = db.get(IpLocation, ip) if ip else None
        return {
            "play": None
            if play is None
            else {c.name: getattr(play, c.name) for c in History.__table__.columns},
            "place": None
            if loc is None
            else {
                "city": loc.city,
                "region": loc.region,
                "country": loc.country,
                "lat": loc.lat,
                "lon": loc.lon,
                "accuracy_km": loc.accuracy_radius,
                "asn_org": loc.asn_org,
                "is_hosting": loc.is_hosting,
            },
        }

    first = side(flag.from_history_id, flag.from_ip)
    second = side(flag.to_history_id, flag.to_ip)

    # How the two plays sit in time: an overlap for a concurrent pair, a gap
    # otherwise, both in seconds so the page can word it.
    from app.services import travel

    a, b = first["play"] or {}, second["play"] or {}
    # The same end the detection uses: when the first play was last watched,
    # not when a paused session finally closed.
    a_end = a.get("stopped") or a.get("started")
    if a_end and a.get("play_duration") and a.get("started"):
        a_end = min(a_end, a["started"] + a["play_duration"] + travel.PAUSE_SLACK_SECONDS)
    gap = (b.get("started") - a_end) if (b.get("started") and a_end) else None

    a_key, b_key = travel.pair(from_key, to_key)
    pattern = db.execute(
        select(SignalIgnore).where(
            SignalIgnore.user_id == flag.user_id, SignalIgnore.key_a == a_key, SignalIgnore.key_b == b_key
        )
    ).scalar_one_or_none()
    similar = db.execute(
        select(func.count()).select_from(TravelFlag).where(
            TravelFlag.user_id == flag.user_id,
            TravelFlag.id != flag.id,
            ((TravelFlag.from_key == from_key) & (TravelFlag.to_key == to_key))
            | ((TravelFlag.from_key == to_key) & (TravelFlag.to_key == from_key)),
        )
    ).scalar_one()

    return {
        **{c.name: getattr(flag, c.name) for c in TravelFlag.__table__.columns},
        "user_name": (user.friendly_name or user.username) if user else str(flag.user_id),
        "from": first,
        "to": second,
        "gap_seconds": gap,
        "pattern_label": f"{_key_label(from_key)} and {_key_label(to_key)}",
        "ignore": None
        if pattern is None
        else {c.name: getattr(pattern, c.name) for c in SignalIgnore.__table__.columns},
        "similar": similar,
    }


@router.patch("/travel-flags/{flag_id}")
def review_flag(
    flag_id: int,
    admin: AdminUser,
    status: str = Body(..., embed=True),
    reason: str = Body("", embed=True),
) -> dict:
    """Reviewed closes this one signal. Ignored also records a pattern, so the
    same person moving between the same two places is closed automatically,
    now and in future. New reopens a signal a person closed."""
    from app.models import SignalIgnore
    from app.services import travel

    if status not in {"new", "reviewed", "ignored"}:
        raise HTTPException(400, "Status must be new, reviewed or ignored")

    closed_too = 0
    with session_scope() as db:
        flag = db.get(TravelFlag, flag_id)
        if flag is None:
            raise HTTPException(404, "No such flag")
        before = flag.status
        user = db.get(User, flag.user_id)
        who = (user.friendly_name or user.username) if user else str(flag.user_id)
        from_key, to_key = _flag_keys(db, flag)
        label = f"{_key_label(from_key)} and {_key_label(to_key)}"

        flag.status = status
        flag.ignore_id = None

        if status == "ignored":
            a_key, b_key = travel.pair(from_key, to_key)
            pattern = db.execute(
                select(SignalIgnore).where(
                    SignalIgnore.user_id == flag.user_id, SignalIgnore.key_a == a_key, SignalIgnore.key_b == b_key
                )
            ).scalar_one_or_none()
            if pattern is None:
                pattern = SignalIgnore(
                    user_id=flag.user_id,
                    key_a=a_key,
                    key_b=b_key,
                    label=label,
                    reason=reason.strip() or None,
                    created_by=admin.username,
                    created_at=datetime.now(UTC),
                )
                db.add(pattern)
                db.flush()
            flag.ignore_id = pattern.id

            # Earlier open signals with the same pattern close now, rather than
            # each needing the same click.
            for other in db.execute(
                select(TravelFlag).where(
                    TravelFlag.user_id == flag.user_id, TravelFlag.status == "new", TravelFlag.id != flag.id
                )
            ).scalars():
                if travel.pair(*_flag_keys(db, other)) == (a_key, b_key):
                    other.status = "ignored"
                    other.ignore_id = pattern.id
                    closed_too += 1

    verb = {"reviewed": "Reviewed", "ignored": "Ignored", "new": "Reopened"}[status]
    summary = f"{verb} a sharing signal for {who}"
    if status == "ignored":
        summary = f"Ignored signals for {who} between {label}" + (f", closing {closed_too} more" if closed_too else "")
    audit.record(
        admin, "travel.review", summary, target=str(flag_id),
        detail={"before": before, "after": status, "user_id": flag.user_id, "pattern": label, "closed_too": closed_too},
    )
    return {"id": flag_id, "status": status, "closed_too": closed_too}


@router.get("/signal-ignores")
def list_signal_ignores(db: Db, scope: ViewerScope) -> list[dict]:
    privacy.forbid_private(scope)
    from app.models import SignalIgnore

    rows = db.execute(select(SignalIgnore).order_by(desc(SignalIgnore.created_at))).scalars().all()
    names = {
        u.user_id: u.friendly_name or u.username
        for u in db.execute(select(User).where(User.user_id.in_([r.user_id for r in rows]))).scalars()
    }
    counts = dict(
        db.execute(
            select(TravelFlag.ignore_id, func.count()).where(TravelFlag.ignore_id.is_not(None)).group_by(TravelFlag.ignore_id)
        ).all()
    )
    return [
        {
            **{c.name: getattr(r, c.name) for c in SignalIgnore.__table__.columns},
            "user_name": names.get(r.user_id) or str(r.user_id),
            "closed": counts.get(r.id, 0),
        }
        for r in rows
    ]


@router.delete("/signal-ignores/{ignore_id}")
def delete_signal_ignore(ignore_id: int, admin: AdminUser) -> dict:
    """Stop ignoring a pattern. Every signal it closed reopens, including the
    one it was created from; signals a person marked reviewed stay reviewed."""
    from app.models import SignalIgnore

    with session_scope() as db:
        pattern = db.get(SignalIgnore, ignore_id)
        if pattern is None:
            raise HTTPException(404, "No such pattern")
        label = pattern.label
        user = db.get(User, pattern.user_id)
        who = (user.friendly_name or user.username) if user else str(pattern.user_id)
        reopened = 0
        for flag in db.execute(select(TravelFlag).where(TravelFlag.ignore_id == ignore_id)).scalars():
            flag.status = "new"
            flag.ignore_id = None
            reopened += 1
        db.delete(pattern)
    audit.record(
        admin, "travel.unignore", f"Stopped ignoring signals for {who} between {label}, reopening {reopened}",
        target=str(ignore_id),
    )
    return {"deleted": ignore_id, "reopened": reopened}


# ---- dashboard -------------------------------------------------------------

@router.get("/dashboard")
async def dashboard(db: Db, filters: Filt, scope: ViewerScope) -> dict:
    """Everything the landing screen needs, composed in one call.

    Live activity is awaited here; the history counts run in a worker thread,
    since on a large history they take long enough to hold up every other
    request if run on the event loop."""
    import asyncio

    live = await activity(db, scope)
    return await asyncio.to_thread(_dashboard_payload, db, filters, scope, live)


def _dashboard_payload(db: Session, filters: Filters, scope: "privacy.Scope | None", live: dict) -> dict:
    """The dashboard's history counts, with live activity already fetched.

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
            plays(History),
            func.count(func.distinct(History.user_id)),
            func.count(func.distinct(History.machine_id)),
            func.count(func.distinct(History.rating_key)),
            func.count(func.distinct(History.ip_address)),
            func.count(),
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
        filtered(day, plays(History).label("plays"))
        .group_by(day)
        .order_by(desc(day))
        .limit(30)
    ).all()

    top_users = db.execute(
        filtered(
            History.user_id,
            func.coalesce(User.friendly_name, User.username).label("name"),
            plays(History).label("plays"),
        )
        .join(User, User.user_id == History.user_id, isouter=True)
        .group_by(History.user_id)
        .order_by(desc(plays(History)))
        .limit(5)
    ).all()

    new_devices = db.execute(
        select(func.count()).select_from(Device).where(
            Device.is_new_unreviewed.is_(True),
            *([Device.user_id == (scope.plex_user_id if scope.plex_user_id is not None else -1)] if scope is not None else []),
        )
    ).scalar_one()

    me = scope.plex_user_id if scope is not None and scope.plex_user_id is not None else -1
    open_flags = db.execute(
        select(func.count()).select_from(TravelFlag).where(
            TravelFlag.status == "new", *([TravelFlag.user_id == me] if scope is not None else [])
        )
    ).scalar_one()

    last_enforcement = (
        []
        if scope is not None
        else db.execute(select(EnforcementLog).order_by(desc(EnforcementLog.acted_at)).limit(5)).scalars()
    )

    if scope is not None and not scope.own_only:
        from types import SimpleNamespace

        # Anonymised: the ranking stays, other people's names do not.
        top_users = [
            SimpleNamespace(
                user_id=r.user_id if r.user_id == me else None,
                name=r.name if r.user_id == me else privacy.ANOTHER,
                plays=r.plays,
            )
            for r in top_users
        ]

    return {
        "capabilities": capabilities.as_map(),
        "settings": {
            "enforce_enabled": current().enforce_enabled,
            "dry_run_locked": enforcer.dry_run_locked(),
            "record_only_rules": sum(
                1
                for r in db.execute(select(Rule).where(Rule.enabled.is_(True))).scalars()
                if enforcer.record_only(r)
            ),
            "enabled_rules": db.execute(
                select(func.count()).select_from(Rule).where(Rule.enabled.is_(True))
            ).scalar_one(),
        },
        "totals": {
            "plays": totals[0],
            "sessions": totals[5],
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

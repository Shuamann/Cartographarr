"""The Reports tab: run a report, list the presets, keep saved reports.

Plays are open to everyone signed in, narrowed by viewer privacy. Buffering
and rule matches are admin only, like the Log they come from. Saved reports
are shared: admins save and delete them, everyone can open the ones they are
allowed to run.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from sqlalchemy import select

from app import audit
from app.auth.deps import AdminUser, CurrentUser
from app.models import SavedReport
from app.privacy import ScopedFilt, ViewerScope
from app.routers.data import Db
from app.services import reports
from app.settings_store import current

router = APIRouter(prefix="/api/reports")


@router.get("/catalog")
def catalog(user: CurrentUser) -> dict:
    return reports.catalog(admin=user.role == "admin", geoip=(current().geoip_dir / "city.mmdb").exists())


@router.get("/run")
def run(
    user: CurrentUser,
    scope: ViewerScope,
    filters: ScopedFilt,
    db: Db,
    source: str = Query("plays"),
    measure: str = Query("plays"),
    group: str = Query("user"),
    then: str | None = Query(None),
    limit: int = Query(25, ge=1, le=200),
) -> dict:
    spec = reports.SOURCES.get(source)
    if spec is not None and spec.admin_only and user.role != "admin":
        raise HTTPException(403, f"{spec.label} reports are for admins")
    # Anonymised viewers see server-wide totals, but a report that names
    # people, devices, addresses or titles is narrowed to their own.
    narrowed = scope is not None and scope.own_only
    if scope is not None and not scope.own_only:
        if any(reports.DIMENSION.get(d) and reports.DIMENSION[d].identifying for d in (group, then) if d):
            filters.user_id = [scope.plex_user_id if scope.plex_user_id is not None else -1]
            narrowed = True
    try:
        result = reports.run(db, filters, source=source, measure=measure, group=group, then=then or None, limit=limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    result["narrowed_to_you"] = narrowed
    return result


def _out(row: SavedReport) -> dict[str, Any]:
    try:
        spec = json.loads(row.spec)
    except ValueError:
        spec = {}
    return {"id": row.id, "name": row.name, **spec, "created_by": row.created_by,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


SPEC_KEYS = ("source", "measure", "group", "then", "range", "filters", "chart")


def _clean(body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "A saved report needs a name")
    spec = {k: body.get(k) for k in SPEC_KEYS}
    try:
        reports.validate(str(spec["source"]), str(spec["measure"]), str(spec["group"]), spec["then"] or None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return name[:255], spec


@router.get("/saved")
def saved(user: CurrentUser, db: Db) -> list:
    rows = db.execute(select(SavedReport).order_by(SavedReport.name)).scalars().all()
    out = [_out(r) for r in rows]
    if user.role != "admin":
        out = [r for r in out if not (reports.SOURCES.get(r.get("source")) or reports.SOURCES["matches"]).admin_only]
    return out


@router.post("/saved")
def save(admin: AdminUser, db: Db, body: dict[str, Any] = Body(...)) -> dict:
    name, spec = _clean(body)
    now = datetime.now(UTC)
    row = SavedReport(name=name, spec=json.dumps(spec), created_by=admin.username, created_at=now, updated_at=now)
    db.add(row)
    db.commit()
    audit.record(admin, "report.save", f"Saved report '{name}'", target=str(row.id))
    return _out(row)


@router.put("/saved/{report_id}")
def update(report_id: int, admin: AdminUser, db: Db, body: dict[str, Any] = Body(...)) -> dict:
    row = db.get(SavedReport, report_id)
    if row is None:
        raise HTTPException(404, "No such report")
    name, spec = _clean(body)
    row.name, row.spec, row.updated_at = name, json.dumps(spec), datetime.now(UTC)
    db.commit()
    audit.record(admin, "report.update", f"Updated report '{name}'", target=str(row.id))
    return _out(row)


@router.delete("/saved/{report_id}")
def delete(report_id: int, admin: AdminUser, db: Db) -> dict:
    row = db.get(SavedReport, report_id)
    if row is None:
        raise HTTPException(404, "No such report")
    name = row.name
    db.delete(row)
    db.commit()
    audit.record(admin, "report.delete", f"Deleted report '{name}'", target=str(report_id))
    return {"ok": True}

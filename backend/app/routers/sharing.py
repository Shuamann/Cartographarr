"""Sharing endpoints.

Admin only, and every change is written to the audit log with what it was
before, because these are the only actions in the app that reach outside it
and cannot be taken back.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Body, HTTPException

from app.auth.deps import AdminUser
from app import audit
from app.db import session_scope
from app.models import AuditLog
from app.plex import sharing

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sharing")


def require_plex() -> None:
    """Refuse clearly rather than letting plexapi raise into a 500."""
    if not sharing.configured():
        raise HTTPException(
            409, "Sharing needs a Plex token. Add one in Settings."
        )


@router.get("/status")
async def status(_: AdminUser) -> dict:
    return await sharing.run(sharing.status)


@router.get("")
async def list_shares(_: AdminUser) -> dict:
    if not sharing.configured():
        return {"configured": False, "users": [], "sections": []}
    try:
        users = await sharing.run(sharing.list_shares)
        sections = await sharing.run(sharing.all_sections)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Plex said: {exc}") from exc
    return {"configured": True, "users": users, "sections": sections}


@router.put("/{username}/sections")
async def set_sections(
    username: str, admin: AdminUser, sections: list[str] = Body(..., embed=True)
) -> dict:
    require_plex()
    before = await sharing.run(sharing._sections_for, username)
    try:
        result = await sharing.run(sharing.set_sections, username, sections)
    except Exception as exc:  # noqa: BLE001
        audit.record(
            admin, "sharing.sections", f"Tried to change {username}'s libraries",
            target=username, detail={"sections": sections}, result=f"failed: {exc}",
        )
        raise HTTPException(502, f"Plex refused: {exc}") from exc

    audit.record(
        admin, "sharing.sections",
        f"Changed {username}'s libraries to {', '.join(result['sections']) or 'nothing'}",
        target=username, detail={"before": before, "after": result["sections"]},
    )
    return result


@router.delete("/{username}")
async def unshare(username: str, admin: AdminUser, confirm: str = Body(..., embed=True)) -> dict:
    """Remove someone's access.

    The username has to be typed back. This cannot be undone from here, it
    needs a fresh invitation the other person accepts, so a misclick should not
    be enough.
    """
    require_plex()
    if confirm.strip() != username:
        raise HTTPException(400, "Type the username exactly to confirm")

    before = await sharing.run(sharing._sections_for, username)
    try:
        result = await sharing.run(sharing.unshare, username)
    except Exception as exc:  # noqa: BLE001
        audit.record(
            admin, "sharing.unshare", f"Tried to stop sharing with {username}",
            target=username, detail={"before": before}, result=f"failed: {exc}",
        )
        raise HTTPException(502, f"Plex refused: {exc}") from exc

    audit.record(
        admin, "sharing.unshare", f"Stopped sharing with {username}",
        target=username, detail={"before": before}, result="removed",
    )
    return result


@router.get("/audit")
def audit(_: AdminUser, limit: int = 100) -> list[dict]:
    from sqlalchemy import desc, select

    with session_scope() as db:
        rows = db.execute(
            select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
        ).scalars()
        return [{c.name: getattr(r, c.name) for c in AuditLog.__table__.columns} for r in rows]

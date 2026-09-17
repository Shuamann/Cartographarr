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
from app.redact import redact

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sharing")


def require_plex() -> None:
    """Refuse clearly rather than letting plexapi raise into a 500."""
    if not sharing.configured():
        raise HTTPException(
            409, "Sharing needs a Plex token. Add one in Settings."
        )


@router.post("/servers")
async def list_servers(_: AdminUser, values: dict = Body(default_factory=dict, embed=True)) -> dict:
    """Servers the Plex token can see, using the token typed on the page if
    there is one, so the server can be picked before saving."""
    from app.settings_store import trial

    with trial(values):
        if not sharing.configured():
            return {"servers": [], "error": "Add a Plex token first"}
        try:
            return {"servers": await sharing.run(sharing.servers), "error": None}
        except Exception as exc:  # noqa: BLE001 - the failure is the answer
            text = redact(exc)
            if "401" in text or "Unauthorized" in text:
                text = "Plex rejected that token"
            return {"servers": [], "error": text}


@router.get("/status")
async def status(_: AdminUser) -> dict:
    return await sharing.run(sharing.status)


_cache: dict[str, object] = {"at": 0.0, "value": None}
CACHE_SECONDS = 120


def _forget() -> None:
    _cache["at"], _cache["value"] = 0.0, None


@router.get("")
async def list_shares(_: AdminUser, fresh: bool = False) -> dict:
    import asyncio
    import time

    if not sharing.configured():
        return {"configured": False, "users": [], "sections": []}
    if not fresh and _cache["value"] is not None and time.time() - float(_cache["at"]) < CACHE_SECONDS:
        return _cache["value"]  # type: ignore[return-value]
    try:
        # A time limit, so a slow plex.tv is an error on the page rather than
        # a page that says Loading forever.
        users, sections = await asyncio.wait_for(
            asyncio.gather(sharing.run(sharing.list_shares), sharing.run(sharing.all_sections)), timeout=45
        )
    except TimeoutError as exc:
        raise HTTPException(504, "Plex took longer than 45 seconds to answer. Try again in a moment.") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Plex said: {redact(exc)}") from exc
    value = {"configured": True, "users": users, "sections": sections}
    _cache["at"], _cache["value"] = time.time(), value
    return value


@router.put("/{username}/sections")
async def set_sections(
    username: str, admin: AdminUser, sections: list[str] = Body(..., embed=True)
) -> dict:
    require_plex()
    _forget()
    before = await sharing.run(sharing._sections_for, username)
    try:
        result = await sharing.run(sharing.set_sections, username, sections)
    except Exception as exc:  # noqa: BLE001
        audit.record(
            admin, "sharing.sections", f"Tried to change {username}'s libraries",
            target=username, detail={"sections": sections}, result=f"failed: {redact(exc)}",
        )
        raise HTTPException(502, f"Plex refused: {redact(exc)}") from exc

    audit.record(
        admin, "sharing.sections",
        f"Changed {username}'s libraries to {', '.join(result['sections']) or 'nothing'}",
        target=username, detail={"before": before, "after": result["sections"]},
    )
    _forget()
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

    _forget()
    before = await sharing.run(sharing._sections_for, username)
    try:
        result = await sharing.run(sharing.unshare, username)
    except Exception as exc:  # noqa: BLE001
        audit.record(
            admin, "sharing.unshare", f"Tried to stop sharing with {username}",
            target=username, detail={"before": before}, result=f"failed: {redact(exc)}",
        )
        raise HTTPException(502, f"Plex refused: {redact(exc)}") from exc

    audit.record(
        admin, "sharing.unshare", f"Stopped sharing with {username}",
        target=username, detail={"before": before}, result="removed",
    )
    _forget()
    return result


@router.get("/audit")
def sharing_audit(_: AdminUser, limit: int = 100) -> list[dict]:
    from sqlalchemy import desc, select

    with session_scope() as db:
        rows = db.execute(
            select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
        ).scalars()
        return [{c.name: getattr(r, c.name) for c in AuditLog.__table__.columns} for r in rows]

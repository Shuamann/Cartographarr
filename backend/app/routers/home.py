"""The home page: where to go next, and what needs someone right now."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from sqlalchemy import func, select

from app import audit
from app.auth.deps import AdminUser, CurrentUser
from app.db import session_scope
from app.models import HomeLink, Issue
from app.services import home
from app.settings_store import current

router = APIRouter(prefix="/api/home")


@router.get("")
def home_page(user: CurrentUser) -> dict:
    """Links for this person, and anything open that is theirs to deal with."""
    is_admin = user.role == "admin"
    with session_scope() as db:
        if is_admin:
            open_issues = db.execute(select(func.count()).select_from(Issue).where(Issue.status == "open")).scalar() or 0
        elif user.plex_user_id:
            open_issues = db.execute(
                select(func.count()).select_from(Issue)
                .where(Issue.status == "open", Issue.reporter_user_id == user.plex_user_id)
            ).scalar() or 0
        else:
            open_issues = 0
    return {
        "app_name": current().app_name,
        "username": user.username,
        "role": user.role,
        "links": home.links_for("admin" if is_admin else "viewer"),
        "open_issues": open_issues,
    }


@router.get("/links")
def list_links(_: AdminUser) -> list[dict[str, Any]]:
    """Every link, hidden ones and all, for the settings page."""
    return home.all_links()


def _save(key: str, values: dict[str, Any], custom: bool = False) -> None:
    with session_scope() as db:
        row = db.get(HomeLink, key)
        if row is None:
            row = HomeLink(key=key, custom=custom)
            db.add(row)
        for field, value in values.items():
            setattr(row, field, value)


@router.put("/links/{key:path}")
def update_link(
    key: str,
    admin: AdminUser,
    label: str | None = Body(None, embed=True),
    url: str | None = Body(None, embed=True),
    roles: str | None = Body(None, embed=True),
    position: int | None = Body(None, embed=True),
    hidden: bool | None = Body(None, embed=True),
) -> list[dict[str, Any]]:
    known = {link["key"] for link in home.all_links()}
    if key not in known:
        raise HTTPException(404, "No such link")
    if roles is not None and roles not in home.ROLES:
        raise HTTPException(400, f"Who sees it should be one of {', '.join(home.ROLES)}")
    values = {k: v for k, v in {"label": label, "url": url, "roles": roles, "position": position, "hidden": hidden}.items() if v is not None}
    if values:
        _save(key, values)
        audit.record(admin, "home.link", f"Changed the {label or key} link on the home page", target=key,
                     detail={k: {"after": v} for k, v in values.items()})
    return home.all_links()


@router.post("/links")
def add_link(
    admin: AdminUser,
    label: str = Body(..., embed=True),
    url: str = Body(..., embed=True),
    icon: str = Body("", embed=True),
    roles: str = Body("all", embed=True),
) -> list[dict[str, Any]]:
    if not label.strip() or not url.strip():
        raise HTTPException(400, "A link needs a name and an address")
    if not url.startswith(("http://", "https://", "/")):
        raise HTTPException(400, "An address starts with http://, https:// or /")
    if roles not in home.ROLES:
        raise HTTPException(400, f"Who sees it should be one of {', '.join(home.ROLES)}")
    key = home.next_custom_key()
    _save(key, {"label": label.strip(), "url": url.strip(), "icon": icon.strip(), "roles": roles,
                "position": 100, "hidden": False}, custom=True)
    audit.record(admin, "home.link", f"Added {label.strip()} to the home page", target=key)
    return home.all_links()


@router.delete("/links/{key:path}")
def remove_link(key: str, admin: AdminUser) -> list[dict[str, Any]]:
    """Custom links are deleted. A built in one is hidden instead, because it
    would only come back the next time the settings were read."""
    with session_scope() as db:
        row = db.get(HomeLink, key)
        if row is not None and row.custom:
            db.delete(row)
            audit.record(admin, "home.link", f"Removed {row.label or key} from the home page", target=key)
            return home.all_links()
    if key not in {link["key"] for link in home.all_links()}:
        raise HTTPException(404, "No such link")
    _save(key, {"hidden": True})
    audit.record(admin, "home.link", f"Hid the {key} link on the home page", target=key)
    return home.all_links()

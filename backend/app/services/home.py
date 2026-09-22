"""The home page: where to go next, for whoever just signed in.

Links for the services that are already set up are worked out from the
settings, so a new install has a working home page without anyone filling in a
form. Each one can be renamed, pointed somewhere else, given to one role only,
moved or hidden, and links of your own can be added beside them.

Viewers get the places they use: Plex, the request service. Admins also get the
services behind it: Sonarr, Radarr, Tautulli, the request service's own admin.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.settings_store import current

ROLES = ("all", "admin", "viewer")


def _plex_url(settings) -> str:
    machine = settings.plex_machine_identifier
    return f"https://app.plex.tv/desktop/#!/server/{machine}" if machine else "https://app.plex.tv/desktop"


def built_in() -> list[dict[str, Any]]:
    """One link per service that is set up, in the order they are used."""
    from app.integrations.arr import radarr, sonarr
    from app.integrations.seerr import seerr

    settings = current()
    out: list[dict[str, Any]] = [
        {"key": "plex", "label": "Watch on Plex", "url": _plex_url(settings), "icon": "plex", "roles": "all"},
    ]
    if seerr.configured():
        out.append({"key": "seerr", "label": "Request something", "url": seerr.link_base, "icon": "seerr", "roles": "all"})
    for service, icon in ((sonarr, "sonarr"), (radarr, "radarr")):
        if service.configured():
            out.append({
                "key": service.name, "label": service.label, "url": service.link_base,
                "icon": icon, "roles": "admin",
            })
    tautulli = (settings.tautulli_url or "").rstrip("/")
    if tautulli:
        out.append({"key": "tautulli", "label": "Tautulli", "url": tautulli, "icon": "", "roles": "admin"})
    for index, link in enumerate(out):
        link.setdefault("position", index)
        link["custom"] = False
    return out


def _merge(rows: dict[str, Any]) -> list[dict[str, Any]]:
    links = []
    for link in built_in():
        saved = rows.get(link["key"])
        if saved is None:
            links.append({**link, "hidden": False})
            continue
        links.append({
            **link,
            "label": saved.label or link["label"],
            "url": saved.url or link["url"],
            "icon": saved.icon if saved.icon is not None else link["icon"],
            "roles": saved.roles,
            "position": saved.position,
            "hidden": bool(saved.hidden),
        })
    for saved in rows.values():
        if saved.custom:
            links.append({
                "key": saved.key, "label": saved.label or saved.url, "url": saved.url,
                "icon": saved.icon or "", "roles": saved.roles, "position": saved.position,
                "hidden": bool(saved.hidden), "custom": True,
            })
    links.sort(key=lambda link: (link["position"], link["label"] or ""))
    return links


def all_links() -> list[dict[str, Any]]:
    """Every link, hidden ones included. For the settings page."""
    from app.models import HomeLink

    with session_scope() as db:
        rows = {row.key: row for row in db.execute(select(HomeLink)).scalars()}
        return _merge(rows)


def links_for(role: str) -> list[dict[str, Any]]:
    """What this person should see, without anything they have no use for."""
    return [
        {k: v for k, v in link.items() if k != "hidden"}
        for link in all_links()
        if not link["hidden"] and link["url"] and link["roles"] in ("all", role)
    ]


def next_custom_key() -> str:
    from app.models import HomeLink

    with session_scope() as db:
        used = [row.key for row in db.execute(select(HomeLink).where(HomeLink.custom.is_(True))).scalars()]
    numbers = [int(key.split(":")[1]) for key in used if key.startswith("custom:") and key.split(":")[1].isdigit()]
    return f"custom:{max(numbers, default=0) + 1}"

"""What a signed-in viewer is allowed to see.

Admins always see everything. For viewers there is one setting,
`viewer_privacy`:

- `all`: viewers see the whole server, as before.
- `own`: viewers see only their own plays, devices, addresses and streams.
  Everyone else is simply absent.
- `anonymised`: totals, the map and charts still cover the whole server, but
  other people are not identifiable. Their names become "Another viewer" and
  their addresses, device ids, players and the titles they watched are
  withheld. Anything that lists people (People, signals) shows only the
  viewer.

A viewer is matched to a Plex user by the account's linked Plex user, or
failing that by email or username. A viewer who matches nobody sees no
personal data at all in either private mode.

Enforced here and in the API, never only in the page: a viewer can call the
API directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException
from sqlalchemy import func, or_, select

from app.auth.deps import CurrentUser
from app.db import session_scope
from app.filters import Filters
from app.models import AppUser, User
from app.settings_store import current

MODES = ("all", "own", "anonymised")
ANOTHER = "Another viewer"


@dataclass(frozen=True)
class Scope:
    mode: str  # "own" or "anonymised"
    plex_user_id: int | None

    @property
    def own_only(self) -> bool:
        return self.mode == "own"

    def is_self(self, user_id: Any) -> bool:
        return self.plex_user_id is not None and user_id is not None and int(user_id) == self.plex_user_id


def linked_plex_user(account: AppUser) -> int | None:
    """The Plex user this account belongs to, set by hand or matched."""
    if account.plex_user_id:
        return account.plex_user_id
    keys = {v.strip().lower() for v in (account.email, account.username) if v and v.strip()}
    if not keys:
        return None
    with session_scope() as db:
        match = db.execute(
            select(User.user_id)
            .where(
                or_(
                    func.lower(User.email).in_(keys),
                    func.lower(User.username).in_(keys),
                    func.lower(User.friendly_name).in_(keys),
                )
            )
            .limit(1)
        ).scalar_one_or_none()
    return match


def scope_for(account: AppUser) -> Scope | None:
    """None means no restriction."""
    if account.role == "admin":
        return None
    mode = getattr(current(), "viewer_privacy", "all") or "all"
    if mode not in ("own", "anonymised"):
        return None
    return Scope(mode=mode, plex_user_id=linked_plex_user(account))


def viewer_scope(user: CurrentUser) -> Scope | None:
    return scope_for(user)


ViewerScope = Annotated[Scope | None, Depends(viewer_scope)]


def scoped_filters(scope: ViewerScope, filters: Filters = Depends()) -> Filters:
    """The request's filters, narrowed to what the viewer may ask about.

    Own mode pins every query to the viewer. Anonymised mode lets totals and
    the map cover everyone, but a filter naming another person, device or
    address would single them out, so those are pinned to the viewer too.
    """
    if scope is None:
        return filters
    me = [scope.plex_user_id] if scope.plex_user_id is not None else [-1]
    if scope.own_only:
        filters.user_id = me
    else:
        if filters.user_id and any(not scope.is_self(u) for u in filters.user_id):
            filters.user_id = me
        if filters.machine_id or filters.ip_address:
            filters.user_id = me
    return filters


ScopedFilt = Annotated[Filters, Depends(scoped_filters)]


def require_self(scope: Scope | None, user_id: Any) -> None:
    """For endpoints about one person: only the viewer themself."""
    if scope is not None and not scope.is_self(user_id):
        raise HTTPException(403, "You can only see your own details")


def forbid_private(scope: Scope | None) -> None:
    """For admin-level views (rules, bans, the log) while privacy is on."""
    if scope is not None:
        raise HTTPException(403, "Not available to viewers while viewer privacy is on")


# ---- scrubbing for anonymised mode ----------------------------------------------

HIDDEN_PLAY_FIELDS = (
    "user_id",
    "machine_id",
    "ip_address",
    "player",
    "full_title",
    "title",
    "rating_key",
    "parent_rating_key",
    "grandparent_rating_key",
    "thumb",
    "year",
    "reference_id",
)


def scrub_play(scope: Scope | None, row: dict) -> dict:
    """A history row, with someone else's identifying details removed."""
    if scope is None or scope.is_self(row.get("user_id")):
        return row
    out = dict(row)
    for key in HIDDEN_PLAY_FIELDS:
        if key in out:
            out[key] = None
    out["anonymised"] = True
    return out


def scrub_session(scope: Scope | None, session: dict) -> dict:
    """A live stream. Others keep only that something is playing, roughly
    where (city level), and how, with no person, device, address or title."""
    if scope is None or scope.is_self(session.get("user_id")):
        return session
    keep = {
        "session_key",
        "state",
        "progress_percent",
        "media_type",
        "transcode_decision",
        "video_decision",
        "audio_decision",
        "video_full_resolution",
        "stream_video_full_resolution",
        "quality_profile",
        "bandwidth",
        "location",
        "library_name",
    }
    out = {k: v for k, v in session.items() if k in keep}
    geo = session.get("geo") or None
    out["geo"] = (
        None
        if geo is None
        else {
            "city": geo.get("city"),
            "region": geo.get("region"),
            "country": geo.get("country"),
            "lat": geo.get("lat"),
            "lon": geo.get("lon"),
            "is_hosting": geo.get("is_hosting"),
            "asn_org": None,
        }
    )
    out["friendly_name"] = ANOTHER
    out["full_title"] = "Something"
    out["anonymised"] = True
    return out

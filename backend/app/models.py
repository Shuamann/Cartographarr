"""ORM models. Grows a table per phase.

Column set is what Tautulli's get_history actually returns (verified by
scripts/probe_source.py), plus section_id backfilled from get_metadata.
Deliberately absent: video_resolution, bandwidth, quality_profile. They need a
per-row get_stream_data call, and nothing needs them from history. Rules read
live get_activity, which carries them already. Stream detail fetches them on
demand for the one row being looked at.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Setting(Base):
    """A setting saved from the UI.

    Stored as text and re-validated through the pydantic Settings model on
    load, so the field's declared type is the single source of truth for
    coercion. Anything set by an environment variable never reaches this
    table. See settings_store.load().
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class SyncState(Base):
    """Cursors and watermarks. Key/value so a new sync job needs no migration."""

    __tablename__ = "sync_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255))
    friendly_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    thumb: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_home_user: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen: Mapped[int | None] = mapped_column(Integer)


class Device(Base):
    """One physical client install.

    machine_id is Plex's clientIdentifier, stable across renames, which is why
    rules match on it and not on `player`.
    """

    __tablename__ = "devices"
    __table_args__ = (Index("ix_devices_user", "user_id"),)

    machine_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # No FK to users: Tautulli history outlives the user record. Someone
    # removed from the Plex share still has devices and plays in history.
    player: Mapped[str | None] = mapped_column(String(255))
    platform: Mapped[str | None] = mapped_column(String(255))
    product: Mapped[str | None] = mapped_column(String(255))
    first_seen: Mapped[int | None] = mapped_column(Integer)
    last_seen: Mapped[int | None] = mapped_column(Integer)
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    is_new_unreviewed: Mapped[bool] = mapped_column(Boolean, default=True)


class IpLocation(Base):
    """Geocode cache. One row per IP, resolved once, never looked up twice."""

    __tablename__ = "ip_locations"

    ip: Mapped[str] = mapped_column(String(45), primary_key=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    city: Mapped[str | None] = mapped_column(String(255))
    region: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(255))
    country_code: Mapped[str | None] = mapped_column(String(2))
    postal: Mapped[str | None] = mapped_column(String(32))
    timezone: Mapped[str | None] = mapped_column(String(64))
    accuracy_radius: Mapped[int | None] = mapped_column(Integer)
    asn: Mapped[int | None] = mapped_column(Integer)
    asn_org: Mapped[str | None] = mapped_column(String(255))
    is_hosting: Mapped[bool] = mapped_column(Boolean, default=False)
    """ASN org matched a hosting/VPN provider. Better credential-sharing signal
    than distance alone. See geo/lookup.py."""
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    looked_up_at: Mapped[datetime | None] = mapped_column()


class Library(Base):
    __tablename__ = "libraries"

    section_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    type: Mapped[str | None] = mapped_column(String(32))


class MediaItem(Base):
    """Metadata cache, one fetch per rating_key ever.

    guids arrive from get_metadata as ['imdb://tt…', 'tmdb://…', 'tvdb://…']
    and are split out here so deep links are string templates downstream.
    """

    __tablename__ = "media_items"

    rating_key: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_rating_key: Mapped[int | None] = mapped_column(Integer)
    grandparent_rating_key: Mapped[int | None] = mapped_column(Integer)
    section_id: Mapped[int | None] = mapped_column(Integer)
    media_type: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(Text)
    full_title: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    thumb: Mapped[str | None] = mapped_column(Text)
    art: Mapped[str | None] = mapped_column(Text)
    duration: Mapped[int | None] = mapped_column(Integer)
    content_rating: Mapped[str | None] = mapped_column(String(32))
    summary: Mapped[str | None] = mapped_column(Text)
    imdb_id: Mapped[str | None] = mapped_column(String(32))
    tmdb_id: Mapped[str | None] = mapped_column(String(32))
    tvdb_id: Mapped[str | None] = mapped_column(String(32))
    radarr_slug: Mapped[str | None] = mapped_column(String(255))
    sonarr_slug: Mapped[str | None] = mapped_column(String(255))
    synced_at: Mapped[datetime | None] = mapped_column()


class History(Base):
    __tablename__ = "history"
    __table_args__ = (
        Index("ix_history_started", "started"),
        Index("ix_history_user_started", "user_id", "started"),
        Index("ix_history_ip", "ip_address"),
        Index("ix_history_machine", "machine_id"),
        Index("ix_history_rating_key", "rating_key"),
        Index("ix_history_media_type", "media_type"),
    )

    row_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    reference_id: Mapped[int | None] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(Integer)
    machine_id: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(45))

    started: Mapped[int | None] = mapped_column(Integer)
    stopped: Mapped[int | None] = mapped_column(Integer)
    duration: Mapped[int | None] = mapped_column(Integer)
    play_duration: Mapped[int | None] = mapped_column(Integer)
    paused_counter: Mapped[int | None] = mapped_column(Integer)
    percent_complete: Mapped[int | None] = mapped_column(Integer)
    watched_status: Mapped[float | None] = mapped_column(Float)

    media_type: Mapped[str | None] = mapped_column(String(32))
    section_id: Mapped[int | None] = mapped_column(Integer)
    rating_key: Mapped[int | None] = mapped_column(Integer)
    parent_rating_key: Mapped[int | None] = mapped_column(Integer)
    grandparent_rating_key: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    full_title: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    thumb: Mapped[str | None] = mapped_column(Text)
    live: Mapped[bool] = mapped_column(Boolean, default=False)

    platform: Mapped[str | None] = mapped_column(String(255))
    player: Mapped[str | None] = mapped_column(String(255))
    product: Mapped[str | None] = mapped_column(String(255))
    transcode_decision: Mapped[str | None] = mapped_column(String(32))
    location: Mapped[str | None] = mapped_column(String(32))
    secure: Mapped[bool | None] = mapped_column(Boolean)
    relayed: Mapped[bool | None] = mapped_column(Boolean)


class Rule(Base):
    """A governance rule: match live sessions, then run an action.

    Every matcher is nullable and ANDed when set, so one table covers "block
    this device", "no transcodes", "no remote 4K" and "cap concurrent streams"
    without a schema per idea. machine_id is the device key because `player`
    is a user-editable name.
    """

    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    match_user_id: Mapped[int | None] = mapped_column(Integer)
    match_machine_id: Mapped[str | None] = mapped_column(String(255))
    match_player: Mapped[str | None] = mapped_column(String(255))
    match_platform: Mapped[str | None] = mapped_column(String(255))
    match_product: Mapped[str | None] = mapped_column(String(255))
    match_ip_cidr: Mapped[str | None] = mapped_column(String(64))
    match_transcode_decision: Mapped[str | None] = mapped_column(String(32))
    match_video_resolution: Mapped[str | None] = mapped_column(String(32))
    match_location: Mapped[str | None] = mapped_column(String(32))
    match_is_hosting: Mapped[bool | None] = mapped_column(Boolean)
    match_concurrent_streams_gt: Mapped[int | None] = mapped_column(Integer)
    match_paused_minutes_gt: Mapped[int | None] = mapped_column(Integer)

    action: Mapped[str] = mapped_column(String(32), default="terminate")
    message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime | None] = mapped_column()


class EnforcementLog(Base):
    """What the enforcer did, or would have done in dry run."""

    __tablename__ = "enforcement_log"
    __table_args__ = (Index("ix_enforcement_at", "acted_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(Integer)
    rule_name: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str | None] = mapped_column(String(32))
    session_key: Mapped[str | None] = mapped_column(String(64))
    user_id: Mapped[int | None] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(255))
    machine_id: Mapped[str | None] = mapped_column(String(255))
    player: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    full_title: Mapped[str | None] = mapped_column(Text)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    result: Mapped[str | None] = mapped_column(Text)
    acted_at: Mapped[datetime | None] = mapped_column()


class AppUser(Base):
    """Someone who can log in. Separate from `users`, which are Plex viewers."""

    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="viewer")
    password_hash: Mapped[str | None] = mapped_column(Text)
    """Null for accounts created by the reverse proxy, which never have a
    local password."""
    auth_source: Mapped[str] = mapped_column(String(16), default="local")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column()
    last_login: Mapped[datetime | None] = mapped_column()


class AppSession(Base):
    """A login session.

    Opaque random token, stored hashed. Keeping sessions in the database means
    logging someone out actually ends their access, which a stateless token
    cannot do without extra machinery.
    """

    __tablename__ = "app_sessions"
    __table_args__ = (Index("ix_sessions_user", "app_user_id"),)

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    app_user_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime | None] = mapped_column()
    expires_at: Mapped[datetime | None] = mapped_column()


class TravelFlag(Base):
    """Two plays by one account, too far apart to be the same person.

    The clearest sign of a shared password. Stored rather than recomputed so a
    flag can be reviewed and stay reviewed.
    """

    __tablename__ = "travel_flags"
    __table_args__ = (Index("ix_travel_user", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    from_history_id: Mapped[int] = mapped_column(Integer)
    to_history_id: Mapped[int] = mapped_column(Integer, unique=True)

    from_city: Mapped[str | None] = mapped_column(String(255))
    to_city: Mapped[str | None] = mapped_column(String(255))
    from_ip: Mapped[str | None] = mapped_column(String(45))
    to_ip: Mapped[str | None] = mapped_column(String(45))
    from_started: Mapped[int | None] = mapped_column(Integer)
    to_started: Mapped[int | None] = mapped_column(Integer)

    kind: Mapped[str] = mapped_column(String(16), default="travel")
    """`concurrent` when the two plays overlap in time, which is not travel at
    all but one account streaming from two places at once. `travel` when there
    is a real gap that is still too short for the distance."""

    km: Mapped[float | None] = mapped_column(Float)
    hours: Mapped[float | None] = mapped_column(Float)
    kmh: Mapped[float | None] = mapped_column(Float)
    """Meaningless for a concurrent pair, so it is left null rather than
    reported as a million kilometres an hour."""
    hosting_involved: Mapped[bool] = mapped_column(Boolean, default=False)
    """A VPN explains impossible travel without anyone sharing a password, so
    it is recorded and shown rather than being silently excluded."""

    status: Mapped[str] = mapped_column(String(16), default="new")
    created_at: Mapped[datetime | None] = mapped_column()

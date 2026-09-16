"""ORM models. Grows a table per phase.

Column set is what Tautulli's get_history actually returns (verified by
scripts/probe_source.py), plus section_id backfilled from get_metadata.
Deliberately absent: video_resolution, bandwidth, quality_profile. They need a
per-row get_stream_data call, and nothing needs them from history — rules read
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
    table — see settings_store.load().
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

    machine_id is Plex's clientIdentifier — stable across renames, which is why
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
    than distance alone — see geo/lookup.py."""
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

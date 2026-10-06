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

from sqlalchemy import BigInteger, Boolean, Float, Index, Integer, String, Text
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
    # Deleted from Tautulli's user list, which hides them from get_users, while
    # the Plex account may well still have access and still be streaming.
    deleted_in_tautulli: Mapped[bool | None] = mapped_column(Boolean)
    # Library section ids shared with them (JSON list), from Tautulli's
    # get_users, so access can be reviewed without a Plex token.
    shared_libraries: Mapped[str | None] = mapped_column(Text)
    allow_sync: Mapped[bool | None] = mapped_column(Boolean)


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
    trusted_at: Mapped[datetime | None] = mapped_column()
    """When somebody said this device belongs to this account.

    Set means trusted; the time is kept because a flag with no date cannot
    answer how long ago somebody decided, and the question of whether trust
    should go stale is open rather than settled.

    It quiets one thing and nothing else: a pair of plays is not raised as one
    account in two places when the device at each end is a trusted device of
    that account. Both ends, never one. A device somebody recognises playing
    alongside one they do not is exactly what sharing looks like, so trusting
    half a pair has to leave the signal standing."""

    trusted_by: Mapped[str | None] = mapped_column(String(255))
    """Who said so. A decision that quiets a signal is worth attributing."""


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
    # Thirty thousand rows and, until now, nothing but the primary key, so
    # every library page scanned the whole table to show sixty titles. Browse
    # filters on the library and the kind, Taking up room sorts by size, and
    # the problem-bitrate lists compare against a threshold; those are the
    # three. Measured on a library of this size: 34 ms to 0.8 ms.
    __table_args__ = (
        Index("ix_media_section_type", "section_id", "media_type"),
        # A show and a season have no row of their own, so their artwork and
        # their episode lists are found through these. Without them every
        # poster on a page of five hundred shows was a full scan of thirty
        # thousand rows: thirty two milliseconds each, sixteen seconds a page.
        Index("ix_media_grandparent", "grandparent_rating_key"),
        Index("ix_media_parent", "parent_rating_key"),
        Index("ix_media_type_size", "media_type", "file_size"),
        Index("ix_media_bitrate", "file_bitrate"),
    )

    rating_key: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_rating_key: Mapped[int | None] = mapped_column(Integer)
    grandparent_rating_key: Mapped[int | None] = mapped_column(Integer)
    section_id: Mapped[int | None] = mapped_column(Integer)
    media_type: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(Text)
    full_title: Mapped[str | None] = mapped_column(Text)
    grandparent_title: Mapped[str | None] = mapped_column(Text)
    parent_media_index: Mapped[int | None] = mapped_column(Integer)
    media_index: Mapped[int | None] = mapped_column(Integer)
    year: Mapped[int | None] = mapped_column(Integer)
    thumb: Mapped[str | None] = mapped_column(Text)
    """For an episode this is the episode still, a 16:9 screen grab, not a
    poster. Use poster_thumb when you want cover art."""

    grandparent_thumb: Mapped[str | None] = mapped_column(Text)
    """The show's poster, for episodes."""

    parent_thumb: Mapped[str | None] = mapped_column(Text)
    """The season's poster, for episodes."""

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

    # The file itself, for Library health: what it is, and so what a device
    # has to do to play it. The first version when there are several.
    file_bitrate: Mapped[int | None] = mapped_column(Integer)  # kbps, average
    file_container: Mapped[str | None] = mapped_column(String(16))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    file_path: Mapped[str | None] = mapped_column(Text)
    versions: Mapped[int | None] = mapped_column(Integer)
    video_codec: Mapped[str | None] = mapped_column(String(16))
    video_resolution: Mapped[str | None] = mapped_column(String(16))
    video_bit_depth: Mapped[int | None] = mapped_column(Integer)
    video_dynamic_range: Mapped[str | None] = mapped_column(String(32))
    audio_codec: Mapped[str | None] = mapped_column(String(16))
    audio_channels: Mapped[int | None] = mapped_column(Integer)
    # JSON lists. Always [{"codec", "channels", "language", "bitrate"}] and
    # [{"codec", "language", "forced", "location"}].
    #
    # A file read from Plex also carries, where Plex says so: on an audio
    # track layout, profile, sample_rate, bit_depth, default and title; on a
    # subtitle sdh, dub, original, default and title. Those keys are absent
    # rather than null when Plex did not say, which is how Plex itself answers
    # and keeps thirty thousand rows from storing a great many falses. A file
    # read through Tautulli has the four it always had.
    audio_tracks: Mapped[str | None] = mapped_column(Text)
    subtitle_tracks: Mapped[str | None] = mapped_column(Text)
    file_checked_at: Mapped[datetime | None] = mapped_column()
    library_seen_at: Mapped[datetime | None] = mapped_column()
    """When the library scan last found this in Plex. Older than the last scan
    means it has gone."""

    @property
    def poster_thumb(self) -> str | None:
        """Cover art, whatever the media type.

        An episode's own thumb is a still from the episode, which looks wrong
        stretched into a poster slot, so the show's poster is preferred and the
        season's is the fallback.
        """
        if self.media_type in ("episode", "season"):
            return self.grandparent_thumb or self.parent_thumb or self.thumb
        return self.thumb


class History(Base):
    __tablename__ = "history"
    __table_args__ = (
        Index("ix_history_started", "started"),
        Index("ix_history_user_started", "user_id", "started"),
        Index("ix_history_ip", "ip_address"),
        Index("ix_history_machine", "machine_id"),
        Index("ix_history_rating_key", "rating_key"),
        Index("ix_history_media_type", "media_type"),
        # A device's, an address's or a title's history is always newest
        # first, and the single column indexes above find the rows and then
        # leave SQLite to build a temporary B-tree to order them. Carrying
        # `started` in the index removes that.
        #
        # The single column ones stay: they are cheap at this size, they are
        # still the right index for a plain count, and dropping an index is
        # not something the schema helpers do.
        Index("ix_history_machine_started", "machine_id", "started"),
        Index("ix_history_ip_started", "ip_address", "started"),
        Index("ix_history_rating_started", "rating_key", "started"),
    )

    row_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    reference_id: Mapped[int | None] = mapped_column(Integer, index=True)
    """Tautulli groups a play that was paused and resumed under one reference
    id, and gives the group the newest row id. Only that row is kept."""
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
    # The show's name, and season and episode numbers, for S01E02 in titles.
    grandparent_title: Mapped[str | None] = mapped_column(Text)
    parent_media_index: Mapped[int | None] = mapped_column(Integer)
    media_index: Mapped[int | None] = mapped_column(Integer)
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

    trigger: Mapped[str] = mapped_column(String(16), default="stream")
    """What sets it off: a stream playing, a file crossing a threshold, an
    issue raised, a replacement finishing, or a person going quiet. Rules
    written before this existed are about streams, which is why that is the
    default."""

    daily_cap: Mapped[int | None] = mapped_column(Integer)
    """How many times a day this rule may act. Unset follows the global cap.
    A rule that can act while nobody is watching needs a ceiling."""

    action: Mapped[str] = mapped_column(String(32), default="terminate")
    message: Mapped[str | None] = mapped_column(Text)

    # JSON. The condition tree (services/conditions.py) and the list of
    # actions to run. When empty, the match_* columns and action above are
    # the rule, as saved before these existed, and are converted on read.
    conditions: Mapped[str | None] = mapped_column(Text)
    actions: Mapped[str | None] = mapped_column(Text)

    record_only: Mapped[bool | None] = mapped_column(Boolean)
    """Match and log, but do not act. Null on rules saved before the switch
    existed, which then follow the old global dry run setting."""

    created_at: Mapped[datetime | None] = mapped_column()


class StreamEvent(Base):
    """Something that happened during a stream, with how long it lasted.

    Only buffering so far. Recorded by services/tracker.py when an episode
    ends, with the stream's details at the time, so it can be counted in
    rules and reported on later.
    """

    __tablename__ = "stream_events"
    __table_args__ = (
        Index("ix_stream_events_started", "started_at"),
        Index("ix_stream_events_user", "user_id", "started_at"),
        Index("ix_stream_events_machine", "machine_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    session_key: Mapped[str | None] = mapped_column(String(64))
    user_id: Mapped[int | None] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(255))
    machine_id: Mapped[str | None] = mapped_column(String(255))
    player: Mapped[str | None] = mapped_column(String(255))
    platform: Mapped[str | None] = mapped_column(String(64))
    product: Mapped[str | None] = mapped_column(String(128))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    location: Mapped[str | None] = mapped_column(String(8))
    rating_key: Mapped[int | None] = mapped_column(Integer)
    full_title: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(String(16))
    transcode_decision: Mapped[str | None] = mapped_column(String(32))
    video_resolution: Mapped[str | None] = mapped_column(String(16))
    quality_profile: Mapped[str | None] = mapped_column(String(64))
    bandwidth: Mapped[int | None] = mapped_column(Integer)
    stream_bitrate: Mapped[int | None] = mapped_column(Integer)
    progress_percent: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column()
    ended_at: Mapped[datetime | None] = mapped_column()
    seconds: Mapped[float | None] = mapped_column(Float)
    # Likely cause, from services/stalls.py, and why.
    cause: Mapped[str | None] = mapped_column(String(16))
    cause_detail: Mapped[str | None] = mapped_column(Text)


class StreamSession(Base):
    """One stream as live activity saw it, from services/streams.py.

    Decisions are the worst seen during the stream, causes every reason it
    was not a plain direct play. Only streams seen while Cartographarr was
    running are here.
    """

    __tablename__ = "stream_sessions"
    __table_args__ = (
        Index("ix_stream_sessions_started", "started_at"),
        Index("ix_stream_sessions_user", "user_id", "started_at"),
        Index("ix_stream_sessions_rating_key", "rating_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_key: Mapped[str | None] = mapped_column(String(64))
    user_id: Mapped[int | None] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(255))
    machine_id: Mapped[str | None] = mapped_column(String(255))
    player: Mapped[str | None] = mapped_column(String(255))
    platform: Mapped[str | None] = mapped_column(String(64))
    product: Mapped[str | None] = mapped_column(String(128))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    location: Mapped[str | None] = mapped_column(String(8))
    relayed: Mapped[bool | None] = mapped_column(Boolean)
    secure: Mapped[bool | None] = mapped_column(Boolean)
    rating_key: Mapped[int | None] = mapped_column(Integer)
    grandparent_rating_key: Mapped[int | None] = mapped_column(Integer)
    full_title: Mapped[str | None] = mapped_column(Text)
    grandparent_title: Mapped[str | None] = mapped_column(Text)
    parent_media_index: Mapped[int | None] = mapped_column(Integer)
    media_index: Mapped[int | None] = mapped_column(Integer)
    media_type: Mapped[str | None] = mapped_column(String(16))
    quality_profile: Mapped[str | None] = mapped_column(String(64))
    file_bitrate: Mapped[int | None] = mapped_column(Integer)
    video_codec: Mapped[str | None] = mapped_column(String(16))
    video_resolution: Mapped[str | None] = mapped_column(String(16))
    video_bit_depth: Mapped[int | None] = mapped_column(Integer)
    video_dynamic_range: Mapped[str | None] = mapped_column(String(32))
    audio_codec: Mapped[str | None] = mapped_column(String(16))
    subtitle_codec: Mapped[str | None] = mapped_column(String(16))
    stream_bitrate: Mapped[int | None] = mapped_column(Integer)
    stream_video_codec: Mapped[str | None] = mapped_column(String(16))
    stream_video_resolution: Mapped[str | None] = mapped_column(String(16))
    stream_audio_codec: Mapped[str | None] = mapped_column(String(16))
    transcode_decision: Mapped[str | None] = mapped_column(String(32))
    video_decision: Mapped[str | None] = mapped_column(String(32))
    audio_decision: Mapped[str | None] = mapped_column(String(32))
    subtitle_decision: Mapped[str | None] = mapped_column(String(32))
    container_decision: Mapped[str | None] = mapped_column(String(32))
    transcode_hw: Mapped[bool | None] = mapped_column(Boolean)

    # Detail only Plex reports, so these stay empty on a stream recorded
    # through Tautulli rather than being wrong.
    #
    # The hardware pair is the useful one. Plex says separately whether
    # hardware was asked for and whether it was actually used, and asked for
    # but not granted is the case somebody wants explained. Nothing could say
    # it before: a server doing no hardware transcoding at all looked the same
    # as one never asked.
    transcode_hw_requested: Mapped[bool | None] = mapped_column(Boolean)
    transcode_hw_decode: Mapped[bool | None] = mapped_column(Boolean)
    transcode_hw_encode: Mapped[bool | None] = mapped_column(Boolean)
    transcode_protocol: Mapped[str | None] = mapped_column(String(16))
    video_profile: Mapped[str | None] = mapped_column(String(32))
    video_frame_rate: Mapped[str | None] = mapped_column(String(16))
    audio_channels: Mapped[int | None] = mapped_column(Integer)
    # Which track was actually being played and read, rather than which the
    # file happens to contain.
    audio_language: Mapped[str | None] = mapped_column(String(64))
    subtitle_language: Mapped[str | None] = mapped_column(String(64))
    transcode_speed_min: Mapped[float | None] = mapped_column(Float)
    causes: Mapped[str | None] = mapped_column(String(255))
    primary_cause: Mapped[str | None] = mapped_column(String(32))
    bandwidth_max: Mapped[int | None] = mapped_column(Integer)
    progress_start: Mapped[int | None] = mapped_column(Integer)
    progress_end: Mapped[int | None] = mapped_column(Integer)
    buffer_count: Mapped[int | None] = mapped_column(Integer)
    buffer_seconds: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[datetime | None] = mapped_column()
    last_seen_at: Mapped[datetime | None] = mapped_column()
    ended_at: Mapped[datetime | None] = mapped_column()


class BandwidthSample(Base):
    """The busiest moment of one minute: upload, streams and transcodes."""

    __tablename__ = "bandwidth_samples"

    minute: Mapped[int] = mapped_column(Integer, primary_key=True)  # unix time, start of the minute
    wan_kbps: Mapped[int | None] = mapped_column(Integer)
    lan_kbps: Mapped[int | None] = mapped_column(Integer)
    streams: Mapped[int | None] = mapped_column(Integer)
    remote_streams: Mapped[int | None] = mapped_column(Integer)
    transcodes: Mapped[int | None] = mapped_column(Integer)
    hw_transcodes: Mapped[int | None] = mapped_column(Integer)


class BannedDevice(Base):
    """A device that may not stream.

    One list rather than a rule per device: the enforcer treats the whole list
    as a single built-in rule that runs before the others. The label and owner
    are copied at ban time, so the list still reads sensibly if the device is
    renamed or its history ages out.
    """

    __tablename__ = "banned_devices"

    machine_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    label: Mapped[str | None] = mapped_column(String(255))
    user_id: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    banned_by: Mapped[str | None] = mapped_column(String(64))
    banned_at: Mapped[datetime | None] = mapped_column()
    # Empty for a permanent ban. After this the ban no longer applies and is
    # removed on the next sweep, with a Log entry.
    expires_at: Mapped[datetime | None] = mapped_column()


class BannedAddress(Base):
    """An address, or a range of them, that may not stream.

    A device ban follows one machine. An address ban follows the connection,
    which is what you want when a device comes back under a new identifier,
    or when a whole household is the thing being stopped rather than one box
    in it. Stored as typed: a plain address or a CIDR, matched as a network
    either way.

    Same shape as BannedDevice on purpose, down to the expiry, because the
    enforcer treats both as built-in rules and nothing else should have to
    know which kind it is looking at.
    """

    __tablename__ = "banned_addresses"

    address: Mapped[str] = mapped_column(String(64), primary_key=True)
    """An IP address or a CIDR range, as it was typed."""
    label: Mapped[str | None] = mapped_column(String(255))
    """Where it was when banned, copied at ban time so the list still reads
    sensibly after the address moves on or its history ages out."""
    user_id: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    banned_by: Mapped[str | None] = mapped_column(String(64))
    banned_at: Mapped[datetime | None] = mapped_column()
    expires_at: Mapped[datetime | None] = mapped_column()


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

    trigger: Mapped[str | None] = mapped_column(String(16))
    """What set the rule off: a stream, a file, a report, a replacement, a
    person. Null on entries from before rules could be about anything else."""

    subject: Mapped[str | None] = mapped_column(String(64))
    """Which one of those it was, for the cooldown that stops the same file
    setting the same rule off every ten minutes."""

    # A snapshot of the stream as it was when acted on. Copied rather than
    # joined, because the session is gone a moment later and history may not
    # record a stream that was stopped seconds in.
    source: Mapped[str | None] = mapped_column(String(16))  # "rule" or "manual"
    actor: Mapped[str | None] = mapped_column(String(255))  # who pressed it, or the rule
    message: Mapped[str | None] = mapped_column(Text)
    platform: Mapped[str | None] = mapped_column(String(64))
    product: Mapped[str | None] = mapped_column(String(128))
    media_type: Mapped[str | None] = mapped_column(String(16))
    rating_key: Mapped[int | None] = mapped_column(Integer)
    grandparent_rating_key: Mapped[int | None] = mapped_column(Integer)
    grandparent_title: Mapped[str | None] = mapped_column(Text)
    parent_media_index: Mapped[int | None] = mapped_column(Integer)
    media_index: Mapped[int | None] = mapped_column(Integer)
    library_name: Mapped[str | None] = mapped_column(String(255))
    year: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str | None] = mapped_column(String(16))
    progress_percent: Mapped[int | None] = mapped_column(Integer)
    view_offset: Mapped[int | None] = mapped_column(Integer)  # ms
    duration: Mapped[int | None] = mapped_column(Integer)  # ms
    transcode_decision: Mapped[str | None] = mapped_column(String(32))
    video_resolution: Mapped[str | None] = mapped_column(String(16))
    quality_profile: Mapped[str | None] = mapped_column(String(64))
    bandwidth: Mapped[int | None] = mapped_column(Integer)  # kbps
    location: Mapped[str | None] = mapped_column(String(8))  # lan or wan
    city: Mapped[str | None] = mapped_column(String(255))
    region: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(255))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    is_hosting: Mapped[bool | None] = mapped_column(Boolean)
    asn_org: Mapped[str | None] = mapped_column(String(255))


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
    plex_user_id: Mapped[int | None] = mapped_column(Integer)
    """Which Plex user this person is, for viewer privacy. Set by an admin, or
    left empty to match by email or username."""
    privacy: Mapped[str | None] = mapped_column(String(16))
    """What this viewer may see: all, own or anonymised. Empty follows the
    viewer privacy setting. Accounts made by Plex sign-in start anonymised."""


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

    # Where each end was, as a place an ignore pattern can name: the network
    # for a VPN, since a VPN exit moves between cities, and the city otherwise.
    from_key: Mapped[str | None] = mapped_column(String(255))
    to_key: Mapped[str | None] = mapped_column(String(255))
    ignore_id: Mapped[int | None] = mapped_column(Integer)
    """Set when an ignore pattern closed this flag, rather than a person."""


class LibrarySize(Base):
    """What a library held, once a day.

    Space used is a sum of the files and can be worked out any time. Space
    gained or lost cannot: nothing anywhere records when a file arrived, and
    the library scan overwrites what it finds. So the only way to know whether
    a library grew this week is to have written down what it was last week,
    which is what this is.

    One row per library per day, written by the scan and overwritten by each
    later scan the same day. Thirty rows a year per library; it never needs
    pruning.
    """

    __tablename__ = "library_sizes"
    __table_args__ = (Index("ix_library_size_day", "section_id", "on_day", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section_id: Mapped[int] = mapped_column(Integer)
    on_day: Mapped[str] = mapped_column(String(10))
    """The server's own date, as YYYY-MM-DD, because that is the day somebody
    means when they ask what it was a week ago."""

    files: Mapped[int] = mapped_column(Integer, default=0)
    bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    at: Mapped[datetime | None] = mapped_column()


class Replacement(Base):
    """A file being replaced through Radarr or Sonarr, from the release chosen
    to the import confirmed or denied. See services/replacements.py."""

    __tablename__ = "replacements"
    __table_args__ = (Index("ix_replacements_status", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rating_key: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    service: Mapped[str] = mapped_column(String(16))  # radarr or sonarr
    arr_id: Mapped[int | None] = mapped_column(Integer)  # movie or series id
    episode_id: Mapped[int | None] = mapped_column(Integer)
    guid: Mapped[str | None] = mapped_column(Text)
    indexer_id: Mapped[int | None] = mapped_column(Integer)
    # queued, downloading, ready, importing, imported, imported_automatically, denied, failed
    status: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[float | None] = mapped_column(Float)
    download_id: Mapped[str | None] = mapped_column(String(128))
    queue_id: Mapped[int | None] = mapped_column(Integer)
    release: Mapped[str | None] = mapped_column(Text)  # JSON, the release as compared when chosen
    current: Mapped[str | None] = mapped_column(Text)  # JSON, the file it replaces
    candidate: Mapped[str | None] = mapped_column(Text)  # JSON, the downloaded file, then the imported one
    message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(64))
    resolved_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime | None] = mapped_column()
    updated_at: Mapped[datetime | None] = mapped_column()
    checked_at: Mapped[datetime | None] = mapped_column()


class TaskRun(Base):
    """One run of a background task, for Settings, Tasks. See app/tasks.py."""

    __tablename__ = "task_runs"
    __table_args__ = (Index("ix_task_runs_task", "task", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime | None] = mapped_column()
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))  # ok, failed, skipped
    message: Mapped[str | None] = mapped_column(Text)
    trigger: Mapped[str | None] = mapped_column(String(16))  # schedule, manual, startup


class SavedReport(Base):
    """A report someone saved from the Reports tab. The spec is what the
    builder sends: source, measure, group, split, range and filters."""

    __tablename__ = "saved_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    spec: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime | None] = mapped_column()
    updated_at: Mapped[datetime | None] = mapped_column()


class SignalIgnore(Base):
    """A sharing signal that is expected for one person.

    A second home, a phone on mobile data, a VPN they always use. Matches the
    same user moving between the same two places in either direction, and
    closes those signals as they are found, past and future.
    """

    __tablename__ = "signal_ignores"
    __table_args__ = (Index("ix_signal_ignore_user", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    key_a: Mapped[str] = mapped_column(String(255))
    key_b: Mapped[str] = mapped_column(String(255))
    label: Mapped[str | None] = mapped_column(String(255))
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime | None] = mapped_column()


class AuditLog(Base):
    """Every change someone made through the app, and every sign in.

    Sharing changes cannot be undone from here, so what something looked like
    before is worth keeping even when the change went fine.
    """

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_user_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column()
    # Copied rather than joined: an account can be deleted, and the log should
    # still say who did it.
    actor: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[str | None] = mapped_column(Text)


class Issue(Base):
    """Something wrong with a file, as reported by a person.

    Read from Seerr where it is set up, and kept here as well, so the report
    sits next to what this app knows: the file's tracks and bitrate, who played
    it on what, whether it transcoded, and whether it stalled while they
    watched. See services/issues.py.
    """

    __tablename__ = "issues"
    __table_args__ = (Index("ix_issues_status", "status"), Index("ix_issues_rating_key", "rating_key"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(16), default="seerr")
    seerr_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    issue_type: Mapped[str] = mapped_column(String(16), default="other")
    """video, audio, subtitles or other."""
    status: Mapped[str] = mapped_column(String(16), default="open")
    message: Mapped[str | None] = mapped_column(Text)

    media_type: Mapped[str | None] = mapped_column(String(16))
    tmdb_id: Mapped[int | None] = mapped_column(Integer)
    tvdb_id: Mapped[int | None] = mapped_column(Integer)
    rating_key: Mapped[int | None] = mapped_column(Integer)
    """The episode where one is named, otherwise the movie or the show."""
    show_rating_key: Mapped[int | None] = mapped_column(Integer)
    season: Mapped[int | None] = mapped_column(Integer)
    episode: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)

    reporter_name: Mapped[str | None] = mapped_column(String(255))
    reporter_user_id: Mapped[int | None] = mapped_column(Integer)
    """Plex user id, where the reporter could be matched to someone here."""
    comments: Mapped[str | None] = mapped_column(Text)
    """JSON: [{"message", "author", "created_at"}], oldest first."""

    context: Mapped[str | None] = mapped_column(Text)
    """JSON: the play this was reported from, recorded as it was at the time.
    Device, when, whether it transcoded, and any stalls during it. A report
    that carries its own evidence beats one that says "it looked bad"."""

    created_at: Mapped[datetime | None] = mapped_column()
    updated_at: Mapped[datetime | None] = mapped_column()
    synced_at: Mapped[datetime | None] = mapped_column()


class BlockedCountry(Base):
    """A country whose streams are flagged, warned or stopped.

    The same idea as the ban list, by place rather than by device. Each entry
    says what should happen, so somewhere worth watching can be flagged without
    cutting anyone off. See services/enforcer.py, country_rules().
    """

    __tablename__ = "blocked_countries"

    code: Mapped[str] = mapped_column(String(2), primary_key=True)
    """Two letter country code, as GeoIP reports it."""
    name: Mapped[str | None] = mapped_column(String(128))
    mode: Mapped[str] = mapped_column(String(8), default="flag")
    """flag, warn or stop."""
    vpn_mode: Mapped[str | None] = mapped_column(String(8))
    """What to do instead when the address is a VPN or hosting provider.
    Unset means the same as mode. "ignore" means leave those streams alone,
    which is the answer where a country only ever appears as a VPN exit."""
    reason: Mapped[str | None] = mapped_column(Text)
    blocked_by: Mapped[str | None] = mapped_column(String(64))
    blocked_at: Mapped[datetime | None] = mapped_column()


class HomeLink(Base):
    """A link on the home page, and who sees it.

    Links for the services that are set up are worked out from the settings, so
    a fresh install has a useful home page with nothing to configure. A row
    here only records what someone changed about one: a different name, a
    different audience, hidden, moved, or a link of their own. See
    services/home.py.
    """

    __tablename__ = "home_links"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    """plex, seerr, radarr and so on for the built in ones, custom:N for the rest."""
    label: Mapped[str | None] = mapped_column(String(64))
    url: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(String(32))
    roles: Mapped[str] = mapped_column(String(16), default="all")
    """all, admin or viewer."""
    position: Mapped[int] = mapped_column(Integer, default=0)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    custom: Mapped[bool] = mapped_column(Boolean, default=False)


class LibraryStore(Base):
    """A name for one storage mount, so several mounts on one box read as one.

    Only names live here. Which mounts exist is worked out from the file paths
    each time. See services/stores.py.
    """

    __tablename__ = "library_stores"

    prefix: Mapped[str] = mapped_column(String(255), primary_key=True)
    label: Mapped[str | None] = mapped_column(String(64))


class KeepDecision(Base):
    """A file somebody looked at and decided to keep.

    The deletion review is meant to be the things nobody has thought about yet,
    so a decision has to stick. Nothing here deletes anything: Plex, Radarr and
    Sonarr own the files. See services/cleanup.py.
    """

    __tablename__ = "keep_decisions"

    rating_key: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    reason: Mapped[str | None] = mapped_column(Text)
    kept_by: Mapped[str | None] = mapped_column(String(64))
    kept_at: Mapped[datetime | None] = mapped_column()


class MediaJob(Base):
    """One run of ffmpeg over one file, and what came of it.

    Kept because these take minutes and nobody watches them: the page is shut,
    the job carries on, and what happened is readable afterwards. The plan is
    stored with the job so a finished one still says what it did, even after
    the file has been read again and no longer needs it.
    """

    __tablename__ = "media_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rating_key: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str | None] = mapped_column(String(512))
    path: Mapped[str | None] = mapped_column(Text)
    steps: Mapped[str | None] = mapped_column(Text)
    """The step keys asked for, as JSON, and the words shown with them."""
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    """queued, running, done, failed, cancelled."""
    progress: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str | None] = mapped_column(Text)
    """The last thing worth saying: what it is doing, or why it stopped."""
    saved_bytes: Mapped[int | None] = mapped_column(BigInteger)
    asked_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime | None] = mapped_column(index=True)
    finished_at: Mapped[datetime | None] = mapped_column()

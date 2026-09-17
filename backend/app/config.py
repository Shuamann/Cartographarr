"""Settings, from environment / .env.

Only what the current phases use. Plex, enforcement, auth and integration
settings arrive with the phases that need them. Config for a feature that
doesn't exist yet is just churn.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_name: str = "Cartographarr"
    log_level: str = "INFO"

    data_dir: Path = Path("/data")
    """Writable volume: cartographarr.db, the mmdb files, and any Tautulli DB
    snapshot the source_db fallback takes."""

    # ---- Tautulli (required) ----------------------------------------------
    tautulli_url: str = ""
    """Remote / fallback URL. Always reachable, used when the LAN one isn't."""

    tautulli_local_url: str = ""
    """Optional LAN address. Preferred when set and actually reachable, so the
    container talks to Tautulli directly instead of out and back through the
    reverse proxy. Falls back to tautulli_url on any failure."""

    tautulli_local_timeout: float = 3.0
    """Short, because this is a reachability probe, not a real request."""

    tautulli_api_key: str = ""
    tautulli_verify_ssl: bool = True
    tautulli_timeout: float = 30.0

    plex_token: str = ""
    """Server owner's Plex token. Only needed for sharing: everything else
    goes through Tautulli. Find it in any Plex XML request, or in Tautulli's
    settings."""

    plex_machine_identifier: str = ""
    """Server id for app.plex.tv deep links. Optional; without it the Plex
    button just isn't rendered."""

    source_mode: Literal["auto", "api", "db"] = "auto"
    """auto = probe get_history for machine_id at startup and pick. See
    scripts/probe_source.py."""

    tautulli_db_path: Path | None = None
    """Only used if the probe forces the db fallback. Points at a read-only
    bind-mount of Tautulli's config dir. Tautulli runs SQLite in WAL mode, so
    the DB gets snapshotted to data_dir and the *copy* opened read-write;
    opening the original read-only fails with CANTOPEN (error 14)."""

    # ---- Sync --------------------------------------------------------------
    sync_interval_minutes: int = 5
    sync_page_size: int = 1000
    metadata_concurrency: int = 4
    slow_sync_interval_minutes: int = 60
    """Users and libraries change rarely; own slower schedule."""

    # ---- Live activity + enforcement --------------------------------------
    activity_poll_seconds: int = 5

    enforce_enabled: bool = True
    enforce_dry_run: bool = True
    """No longer set in the UI: each rule, and the ban list, has its own record
    only switch on the Rules page. Two jobs remain. It is the starting value
    for rules saved before that switch existed. And set as an environment
    variable to true, it is a safety lock forcing every rule to record only."""

    enforce_cooldown_seconds: int = 60
    """Per rule, per session, to stop a stubborn client from filling the log."""

    upload_capacity_mbps: float = 0
    """Your server's upload speed. Lets stalls be blamed on a full upload, and
    lets Cartographarr warn when it is nearly full. 0 means unknown."""

    library_bitrate_threshold_mbps: float = 20
    """Library health lists files above this average bitrate that are watched
    remotely. Set it near what one remote stream can comfortably use."""

    upload_alert_percent: int = 90
    """Notify when remote streams use this much of the upload. 0 turns the
    warning off. Needs the upload capacity set."""

    ban_message: str = "This device is not permitted to stream. Contact the server owner."
    """Shown to a banned device when its stream is stopped."""

    ban_record_only: bool | None = None
    """The ban list's own record only switch. Unset means it follows the old
    global dry run setting, so upgrading changes nothing until someone chooses."""

    # ---- Integrations ------------------------------------------------------
    # Each app has two addresses. The URL is the one Cartographarr calls, best
    # a local address inside the network. The public URL is where the buttons
    # send a person's browser, which is usually the reverse proxy address;
    # left empty, buttons use the URL.
    radarr_url: str = ""
    radarr_public_url: str = ""
    radarr_api_key: str = ""
    sonarr_url: str = ""
    sonarr_public_url: str = ""
    sonarr_api_key: str = ""

    tmdb_api_key: str = ""
    """Free TMDB key. Used for the sign-in backdrop, and nothing else yet."""

    uptime_kuma_push_url: str = ""
    """Pinged after every successful sync. Monitors the sync being alive rather
    than the container being up, which is the thing that actually breaks."""

    seerr_url: str = ""
    seerr_public_url: str = ""
    seerr_api_key: str = ""
    """Seerr, the project Overseerr and Jellyseerr merged into. An older
    Overseerr instance should work too, the API shape is inherited."""

    metrics_token: str = ""
    """Turns on /metrics (Prometheus) and /api/summary (Homepage, Homarr), and
    is the token they must be sent with. Empty leaves both switched off. They
    carry counts only, never names, addresses or titles."""

    apprise_urls: str = ""
    """Where notifications go. One Apprise URL per line or comma separated, so
    one setting covers Discord, ntfy, Gotify, Pushover, Telegram, email and the
    hundred or so others Apprise speaks."""

    webhook_url: str = ""
    """Posted a JSON body when a rule says to. The escape hatch for anything
    Apprise does not cover."""

    # ---- Impossible travel -------------------------------------------------
    impossible_kmh: float = 900.0
    """Faster than a commercial flight, so not one person moving."""

    impossible_min_km: float = 100.0
    """Below this, city centroid error alone can manufacture a flag."""

    impossible_max_accuracy_km: float = 200.0
    """Skip pairs where the location is too vague to draw a conclusion from."""

    # ---- Auth --------------------------------------------------------------
    session_ttl_hours: int = 720
    session_cookie_name: str = "cartographarr_session"
    session_cookie_secure: bool = False
    """Set true once served over HTTPS. Left false by default because a LAN
    install on plain http would otherwise never receive the cookie."""

    viewer_privacy: str = "all"
    """What viewer accounts can see: `all` of the server, only their `own`
    data, or everything with other people `anonymised`. Admins see all."""

    auth_proxy_enabled: bool = False
    """Trust an authenticating reverse proxy (Authelia, Authentik, Cloudflare
    Access). Off until you have one in front, or anyone could send the header."""

    proxy_user_header: str = "X-Forwarded-User"
    proxy_email_header: str = "X-Forwarded-Email"

    trusted_proxy_ips: list[str] = []
    """Addresses or CIDRs allowed to send the proxy auth header. Empty means
    nothing is trusted, so proxy auth stays off however it is configured."""

    proxy_default_role: Literal["admin", "viewer"] = "viewer"
    """Role given to someone the proxy vouches for who has no account yet."""

    # ---- GeoIP -------------------------------------------------------------
    maxmind_account_id: str = ""
    maxmind_license_key: str = ""
    geoip_auto_update: bool = True
    geoip_update_interval_days: int = 7

    @field_validator("trusted_proxy_ips", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        # Env vars arrive as a single string; a comma separated list is what
        # anyone would type into an Unraid template.
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cartographarr.db"

    @property
    def geoip_dir(self) -> Path:
        return self.data_dir / "geoip"

    @property
    def snapshot_dir(self) -> Path:
        return self.data_dir / "snapshot"

    def require_tautulli(self) -> None:
        missing = [
            name
            for name, value in (
                ("TAUTULLI_URL", self.tautulli_url),
                ("TAUTULLI_API_KEY", self.tautulli_api_key),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                f"Missing required settings: {', '.join(missing)}. "
                "Copy .env.example to .env and fill them in."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()

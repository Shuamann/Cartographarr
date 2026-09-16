"""Settings, from environment / .env.

Only what the current phases use. Plex, enforcement, auth and integration
settings arrive with the phases that need them — config for a feature that
doesn't exist yet is just churn.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    """Short — this is a reachability probe, not a real request."""

    tautulli_api_key: str = ""
    tautulli_verify_ssl: bool = True
    tautulli_timeout: float = 30.0

    plex_machine_identifier: str = ""
    """Server id for app.plex.tv deep links. Optional — without it the Plex
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
    """Ships ON. Rules log what they *would* have done without doing it.
    Turning this off is a deliberate act after reading the enforcement log."""

    enforce_cooldown_seconds: int = 60
    """Per rule, per session — stops a stubborn client from filling the log."""

    # ---- GeoIP -------------------------------------------------------------
    maxmind_account_id: str = ""
    maxmind_license_key: str = ""
    geoip_auto_update: bool = True
    geoip_update_interval_days: int = 7

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

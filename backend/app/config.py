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

THEME_PARTS = ("bg", "surface", "bar", "ink")
"""What a person chooses: the page, the panels and menus, the top bar, the
text. Everything else the interface needs (raised surfaces, borders, quieter
inks) is worked out from these in the browser."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_name: str = "Cartographarr"
    accent_color: str = ""
    """The one colour the app is built around, as #rrggbb. Empty means the
    colour it ships with. Everything else is worked out from it, light and dark
    alike, including the map."""

    theme_colors: str = ""
    """The page, the panels, the top bar and the text, per theme, as JSON:

        {"dark": {"bg": "#0b0b0d", "surface": "#141417", "bar": "#0f0f11", "ink": "#eaeaea"}}

    Empty means the colours it ships with. Only these four are asked for; the
    raised surfaces, borders and quieter inks are worked out from them, which
    is the difference between choosing a scheme and filling in a form."""

    preferred_audio_language: str = ""
    """Three letter code, as the tracks are tagged: eng, spa, jpn. Set it and
    tidying can put that language first on a file that has several, so a
    television stops picking the commentary. Empty leaves the order alone."""

    keep_subtitle_languages: str = ""
    """Subtitle languages worth keeping, comma separated, as three letter
    codes. Empty keeps every one. Twenty tracks in languages nobody in the
    house reads is a menu to scroll past, and Plex reads the whole list before
    a stream starts."""

    keep_audio_languages: str = ""
    """Audio languages worth keeping, comma separated. Empty keeps every one,
    and a file that would be left silent keeps everything whatever this says."""

    tidy_when_quiet: bool = True
    """Hold tidying jobs back while anybody is watching.

    Tidying reads and rewrites a whole film: minutes of the array's attention,
    for a file nobody is waiting on. Doing that at eight in the evening while
    four people stream from the same disks is the one piece of work this app
    does that can be felt by somebody else.

    So a queued job waits for the streams to stop. Queue twenty files at
    teatime and they are done by morning without anyone having thought about
    when. Turn it off to have them run the moment they are asked for."""

    media_roots: str = ""
    """Where the media is mounted inside this container, as one path per entry.

    Mounting a share per library means a flag per library and a field per
    library. Mounting the parent instead means one, and this says where to
    look: for a file Plex calls `/movies/A Film/a.mkv`, every root given here
    is tried with the whole path hung off it and again with the library name
    dropped, and whichever answers is remembered for the rest of that library.

    More than one, because a library is often split across two shares or two
    pools. media_path_map still wins where a name cannot be guessed."""

    media_path_map: str = ""
    """How the paths Plex reports line up with this container's mounts, as
    `plex=here` pairs separated by commas. Empty, which is the normal case,
    means they are the same: mount the shares where Plex already has them and
    there is nothing to set. Only needed when they differ, for example
    `/media/movies=/movies`."""

    log_level: str = "INFO"

    # ---- Updates -----------------------------------------------------------
    update_check_enabled: bool = True
    """Ask GitHub twice a day whether a newer version is out. Nothing about
    this install is sent."""

    update_repository: str = "Shuamann/Cartographarr"
    """Where updates come from, as owner/name."""

    update_github_token: str = ""
    """Only needed while the repository is private: a token that can read it."""

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

    plex_url: str = ""
    """The address of the Plex server, for talking to it directly.

    Stored rather than discovered. Asking plexapi to find the server takes
    twenty seconds, because it tries every address Plex advertises, including
    a docker bridge and a LAN address unreachable from outside the house, and
    waits out each one. Connecting to a known address takes a fifth of a
    second. Settings finds it once and writes it here."""

    activity_source: str = "tautulli"
    """Where live activity is read from: tautulli or plex.

    Plex answers this directly in nine milliseconds, with the viewer's address,
    whether they are local, relayed or secure, the device, the player and the
    account, which is everything recorded about a stream. Tautulli remains the
    default until somebody chooses otherwise."""

    library_source: str = "tautulli"
    """Where the library is read from: tautulli or plex.

    Plex gives the file path, size, codecs, bitrate, duration and the IMDb,
    TMDB and TVDB ids in one pass, at about half a millisecond an item, which
    is more than Tautulli reports and one hop fewer."""

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

    run_background_jobs: bool = True
    """Whether to start the scheduler and probe the server at boot.

    False gives the app without any of its background work: no scheduler, no
    syncs, no capability probe. Every page still answers from what is already
    in the database. Meant for a second instance kept for reading, and for the
    test suite, which otherwise paid for a scheduler and a failed network call
    in every one of five hundred tests."""

    enforce_enabled: bool = True
    """The rules somebody wrote, and only those.

    The ban list and the blocked countries are enforced by the same sweep but
    are not rules: each is an explicit act against a named device, address or
    place. Turning this off to quieten one rule should not quietly stop every
    ban on the server, which it did."""

    enforce_dry_run: bool = True
    """No longer set in the UI: each rule, and the ban list, has its own record
    only switch on the Rules page. Two jobs remain. It is the starting value
    for rules saved before that switch existed. And set as an environment
    variable to true, it is a safety lock forcing every rule to record only."""

    automation_daily_cap: int = 20
    """How many times a rule that runs on its own may act in a day, unless the
    rule sets its own. A rule that fires while nobody is watching needs a
    ceiling, or one bad afternoon becomes a thousand."""

    automation_download_cap: int = 3
    """How many replacements every rule together may queue in a day. Spending
    bandwidth is the one thing worth a second, tighter limit."""

    enforce_cooldown_seconds: int = 60
    """Per rule, per session, to stop a stubborn client from filling the log."""

    upload_capacity_mbps: float = 0
    """Your server's upload speed. Lets stalls be blamed on a full upload, and
    lets Cartographarr warn when it is nearly full. 0 uses the Internet upload
    speed set in Plex (Settings, Remote Access), read every hour."""

    library_store_depth: int = 1
    """How much of a file path names its storage. Plex usually reports a mount
    per library, so one part (/movies, /tv) is right. Raise it where several
    libraries share a mount (/mnt/user/movies, /mnt/user/tv)."""

    poster_cache: bool = True
    """Keep the posters and backdrops the app shows on disk, at a modest size.

    Each is fetched once at one of three sizes, small enough to stay quick
    and large enough to stay sharp where it is shown, and served from disk
    afterwards. Off, every picture is fetched from Plex or Tautulli each time
    the browser does not already have it."""

    poster_cache_dir: str = ""
    """Where the kept posters live. Empty keeps them in the data directory,
    under posters. In a container this is a path inside it, such as /posters,
    mapped to wherever on the host suits: a fast cache pool, say, rather than
    the array. A folder that does not exist is not created, because inside a
    container that would be a folder lost on the next update; the data
    directory is used instead, and Settings says so."""

    library_bitrate_threshold_mbps: float = 20
    """Library health lists files above this average bitrate that are watched
    remotely. Set it near what one remote stream can comfortably use."""

    access_inactive_days: int = 90
    """Access review marks someone inactive after this many days without a
    play."""

    upload_alert_percent: int = 90
    """Notify when remote streams use this much of the upload. 0 turns the
    warning off. Needs the upload capacity set."""

    ban_message: str = "This device is not permitted to stream. Contact the server owner."
    """Shown to a banned device when its stream is stopped."""

    ban_record_only: bool | None = None

    address_ban_message: str = ""
    """Shown when a stream is stopped for its address rather than its device.

    Empty, which is the default, uses ban_message, because the two usually
    want the same wording. Set it where they do not: a device ban is aimed at
    one box and a household can reasonably be told something else."""

    geo_block_message: str = "Streaming is not permitted from this location. Contact the server owner."
    """Shown to a viewer whose country is set to warn or stop."""

    geo_block_allow_list: bool = False
    """Turn the country list around: anything NOT listed is flagged instead.
    For a server meant to be watched from one or two countries only."""

    geo_block_record_only: bool | None = None
    """The country list's own record only switch. Unset follows the global dry
    run, the same way the ban list does."""
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

    viewer_message_url: str = ""
    """An Apprise URL for messaging the person watching, with {email} and
    {username} filled in from their Plex account. Usually email, for example
    mailtos://you:app-password@gmail.com?to={email}. Empty turns the action
    off."""

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

    watch_alerts: bool = True
    """Send word when a sync turns up a new device or a shared account signal.

    These are the two things this app exists to notice and the two it never
    mentioned: both sat on a page until somebody went and looked, and on the
    server this was written against twenty eight devices had been waiting since
    2023 and no signal had ever been reviewed. A number that is always twenty
    eight carries nothing; one that is usually nought and becomes one carries
    everything, which is why there is also a way to clear the list.

    Only ever about what the sync just found, never the backlog. Quiet unless
    notifications are set up."""

    keep_streams_days: int = 1095
    """How long the detailed record of each stream is kept. 0 keeps everything.

    Not the plays, which are history and are kept whatever this says. This is
    what live activity recorded while a stream was running: the decisions, the
    causes, the buffering, the bandwidth. Three years because the reports can
    be asked for any window up to ten, and somebody throwing away two year old
    streams should have chosen to rather than found out."""

    keep_logs_days: int = 1095
    """How long the audit log and the enforcement log are kept. 0 keeps
    everything.

    A record of what was done rather than of what was watched. Sharing changes
    cannot be undone from here, so what something looked like before is worth
    keeping well past the point it is worth reporting on."""

    backup_keep: int = 7
    """How many database snapshots to keep beside the live one. 0 turns it off.

    Everything the app has worked out lives in one file and nowhere else:
    stall causes, travel flags, bans, rules, reported problems, keep decisions,
    every setting. Tautulli can reconstruct the raw history and none of the
    rest. A week of daily snapshots is a few hundred megabytes against losing
    all of it to a bad restore or a damaged volume."""

    backup_hour: int = 4
    """The hour, in the server's own time, to take it. Four in the morning on
    the assumption that nobody is watching; Settings shows what the server
    thinks the time is, in case TZ is not what you meant."""

    weekly_digest: bool = False
    """One message a week with the week in it, through the same Apprise setup.

    Every number this app works out sits on a page waiting to be visited, and
    mostly is not: devices nobody reviewed, signals nobody opened, a job that
    quietly stopped working. This is the dashboard's week pushed rather than
    pulled. It adds no data and no analysis, and it is off until asked for."""

    digest_weekday: int = 0
    """Which day to send it, Monday being 0, in the server's own time."""

    digest_hour: int = 9
    """The hour to send it, in the server's own time. Settings shows what the
    server thinks the time is, in case TZ is not what you meant."""

    disk_sizes: str = ""
    """How big a disk really is, where it will not say, one per line.

        /mnt/user/media2 = 20 TB

    A share that answers for the whole array rather than for itself reports a
    total nothing can correct from the outside: a twenty terabyte NAS read as
    sixty one terabytes free, and the host agreed, because the share told it
    so. Stating the capacity replaces the total, and what is in use is then
    taken from the files this app can see there rather than from the disk."""

    disk_warn_percent: int = 10
    """Free space, as a percentage, below which a disk is worth a word. 0 is off.

    A media server fills up. It is the one thing that goes wrong on every one
    of them eventually, it gives plenty of warning, and nothing was watching
    for it."""

    disk_critical_percent: int = 3
    """And below which it is worth a stronger word. Still one message: the
    difference is what it says, not how often it says it."""

    task_alerts: bool = True
    """Send word through Apprise when a background job keeps failing.

    Three failures in a row, then nothing more until it works again, so a job
    that is broken says so once rather than every half hour. Quiet unless
    notifications are set up.

    This is the one alert the app could not previously give: a job that stops
    working stops the app having the right answer, and the only sign was a
    page nobody had reason to open."""

    issue_alerts: bool = True
    """Send word through Apprise when somebody reports a problem. Quiet unless
    notifications are set up."""

    viewer_reports_issues: bool = True
    """Whether people who sign in as viewers can report a problem with
    something they watched, and see what they reported. They see their own
    reports and nothing else: not other people's, not the file's path, not who
    else watched it."""

    viewer_privacy: str = "all"
    """What viewer accounts can see: `all` of the server, only their `own`
    data, or everything with other people `anonymised`. Admins see all."""

    allow_framing: bool = False
    """Let other pages show Cartographarr inside a frame, for dashboards such as
    Organizr or Homarr. Off, only Cartographarr itself may frame it, which stops
    another site tricking a click on Ban or Unshare."""

    plex_signin_enabled: bool = False
    """Offer "Sign in with Plex" on the sign-in page. A Plex account signs in as
    the Cartographarr account linked to it, or a viewer account with the same
    email. Usernames are never matched; admins must be linked explicitly."""

    plex_signin_new_viewers: bool = False
    """Let anyone the server is shared with (per Tautulli) sign in with Plex
    and get a viewer account the first time. Nobody becomes an admin this way."""

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

    @field_validator("accent_color", mode="before")
    @classmethod
    def _colour(cls, value: object) -> object:
        """Only a plain hex colour. This ends up inside a style the browser
        applies, so nothing else is worth allowing."""
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return ""
        if not text.startswith("#"):
            text = f"#{text}"
        body = text[1:]
        if len(body) == 3:
            body = "".join(c * 2 for c in body)
        if len(body) != 6 or any(c not in "0123456789abcdefABCDEF" for c in body):
            raise ValueError("A colour looks like #22d3ee")
        return f"#{body.lower()}"

    @field_validator("theme_colors", mode="before")
    @classmethod
    def _theme(cls, value: object) -> object:
        """Hex colours under known names only. This ends up in a style the
        browser applies, so the shape is checked rather than trusted."""
        import json

        if not isinstance(value, str) or not value.strip():
            return ""
        try:
            parsed = json.loads(value)
        except ValueError as exc:
            raise ValueError("Theme colours should be JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Theme colours should be an object of themes")
        out: dict[str, dict[str, str]] = {}
        for mode, colours in parsed.items():
            if mode not in ("dark", "light"):
                raise ValueError("Themes are dark and light")
            if not isinstance(colours, dict):
                raise ValueError(f"The {mode} theme should be an object of colours")
            kept = {}
            for name, colour in colours.items():
                if name not in THEME_PARTS:
                    raise ValueError(f"Unknown part {name}. Try: {', '.join(THEME_PARTS)}")
                if colour in (None, ""):
                    continue
                kept[name] = cls._colour(colour)
            if kept:
                out[mode] = kept
        return json.dumps(out) if out else ""

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

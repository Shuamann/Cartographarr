"""Cartographarr API."""

from __future__ import annotations

import asyncio
import os

import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.geo.lookup import ensure_databases
from app.auth.deps import require_admin, require_user
from app import redact, tasks
from app.routers import admin, auth, branding, data, home, issues, library, live, monitoring, reports, sharing
from app.services import capabilities, enforcer
from app.services import sync as sync_service
from app.settings_store import current, is_configured, missing_required, tautulli_configured
from app.plex import alerts as plex_alerts
from app.tautulli.client import TautulliClient

log = logging.getLogger(__name__)


# The server's user list and libraries are still read from Tautulli alone, so
# an install connected to Plex directly skips that job and says why, rather
# than failing every few minutes against an address nobody gave it.
NO_TAUTULLI = "Tautulli is not connected, and the user list and libraries are read from it"


def _tautulli_or_skip() -> None:
    # A fresh install has no credentials until someone completes setup.
    if not is_configured():
        raise tasks.Skipped("Not set up yet")
    if not tautulli_configured():
        raise tasks.Skipped(NO_TAUTULLI)


def _client_for(source: str) -> TautulliClient | None:
    """A Tautulli client when this source reads from Tautulli, and nothing when
    it reads from Plex, which needs none."""
    if not is_configured():
        raise tasks.Skipped("Not set up yet")
    if source == "plex":
        return None
    if not tautulli_configured():
        raise tasks.Skipped("The library source is Tautulli, which is not connected")
    return TautulliClient(current())


async def _cycle(full: bool = False) -> dict:
    if not is_configured():
        raise tasks.Skipped("Not set up yet")
    settings = current()
    # Without Tautulli the plays are written as they finish, so the sync still
    # has devices, places and sharing signals to build from them.
    if not tautulli_configured():
        return await sync_service.run_sync(None, settings, full=full)
    client = TautulliClient(settings)
    try:
        return await sync_service.run_sync(client, settings, full=full)
    finally:
        await client.aclose()


async def _enforce_cycle() -> dict:
    return await enforcer.run_once()


async def _capability_cycle() -> None:
    if not is_configured():
        raise tasks.Skipped("Not set up yet")
    await capabilities.refresh()


async def _replacement_cycle() -> str:
    from app.services import replacements

    changed = await replacements.poll()
    return f"{changed} changed" if changed else "nothing to update"


async def _backup_cycle() -> dict | str:
    """A snapshot of the database, around the hour asked for.

    The scheduler runs this hourly and it does the work in one of them, which
    keeps the task list honest (a job that says it runs daily and might not
    have, versus one that runs hourly and usually has nothing to do) and
    survives a restart without needing to remember when it last went.
    """
    import asyncio
    from datetime import datetime

    from app.services import backups

    settings = current()
    if settings.backup_keep <= 0:
        raise tasks.Skipped("Backups are switched off")
    # Asked for by hand means now, whatever the hour says.
    if tasks.TASKS["backup"].trigger != "manual" and datetime.now().hour != settings.backup_hour % 24:
        raise tasks.Skipped(f"Taken at {settings.backup_hour % 24:02d}:00")
    result = await asyncio.to_thread(backups.take)
    return result


async def _slow_cycle() -> dict:
    if not is_configured():
        raise tasks.Skipped("Not set up yet")
    # Plex can list everyone the server is shared with, which Tautulli is not
    # needed for. With Tautulli connected it stays the source, because it also
    # knows who it has dropped from its own list.
    if not tautulli_configured():
        from app.plex.server import configured as plex_configured

        if not plex_configured():
            raise tasks.Skipped(NO_TAUTULLI)
        return await sync_service.run_slow_sync(None)
    client = TautulliClient(current())
    try:
        return await sync_service.run_slow_sync(client)
    finally:
        await client.aclose()


tasks.register(tasks.Task(
    "sync", "Sync history", "New plays, titles, file details, devices, locations, sharing signals and stall causes.",
    _cycle, lambda: current().sync_interval_minutes * 60,
))
tasks.register(tasks.Task(
    "backup", "Back up the database",
    "A snapshot of everything the app has worked out, kept beside the live file. Taken while it is in use, so "
    "nothing has to stop.",
    _backup_cycle, lambda: 3600, store_every_run=False,
))
tasks.register(tasks.Task(
    "slow_sync", "Sync users and libraries", "Plex users, their shared libraries, libraries, and Plex's upload speed.",
    _slow_cycle, lambda: current().slow_sync_interval_minutes * 60,
))
tasks.register(tasks.Task(
    "enforce", "Check live streams", "Runs the rules and ban list, records streams, stalls and upload.",
    _enforce_cycle, lambda: current().activity_poll_seconds, store_every_run=False,
))
async def _library_scan() -> dict:
    from app.services import library_scan

    client = _client_for(current().library_source)
    try:
        return await library_scan.scan(client)
    finally:
        if client is not None:
            await client.aclose()


async def _file_details() -> dict | str:
    from app.services import library_scan

    client = _client_for(current().library_source)
    try:
        result = await library_scan.read_details(client)
    finally:
        if client is not None:
            await client.aclose()
    return result if result["read"] else "all files read"


tasks.register(tasks.Task(
    "library_scan", "Scan the library", "Every movie and episode in Plex, watched or not, with bitrate, resolution, codecs and size.",
    _library_scan, lambda: 6 * 3600,
))
tasks.register(tasks.Task(
    "file_details", "Read file details", "Every audio and subtitle track, a chunk at a time, until all files are read.",
    _file_details, lambda: 60,
))
async def _weekly_digest() -> str:
    """Checked hourly, sent once, like the backup.

    No record is kept of having sent it: the task runs on the hour, so the
    window is an hour wide and it cannot fire twice inside one.
    """
    from app.services import digest

    settings = current()
    if not settings.weekly_digest:
        raise tasks.Skipped("The weekly digest is switched off")
    now = datetime.now()
    by_hand = tasks.TASKS["digest"].trigger == "manual"
    if not by_hand and (now.weekday() != settings.digest_weekday % 7 or now.hour != settings.digest_hour % 24):
        day = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][settings.digest_weekday % 7]
        raise tasks.Skipped(f"Sent {day} at {settings.digest_hour % 24:02d}:00")
    return await digest.send()


tasks.register(tasks.Task(
    "digest", "Send the weekly digest", "The week's watching, new devices, signals, problems and anything that failed.",
    _weekly_digest, lambda: 3600, store_every_run=False,
))
async def _update_check() -> str:
    from app.services import updates

    if not current().update_check_enabled:
        raise tasks.Skipped("Update checks are off")
    return updates.summary(await updates.check())


tasks.register(tasks.Task(
    "update_check", "Check for updates", "Whether a newer Cartographarr is on GitHub.",
    _update_check, lambda: 12 * 3600,
))
async def _issue_sync() -> dict | str:
    from app.integrations.seerr import seerr
    from app.services import issues as issue_service

    if not seerr.configured():
        raise tasks.Skipped("Seerr is not set up")
    return await issue_service.sync()


tasks.register(tasks.Task(
    "issues", "Read reported issues", "Problems people reported in Seerr, kept beside what this app knows about the file.",
    _issue_sync, lambda: 300,
))


async def _issue_import() -> dict | str:
    from app.integrations.seerr import seerr
    from app.services import issues as issue_service

    if not seerr.configured():
        raise tasks.Skipped("Seerr is not set up")
    result = await issue_service.import_all()
    # The breakdown, not one number: what was new, what was already here,
    # and what could not be put against a file and was kept anyway.
    return {k: result[k] for k in ("read", "new", "already_here", "unmatched", "no_longer_in_seerr")}


tasks.register(tasks.Task(
    "issues_import", "Bring in Seerr's issues",
    "Every report Seerr holds, matched to the file by its rating key or its ids, and kept even where no file matches.",
    _issue_import, lambda: 24 * 3600,
))
async def _history_check() -> dict | str:
    """Ask Tautulli whether anything it recorded is missing here.

    The one change where everything can look normal and be wrong is switching
    where the data comes from: a day nobody fetched looks exactly like a day
    nobody watched anything. One request covers two thousand days, so this is
    cheap enough to run on a timer and say so either way.
    """
    from app.services import handover

    _tautulli_or_skip()
    client = TautulliClient(current())
    try:
        found = await handover.compare(client)
        if not found.get("asked"):
            raise tasks.Skipped(found.get("reason") or "Tautulli did not answer")
        if not found["missing"]:
            return f"nothing missing across {found['days']} days"
        filled = await handover.fill(client, found)
        return {**{k: v for k, v in found.items() if k not in ("missing_days", "extra_days")}, **filled}
    finally:
        await client.aclose()


async def _plex_bandwidth() -> dict | str:
    """Plex's own record of what each device used, a day at a time.

    It reaches back years before this app was installed, which nothing else
    here does, and the whole four years comes down in one request. Once a day
    is plenty: the figures for a day do not change after it.
    """
    from app.plex import bandwidth
    from app.plex.server import configured as plex_configured

    if not plex_configured():
        raise tasks.Skipped("Plex is not connected")
    return await bandwidth.store()


tasks.register(tasks.Task(
    "plex_bandwidth", "Read Plex's upload figures",
    "What Plex measured each person's devices using, a day at a time, going back as far as Plex kept it.",
    _plex_bandwidth, lambda: 24 * 3600,
))
async def _room_check() -> dict | str:
    """Is any disk getting full.

    A media server fills up, it gives plenty of warning, and nothing was
    watching for it. Hourly, because a disk does not fill in a minute and a
    warning sent every minute is a warning nobody reads.
    """
    from app.services import room

    found = await room.look()
    if not found.get("watched"):
        raise tasks.Skipped(found.get("reason") or "No disk this container can read")
    return found if found.get("told") else f"{found['watched']} disks, all with room"


tasks.register(tasks.Task(
    "room_check", "Watch the disks",
    "Warns once when a disk is getting full, and once when it has room again.",
    _room_check, lambda: 3600,
))
tasks.register(tasks.Task(
    "history_check", "Check nothing is missing",
    "Counts what Tautulli recorded against what is here, day by day, and fetches any day that is short.",
    _history_check, lambda: 24 * 3600,
))
async def _automations() -> dict | str:
    from app.services import automations

    if not current().enforce_enabled:
        raise tasks.Skipped("Rules are switched off")
    result = await automations.run_once()
    return result if result.get("rules") else "no rules that run on their own"


tasks.register(tasks.Task(
    "automations", "Run rules about files and reports",
    "Rules that are not about a live stream: files behaving badly, reports raised, replacements, people going quiet.",
    _automations, lambda: 600, store_every_run=False,
))
tasks.register(tasks.Task(
    "capabilities", "Check Plex Pass and server", "Whether stopping streams is possible, and the server's name and version.",
    _capability_cycle, lambda: 3600,
))
tasks.register(tasks.Task(
    "replacements", "Follow replacements", "Reads Radarr and Sonarr queues and history for replacements in progress.",
    _replacement_cycle, lambda: 60,
))


def _job(key: str):
    async def job() -> None:
        await tasks.run(key)

    return job


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = current()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
    redact.install()
    init_db()
    ensure_databases(
        settings.geoip_dir,
        settings.maxmind_account_id,
        settings.maxmind_license_key,
        settings.geoip_update_interval_days,
    )

    if not settings.run_background_jobs:
        # No scheduler, no syncs, no probe. Everything still answers from what
        # is already in the database.
        log.info("%s started with background jobs off", settings.app_name)
        yield
        return

    scheduler = AsyncIOScheduler()
    # The syncs also run straight away. An interval job otherwise waits a full
    # interval before its first run, so after every restart or image update
    # names stayed stale for up to an hour.
    soon = datetime.now()
    first = {"slow_sync": soon, "sync": soon + timedelta(seconds=20), "library_scan": soon + timedelta(seconds=45),
             "update_check": soon + timedelta(seconds=90)}
    for task in tasks.TASKS.values():
        # Passing next_run_time=None pauses a job, so it is only passed when set.
        extra = {"next_run_time": first[task.key]} if task.key in first else {}
        scheduler.add_job(
            _job(task.key), "interval", seconds=task.interval(), id=task.key,
            max_instances=1, coalesce=True, **extra,
        )
    tasks.scheduler = scheduler
    scheduler.start()

    # Probe once at boot so the UI knows what to enable before the first hour.
    await tasks.run("capabilities", trigger="startup")
    app.state.scheduler = scheduler

    # Plex pushes playback events. The poll above is the floor and stays
    # exactly as it was; this only asks it to run now rather than in a moment,
    # which is the difference between a banned device being stopped when it
    # starts playing and being stopped up to a poll later.
    stopping = asyncio.Event()
    listener = asyncio.create_task(plex_alerts.listen(lambda: tasks.run("enforce", trigger="plex"), stopping))
    app.state.plex_listener = listener

    if is_configured():
        log.info("%s ready", settings.app_name)
    else:
        log.info(
            "%s started unconfigured (missing: %s). Open the UI to run setup",
            settings.app_name,
            ", ".join(missing_required()),
        )

    try:
        yield
    finally:
        stopping.set()
        listener.cancel()
        with suppress(asyncio.CancelledError):
            await listener
        scheduler.shutdown(wait=False)
        from app.routers.data import close_image_client

        await close_image_client()


# No interactive docs or schema: they would hand anyone who can reach the port a
# map of every endpoint without signing in. API_DOCS=true brings them back for
# development.
_docs = os.environ.get("API_DOCS", "").lower() in ("1", "true", "yes")
app = FastAPI(
    title="Cartographarr",
    lifespan=lifespan,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)


# Compressed on the way out, which JSON takes better than almost anything:
# this server's biggest response is 420 KB of mostly repeated key names and
# comes back at 24 KB. The bundle goes from 435 KB to 132 KB. Below a kilobyte
# the header costs more than the saving, so those are left alone, and already
# compressed things (posters, the GeoIP archives) gain nothing and are skipped
# by their content type.
app.add_middleware(GZipMiddleware, minimum_size=1000)


MAP_TILES = "https://basemaps.cartocdn.com"
"""Where the basemap comes from, and the only outside thing the page loads.

Named here as well as in the front end's map style, because a policy that does
not know about it is a policy that leaves the map blank. Swapping in a
self-hosted basemap later means changing both.
"""

POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    # React writes inline styles, and so does the map.
    "style-src 'self' 'unsafe-inline'",
    # Posters and branding are served by this app; the rest are data URIs.
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    f"connect-src 'self' {MAP_TILES} https://*.basemaps.cartocdn.com",
    # The map renders tiles in a worker it creates from a blob.
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
])


@app.middleware("http")
async def security_headers(request, call_next):
    """Headers every response gets. No framing by other sites (clickjacking a
    Ban or Unshare button), unless ALLOW_FRAMING=true for dashboards such as
    Organizr that show apps in a frame (Settings, Access, or ALLOW_FRAMING);
    no guessing content types; and no
    leaking page addresses to other sites.

    The policy says where the page may load things from. There is nothing to
    exploit today, since the front end never writes HTML it was given, but the
    page does render library titles, player names and the text an indexer sent
    back, all of which come from outside this app.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    policy = POLICY
    if not current().allow_framing:
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        policy += "; frame-ancestors 'self'"
    response.headers.setdefault("Content-Security-Policy", policy)
    return response


@app.middleware("http")
async def refuse_cross_site_writes(request, call_next):
    """No other website can make a signed-in browser change anything here.

    The session cookie is SameSite=Lax and writes only take JSON, which covers
    most of it. Reverse proxy sign-in is the gap: the proxy's own login rides
    along on any request. Browsers mark a request another site started with
    Sec-Fetch-Site: cross-site, which a page cannot forge and proxies pass
    through untouched, so writes marked that way are refused. Host headers are
    not compared, since proxies rewrite them.
    """
    if (
        request.method in ("POST", "PUT", "PATCH", "DELETE")
        and request.url.path.startswith("/api/")
        and request.headers.get("sec-fetch-site", "").lower() == "cross-site"
    ):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": "Refused a change requested by another website"}, status_code=403)
    return await call_next(request)


# Auth carries its own guards: /state, /claim and /login have to be reachable
# before anyone is signed in.
app.include_router(auth.router)

# Branding is readable without signing in: the sign-in page needs the logo and
# the browser needs the icon. Writing is guarded inside the router.
app.include_router(branding.router)

# Reading anything means being signed in. Admin covers configuration and the
# setup wizard, so the screen that accepts API keys is never open to whoever
# finds the URL first: the admin account is claimed before setup runs.
app.include_router(home.router, dependencies=[Depends(require_user)])
app.include_router(data.router, dependencies=[Depends(require_user)])
app.include_router(live.router, dependencies=[Depends(require_user)])
app.include_router(reports.router, dependencies=[Depends(require_user)])
app.include_router(library.router, dependencies=[Depends(require_admin)])
# Viewers reach this one: they see and report their own issues, and every
# route in it decides for itself what that means.
app.include_router(issues.router, dependencies=[Depends(require_user)])
app.include_router(admin.router, dependencies=[Depends(require_admin)])
app.include_router(sharing.router)
# Guarded by its own token rather than a session, since monitoring tools
# scrape it. Off entirely until the token is set.
app.include_router(monitoring.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _static_dir() -> Path | None:
    """Built SPA, if there is one.

    /srv/static in the container; the sibling frontend/dist when running from a
    checkout. Absent during backend-only development, which is fine, because Vite
    serves the UI then and proxies /api here.
    """
    for candidate in (Path("/srv/static"), Path(__file__).resolve().parents[2] / "frontend" / "dist"):
        if (candidate / "index.html").exists():
            return candidate
    return None


class _Ui(StaticFiles):
    """The built app, cached the only way a built app can be.

    Vite puts a hash in every asset filename, so those never change under a
    name and can be kept for a year. index.html is the opposite: it names this
    build's hashes, and a browser or a proxy holding yesterday's copy asks for
    chunks that went out with yesterday's build. That is the "Failed to fetch
    dynamically imported module" people see after an update, so it is never
    cached.
    """

    def file_response(self, *args, **kwargs):  # type: ignore[override]
        response = super().file_response(*args, **kwargs)
        path = str(args[0] if args else kwargs.get("full_path", ""))
        if path.endswith(".html"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        elif "/assets/" in path.replace("\\", "/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


_static = _static_dir()
if _static is not None:
    # Mounted last so every /api route still wins. html=True sends index.html
    # for unknown paths, which is what a client-side app needs.
    # The map loads module workers (.mjs), which browsers refuse unless served
    # as JavaScript. Slim container images have no mime.types to say so.
    import mimetypes

    mimetypes.add_type("text/javascript", ".mjs")
    app.mount("/", _Ui(directory=_static, html=True), name="ui")
else:
    log.info("No built frontend found; serving API only")

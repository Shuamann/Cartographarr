"""Cartographarr API."""

from __future__ import annotations

import os

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.geo.lookup import ensure_databases
from app.auth.deps import require_admin, require_user
from app import redact, tasks
from app.routers import admin, auth, branding, data, library, live, monitoring, reports, sharing
from app.services import capabilities, enforcer
from app.services import sync as sync_service
from app.settings_store import current, is_configured, missing_required
from app.tautulli.client import TautulliClient

log = logging.getLogger(__name__)


async def _cycle(full: bool = False) -> dict:
    # A fresh install has no credentials until someone completes setup.
    if not is_configured():
        raise tasks.Skipped("Not set up yet")
    settings = current()
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


async def _slow_cycle() -> dict:
    if not is_configured():
        raise tasks.Skipped("Not set up yet")
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
    "slow_sync", "Sync users and libraries", "Plex users, their shared libraries, libraries, and Plex's upload speed.",
    _slow_cycle, lambda: current().slow_sync_interval_minutes * 60,
))
tasks.register(tasks.Task(
    "enforce", "Check live streams", "Runs the rules and ban list, records streams, stalls and upload.",
    _enforce_cycle, lambda: current().activity_poll_seconds, store_every_run=False,
))
async def _library_scan() -> dict:
    from app.services import library_scan

    if not is_configured():
        raise tasks.Skipped("Not set up yet")
    client = TautulliClient(current())
    try:
        return await library_scan.scan(client)
    finally:
        await client.aclose()


async def _file_details() -> dict | str:
    from app.services import library_scan

    if not is_configured():
        raise tasks.Skipped("Not set up yet")
    client = TautulliClient(current())
    try:
        result = await library_scan.read_details(client)
    finally:
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

    scheduler = AsyncIOScheduler()
    # The syncs also run straight away. An interval job otherwise waits a full
    # interval before its first run, so after every restart or image update
    # names stayed stale for up to an hour.
    soon = datetime.now()
    first = {"slow_sync": soon, "sync": soon + timedelta(seconds=20), "library_scan": soon + timedelta(seconds=45)}
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
        scheduler.shutdown(wait=False)


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


@app.middleware("http")
async def security_headers(request, call_next):
    """Headers every response gets. No framing by other sites (clickjacking a
    Ban or Unshare button), unless ALLOW_FRAMING=true for dashboards such as
    Organizr that show apps in a frame (Settings, Access, or ALLOW_FRAMING);
    no guessing content types; and no
    leaking page addresses to other sites."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if not current().allow_framing:
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
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
app.include_router(data.router, dependencies=[Depends(require_user)])
app.include_router(live.router, dependencies=[Depends(require_user)])
app.include_router(reports.router, dependencies=[Depends(require_user)])
app.include_router(library.router, dependencies=[Depends(require_admin)])
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


_static = _static_dir()
if _static is not None:
    # Mounted last so every /api route still wins. html=True sends index.html
    # for unknown paths, which is what a client-side app needs.
    # The map loads module workers (.mjs), which browsers refuse unless served
    # as JavaScript. Slim container images have no mime.types to say so.
    import mimetypes

    mimetypes.add_type("text/javascript", ".mjs")
    app.mount("/", StaticFiles(directory=_static, html=True), name="ui")
else:
    log.info("No built frontend found; serving API only")

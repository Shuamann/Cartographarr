"""Cartographarr API."""

from __future__ import annotations

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
from app.routers import admin, auth, branding, data, live, sharing
from app.services import capabilities, enforcer
from app.services import sync as sync_service
from app.settings_store import current, is_configured, missing_required
from app.tautulli.client import TautulliClient

log = logging.getLogger(__name__)


async def _cycle(full: bool = False) -> None:
    # A fresh install has no credentials until someone completes setup. Skip
    # quietly rather than logging a stack trace every five minutes.
    if not is_configured():
        return
    settings = current()
    client = TautulliClient(settings)
    try:
        await sync_service.run_sync(client, settings, full=full)
    except Exception:
        log.exception("sync cycle failed")
    finally:
        await client.aclose()


async def _enforce_cycle() -> None:
    try:
        await enforcer.run_once()
    except Exception:
        log.exception("enforcement sweep failed")


async def _capability_cycle() -> None:
    try:
        await capabilities.refresh()
    except Exception:
        log.exception("capability probe failed")


async def _slow_cycle() -> None:
    if not is_configured():
        return
    client = TautulliClient(current())
    try:
        await sync_service.run_slow_sync(client)
    except Exception:
        log.exception("slow sync cycle failed")
    finally:
        await client.aclose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = current()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
    init_db()
    ensure_databases(
        settings.geoip_dir,
        settings.maxmind_account_id,
        settings.maxmind_license_key,
        settings.geoip_update_interval_days,
    )

    scheduler = AsyncIOScheduler()
    # Both run once straight away as well as on their interval. An interval job
    # otherwise waits a full interval before its first run, so after every
    # restart or image update names stayed stale for up to an hour.
    soon = datetime.now()
    scheduler.add_job(
        _slow_cycle,
        "interval",
        minutes=settings.slow_sync_interval_minutes,
        id="slow_sync",
        next_run_time=soon,
    )
    scheduler.add_job(
        _cycle,
        "interval",
        minutes=settings.sync_interval_minutes,
        id="sync",
        next_run_time=soon + timedelta(seconds=20),
    )
    scheduler.add_job(
        _enforce_cycle, "interval", seconds=settings.activity_poll_seconds, id="enforce"
    )
    scheduler.add_job(_capability_cycle, "interval", minutes=60, id="capabilities")
    scheduler.start()

    # Probe once at boot so the UI knows what to enable before the first hour.
    if is_configured():
        await capabilities.refresh()
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


app = FastAPI(title="Cartographarr", lifespan=lifespan)
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
app.include_router(admin.router, dependencies=[Depends(require_admin)])
app.include_router(sharing.router)


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
    app.mount("/", StaticFiles(directory=_static, html=True), name="ui")
else:
    log.info("No built frontend found; serving API only")

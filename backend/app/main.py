"""Cartographarr API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.db import init_db
from app.geo.lookup import ensure_databases
from app.routers import admin, data
from app.services import sync as sync_service
from app.settings_store import current
from app.tautulli.client import TautulliClient

log = logging.getLogger(__name__)


async def _cycle(full: bool = False) -> None:
    settings = current()
    client = TautulliClient(settings)
    try:
        await sync_service.run_sync(client, settings, full=full)
    except Exception:
        log.exception("sync cycle failed")
    finally:
        await client.aclose()


async def _slow_cycle() -> None:
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
    scheduler.add_job(_cycle, "interval", minutes=settings.sync_interval_minutes, id="sync")
    scheduler.add_job(
        _slow_cycle, "interval", minutes=settings.slow_sync_interval_minutes, id="slow_sync"
    )
    scheduler.start()
    app.state.scheduler = scheduler
    log.info("%s ready", settings.app_name)

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Cartographarr", lifespan=lifespan)
app.include_router(data.router)
app.include_router(admin.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

"""Background tasks: what runs on a schedule, and how each run went.

Every scheduled job goes through `run()`, which times it, catches what it
raises, and records the outcome, so Settings, Tasks can show how often each
runs, when it last ran and how that went, when it runs next, and the error if
it failed. Runs are also triggerable by hand.

The rule sweep runs every few seconds, so only its failures are stored, with
counts kept in memory; everything else stores every run. The last 100 runs
per task are kept.
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.redact import redact

log = logging.getLogger(__name__)

KEEP_RUNS = 100


class Skipped(Exception):
    """Raised by a task with nothing to do, such as before setup is finished."""


@dataclass
class Task:
    key: str
    name: str
    description: str
    run: Callable[[], Awaitable[Any]]
    interval: Callable[[], float]  # seconds
    store_every_run: bool = True
    # In-memory state, since the app started.
    running: bool = False
    runs: int = 0
    failures: int = 0
    last: dict[str, Any] = field(default_factory=dict)


TASKS: dict[str, Task] = {}
scheduler: Any = None  # the AsyncIOScheduler, set at startup


def register(task: Task) -> None:
    TASKS[task.key] = task


async def run(key: str, trigger: str = "schedule") -> dict[str, Any]:
    task = TASKS[key]
    if task.running:
        return {"status": "already running"}
    task.running = True
    started = datetime.now(UTC)
    clock = time.monotonic()
    status, message = "ok", None
    try:
        result = await task.run()
        if isinstance(result, str):
            message = result
        elif isinstance(result, dict):
            message = ", ".join(f"{k} {v}" for k, v in result.items() if v not in (None, 0, {}, []))[:500] or None
    except Skipped as exc:
        status, message = "skipped", str(exc)
    except Exception as exc:  # noqa: BLE001 - recorded and logged, never raised into the scheduler
        status = "failed"
        message = redact("".join(traceback.format_exception(exc))[-4000:])
        log.error("task %s failed: %s", key, redact(exc))
    finally:
        task.running = False
    duration_ms = int((time.monotonic() - clock) * 1000)
    task.runs += 1
    task.failures += 1 if status == "failed" else 0
    task.last = {
        "started_at": started.isoformat(), "duration_ms": duration_ms, "status": status,
        "message": message, "trigger": trigger,
    }
    if task.store_every_run or status == "failed" or trigger == "manual":
        try:
            await asyncio.to_thread(_store, key, started, duration_ms, status, message, trigger)
        except Exception:  # noqa: BLE001
            log.exception("could not record a run of %s", key)
    return task.last


def _store(key: str, started: datetime, duration_ms: int, status: str, message: str | None, trigger: str) -> None:
    from sqlalchemy import delete, select

    from app.db import session_scope
    from app.models import TaskRun

    with session_scope() as db:
        db.add(TaskRun(task=key, started_at=started, duration_ms=duration_ms, status=status, message=message, trigger=trigger))
        db.flush()
        keep = select(TaskRun.id).where(TaskRun.task == key).order_by(TaskRun.id.desc()).limit(KEEP_RUNS)
        db.execute(delete(TaskRun).where(TaskRun.task == key, TaskRun.id.not_in(keep)))


def describe() -> list[dict[str, Any]]:
    out = []
    for task in TASKS.values():
        job = scheduler.get_job(task.key) if scheduler is not None else None
        next_run = job.next_run_time.astimezone(UTC).isoformat() if job is not None and job.next_run_time else None
        out.append({
            "key": task.key,
            "name": task.name,
            "description": task.description,
            "every_seconds": task.interval(),
            "next_run": next_run,
            "running": task.running,
            "runs": task.runs,
            "failures": task.failures,
            "last": task.last or None,
            "stores_every_run": task.store_every_run,
        })
    return out

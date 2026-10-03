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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.redact import redact

log = logging.getLogger(__name__)

KEEP_RUNS = 100

FAILURES_BEFORE_ALERT = 3
"""How many times in a row a job must fail before anyone is told.

One failure is a timeout or a service restarting. Three in a row is a job that
is not going to fix itself. After that nothing more is sent until it works
again, so a job broken for a week is one message rather than three hundred."""


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
    consecutive: int = 0
    """Failures since the last time it worked, which is the number that says
    whether something is broken. `failures` counts them all and never falls."""
    alerted: bool = False
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
        # The sentence, not the stack. Most of these raise something a person
        # wrote to be read ("GitHub can't find <repo>. If the repository is
        # private, add a token"), and four thousand characters of traceback
        # buried it on the Tasks page. The stack goes to the log, where it is
        # the right thing to have.
        message = redact(str(exc)) or type(exc).__name__
        log.error("task %s failed: %s", key, redact(exc), exc_info=exc)
    finally:
        task.running = False
    duration_ms = int((time.monotonic() - clock) * 1000)
    task.runs += 1
    task.failures += 1 if status == "failed" else 0
    if status == "failed":
        task.consecutive += 1
    elif status == "ok":
        task.consecutive = 0
    await _tell_someone(task, status, message)
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


async def _tell_someone(task: Task, status: str, message: str | None) -> None:
    """One message when a job breaks, one when it comes back, nothing between.

    A job that has stopped working is the thing most worth knowing about and
    the thing least likely to be noticed, since the only sign is a page that
    quietly stops being right.
    """
    from app.integrations.notify import apprise_notifier
    from app.settings_store import current

    try:
        if not current().task_alerts:
            return
        if status == "failed" and not task.alerted and task.consecutive >= FAILURES_BEFORE_ALERT:
            task.alerted = True
            await apprise_notifier.send(
                f"{task.name} is failing",
                f"{task.name} has failed {task.consecutive} times in a row. "
                f"The last reason was: {message or 'no reason given'}. "
                f"Nothing more will be sent about it until it works again.",
            )
        elif status == "ok" and task.alerted:
            task.alerted = False
            await apprise_notifier.send(f"{task.name} is working again", f"{task.name} has just run cleanly.")
    except Exception:  # noqa: BLE001 - a job that failed must not fail twice
        log.exception("could not send word about %s", task.key)


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

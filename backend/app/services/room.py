"""Telling somebody before a disk fills, rather than after.

A media server fills up. It is the one thing that goes wrong on every one of
them eventually, it gives plenty of warning, and nothing here was watching for
it: the Storage page says how much room is left and somebody has to go and
look.

The shape is the same as the alert for a job that has stopped: one message
when a disk crosses the line, nothing more about that disk until it either
gets worse or recovers. A warning sent every hour is a warning nobody reads.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# What each disk was last said to be, so the same news is not sent twice.
_told: dict[str, str] = {}


def forget() -> None:
    """For tests, and for a settings change that should be able to warn again."""
    _told.clear()


def _state(free: int, total: int, warn_at: int, critical_at: int) -> str:
    if not total:
        return "unknown"
    share = free / total * 100
    if share <= critical_at:
        return "critical"
    if share <= warn_at:
        return "low"
    return "fine"


def check(disks: list[dict[str, Any]], warn_at: int, critical_at: int) -> list[dict[str, Any]]:
    """Which disks have just crossed a line, and which way.

    Only the crossings. A disk that was already low and still is says nothing,
    because it said it the first time and nothing has changed.
    """
    news = []
    for disk in disks:
        path = disk.get("path")
        free, total = disk.get("free"), disk.get("total")
        if not path or not free or not total:
            continue
        now = _state(int(free), int(total), warn_at, critical_at)
        before = _told.get(path)
        if now == before:
            continue
        _told[path] = now
        # Nothing is said the first time a disk is seen in a good state: the
        # alert is for news, and "this disk is fine" is not news.
        if before is None and now == "fine":
            continue
        news.append({
            "path": path,
            "state": now,
            "was": before,
            "free": int(free),
            "total": int(total),
            "percent": round(int(free) / int(total) * 100, 1),
            "labels": disk.get("labels") or [],
            # True where the capacity was written down rather than read off
            # the disk, which means the room left is worked out from the files
            # this app knows about. Anything else on the share is invisible to
            # it, so the figure errs towards saying there is more room than
            # there is, which is the dangerous direction for this warning. It
            # is still better than the share's own answer, which is what the
            # setting exists for, but the message has to say which it is.
            "stated": bool(disk.get("stated")),
        })
    return news


def _size(value: int) -> str:
    for unit, step in (("TB", 1e12), ("GB", 1e9), ("MB", 1e6)):
        if value >= step:
            return f"{value / step:.1f} {unit}"
    return f"{value} bytes"


def words(item: dict[str, Any]) -> tuple[str, str]:
    """What to say about one disk, as a heading and a line."""
    where = ", ".join(item["labels"]) or item["path"]
    left = f"{_size(item['free'])} left of {_size(item['total'])}, which is {item['percent']}%"
    if item.get("stated"):
        left += ", worked out from the capacity you stated and the files this app can see there"
    if item["state"] == "critical":
        return (f"{where} is nearly full", f"{left}. Nothing more will be said about it until it changes.")
    if item["state"] == "low":
        return (f"{where} is getting full", f"{left}. Nothing more will be said about it until it changes.")
    return (f"{where} has room again", f"{left}.")


async def tell(news: list[dict[str, Any]]) -> int:
    """Send what has changed. Returns how many messages went."""
    from app.integrations.notify import apprise_notifier

    sent = 0
    for item in news:
        heading, body = words(item)
        try:
            await apprise_notifier.send(heading, body)
            sent += 1
        except Exception:  # noqa: BLE001 - a disk filling must not be hidden by a broken notifier
            log.exception("could not send word about %s", item["path"])
    return sent


async def look() -> dict[str, Any]:
    """Read the disks, say what has changed, and report what was found."""
    import asyncio

    from app.services import stores
    from app.settings_store import current

    settings = current()
    if not settings.disk_warn_percent:
        return {"watched": 0, "told": 0, "reason": "switched off"}

    # Through the Storage page's own figures rather than reading the mounts
    # again: it already finds which disk is under each store, and already
    # reports two stores on one share as one disk.
    found = await asyncio.to_thread(stores.summary, 30)
    disks: dict[str, dict] = {}
    for row in found.get("stores", []):
        where = row.get("path")
        if not where:
            continue
        disk = disks.setdefault(where, {"path": where, "free": row.get("free"),
                                        "total": row.get("total"), "labels": [],
                                        "stated": bool(row.get("stated"))})
        disk["labels"].append(row.get("store"))
    readable = [d for d in disks.values() if d.get("free") and d.get("total")]
    news = check(readable, settings.disk_warn_percent, settings.disk_critical_percent)
    sent = await tell(news) if news else 0
    return {
        "watched": len(readable),
        "unreadable": len(disks) - len(readable),
        "told": sent,
        "changed": [{"path": n["path"], "state": n["state"], "percent": n["percent"]} for n in news],
    }

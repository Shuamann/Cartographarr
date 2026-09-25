"""Rules about things nobody is watching.

A stream rule gets its chance every few seconds, because a stream is happening
now. A file that transcodes for everyone, a report nobody has answered, a
replacement stuck waiting: those are true for hours, so they are swept every
ten minutes instead, through the same matcher, the same record only switch, the
same cooldown and the same Log.

Two things keep a rule that can act while you sleep from running away:

- **A cooldown per subject.** The same file cannot set the same rule off twice
  in a day, so a file that transcodes for everybody is one entry, not ninety.
- **A daily cap.** Per rule, and a tighter one across every rule for anything
  that spends bandwidth. Hitting a cap is recorded, because a rule that wanted
  to act fifty times is worth knowing about.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.db import session_scope
from app.settings_store import current

log = logging.getLogger(__name__)

SUBJECT_COOLDOWN_HOURS = 24
"""The same subject setting the same rule off again is the same news."""

DOWNLOADING = {"queue_replacement"}
"""Actions that spend bandwidth, and so answer to the tighter cap."""


def _acted_today(rule_id: int) -> int:
    from app.models import EnforcementLog

    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
    with session_scope() as db:
        return int(db.execute(
            select(func.count()).select_from(EnforcementLog).where(
                EnforcementLog.rule_id == rule_id,
                EnforcementLog.acted_at >= since,
                EnforcementLog.dry_run.is_(False),
            )
        ).scalar() or 0)


def _downloads_today() -> int:
    from app.models import Replacement

    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
    with session_scope() as db:
        return int(db.execute(
            select(func.count()).select_from(Replacement).where(
                Replacement.created_at >= since, Replacement.created_by == AUTOMATION
            )
        ).scalar() or 0)


AUTOMATION = "a rule"
"""Who asked, when a rule did. Shown in Replacements, so an automatic one is
never mistaken for a decision somebody made."""


def _recently_acted(rule_id: int, subject_id: str) -> bool:
    from app.models import EnforcementLog

    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=SUBJECT_COOLDOWN_HOURS)
    with session_scope() as db:
        return db.execute(
            select(EnforcementLog.id).where(
                EnforcementLog.rule_id == rule_id,
                EnforcementLog.subject == subject_id,
                EnforcementLog.acted_at >= since,
            ).limit(1)
        ).first() is not None


async def run_once() -> dict[str, Any]:
    """One sweep of every rule that is not about a live stream."""
    from app.models import Rule
    from app.services import enforcer, subjects

    with session_scope() as db:
        rules = [
            rule
            for rule in db.execute(select(Rule).where(Rule.enabled.is_(True)).order_by(Rule.id)).scalars()
            if (rule.trigger or "stream") != "stream"
        ]
        for rule in rules:
            db.expunge(rule)
    if not rules:
        return {"rules": 0}

    settings = current()
    checked = matched = acted = capped = 0
    by_trigger: dict[str, list[dict[str, Any]]] = {}

    for rule in rules:
        trigger = rule.trigger or "stream"
        if trigger not in by_trigger:
            by_trigger[trigger] = subjects.for_trigger(trigger)
        pool = by_trigger[trigger]
        checked += len(pool)

        missing = enforcer.unmet_requirements(enforcer.rule_tree(rule))
        if missing:
            log.warning("rule %r skipped: requires %s", rule.name, ", ".join(missing))
            continue

        cap = rule.daily_cap if rule.daily_cap is not None else settings.automation_daily_cap
        used = _acted_today(rule.id)
        record_only = enforcer.record_only(rule)

        for subject in pool:
            if not enforcer.matches(rule, subject, {}):
                continue
            matched += 1
            subject_id = subjects.identity(subject)
            if _recently_acted(rule.id, subject_id):
                continue
            if not record_only and cap and used >= cap:
                capped += 1
                _record(rule, subject, subject_id, dry_run=True,
                        result=f"Not done: this rule has already acted {used} times today")
                continue
            results = await _run_actions(rule, subject, record_only=record_only)
            _record(rule, subject, subject_id, dry_run=record_only, result="; ".join(results) or "matched")
            if not record_only:
                used += 1
                acted += 1

    return {"rules": len(rules), "checked": checked, "matched": matched, "acted": acted, "capped": capped}


async def _run_actions(rule, subject: dict[str, Any], record_only: bool) -> list[str]:
    from app.actions import registry
    from app.services import enforcer

    out = []
    for step in enforcer.rule_actions(rule):
        name = step.get("name")
        action = registry.get(name or "")
        if action is None:
            out.append(f"{name}: no such action")
            continue
        if record_only:
            out.append(f"would {action.label.lower()}")
            continue
        if name in DOWNLOADING and _downloads_today() >= current().automation_download_cap:
            out.append("not downloaded: the day's limit on automatic replacements is used up")
            continue
        try:
            out.append(await action.execute(subject, step.get("params") or {}))
        except Exception as exc:  # noqa: BLE001 - one failed action must not stop the sweep
            log.exception("rule %r action %s failed", rule.name, name)
            out.append(f"{name} failed: {exc}")
    return out


def _record(rule, subject: dict[str, Any], subject_id: str, dry_run: bool, result: str) -> None:
    """The Log entry. The same shape as a stream match, so one page shows both."""
    from app import audit
    from app.models import EnforcementLog

    with session_scope() as db:
        db.add(EnforcementLog(
            rule_id=rule.id,
            rule_name=rule.name,
            trigger=rule.trigger,
            subject=subject_id,
            user_id=subject.get("user_id"),
            username=subject.get("username"),
            rating_key=subject.get("rating_key"),
            full_title=subject.get("full_title"),
            media_type=subject.get("media_type"),
            action=json.dumps([step.get("name") for step in _steps(rule)]),
            dry_run=dry_run,
            result=result,
            acted_at=datetime.now(UTC).replace(tzinfo=None),
        ))
    audit.record(None, "rule.automation", f"{rule.name}: {result}", target=subject_id, actor="Cartographarr")


def _steps(rule) -> list[dict[str, Any]]:
    from app.services import enforcer

    return enforcer.rule_actions(rule)

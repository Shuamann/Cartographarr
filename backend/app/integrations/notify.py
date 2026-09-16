"""Sending someone a message.

Apprise rather than a client per service. One dependency covers Discord, ntfy,
Gotify, Pushover, Telegram, Slack, email and a hundred others, and writing
those one at a time would be the worst trade in this codebase.

A plain webhook sits alongside it for anything Apprise does not speak.
"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx

from app.integrations.base import Health, describe_failure
from app.settings_store import current

log = logging.getLogger(__name__)

SPLIT = re.compile(r"[\s,]+")


def _urls() -> list[str]:
    return [u for u in SPLIT.split(current().apprise_urls or "") if u]


class AppriseNotifier:
    name = "apprise"
    label = "Notifications"

    def configured(self) -> bool:
        return bool(_urls())

    async def health(self) -> Health:
        urls = _urls()
        if not urls:
            return Health(False, "Not set up")
        # Apprise validates a URL without sending anything, which is the only
        # honest check available: a working target cannot be proven without
        # actually messaging someone.
        import apprise

        client = apprise.Apprise()
        bad = [u for u in urls if not client.add(u)]
        if bad:
            return Health(False, f"{len(bad)} of {len(urls)} not understood")
        return Health(True, f"{len(urls)} target{'s' if len(urls) > 1 else ''} configured")

    async def send(self, title: str, body: str) -> str:
        urls = _urls()
        if not urls:
            raise RuntimeError("No notification targets configured")

        import apprise

        client = apprise.Apprise()
        for url in urls:
            client.add(url)

        # Apprise is synchronous, so it runs off the event loop rather than
        # stalling the enforcement sweep behind a slow push service.
        sent = await asyncio.to_thread(client.notify, title=title, body=body)
        if not sent:
            raise RuntimeError("Apprise reported a failure")
        return f"notified {len(urls)} target(s)"


class WebhookNotifier:
    name = "webhook"
    label = "Webhook"

    def configured(self) -> bool:
        return bool(current().webhook_url)

    async def health(self) -> Health:
        url = current().webhook_url
        if not url:
            return Health(False, "Not set up")
        if not url.startswith(("http://", "https://")):
            return Health(False, "Needs to start with http:// or https://")
        return Health(True, "Configured")

    async def send(self, payload: dict) -> str:
        url = current().webhook_url
        if not url:
            raise RuntimeError("No webhook configured")
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(describe_failure(exc)) from exc
        return "webhook posted"


apprise_notifier = AppriseNotifier()
webhook_notifier = WebhookNotifier()

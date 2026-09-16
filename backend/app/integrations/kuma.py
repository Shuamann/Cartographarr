"""Uptime Kuma push monitor.

The sync pings this after every run. Testing it sends one real "up" ping,
which is the only way to know the push token is right, and is harmless: it
is exactly what the next sync would send anyway.
"""

from __future__ import annotations

import httpx

from app.integrations.base import Health, describe_failure
from app.settings_store import current


class UptimeKuma:
    name = "uptime_kuma"
    label = "Uptime Kuma"

    def configured(self) -> bool:
        return bool(current().uptime_kuma_push_url)

    async def health(self) -> Health:
        url = current().uptime_kuma_push_url
        if not url:
            return Health(False, "Not set up")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    url, params={"status": "up", "msg": "Cartographarr test"}
                )
                response.raise_for_status()
                body = response.json()
        except Exception as exc:  # noqa: BLE001
            return Health(False, describe_failure(exc))
        # Kuma answers 200 with ok false for an unknown push token.
        if not body.get("ok", False):
            return Health(False, body.get("msg") or "Kuma did not recognise that push token")
        return Health(True, "Ping received")


uptime_kuma = UptimeKuma()

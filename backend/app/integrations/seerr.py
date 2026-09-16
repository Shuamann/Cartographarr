"""Seerr.

Overseerr and Jellyseerr merged into Seerr in February 2026 and both are now
deprecated, so this targets Seerr. The API shape is inherited from Overseerr,
so an older instance will very likely work too.

What it buys: who asked for a title and when. "This was requested and never
watched" and "who wanted this" are both questions the history alone cannot
answer.
"""

from __future__ import annotations

import logging

from app.integrations.base import Health, describe_failure, get_json
from app.models import MediaItem
from app.settings_store import current

log = logging.getLogger(__name__)


class SeerrIntegration:
    name = "seerr"
    label = "Seerr"

    @property
    def base_url(self) -> str:
        return (current().seerr_url or "").rstrip("/")

    @property
    def api_key(self) -> str:
        return current().seerr_api_key or ""

    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.api_key}

    async def health(self) -> Health:
        if not self.configured():
            return Health(False, "Not set up")
        try:
            status = await get_json(f"{self.base_url}/api/v1/status", headers=self.headers)
            return Health(True, "Connected", str(status.get("version") or ""))
        except Exception as exc:  # noqa: BLE001
            return Health(False, describe_failure(exc))

    @staticmethod
    def _kind(media_type: str | None) -> str:
        return "tv" if media_type in ("show", "season", "episode") else "movie"

    def link_for(self, item: MediaItem) -> str | None:
        if not (self.configured() and item.tmdb_id):
            return None
        return f"{self.base_url}/{self._kind(item.media_type)}/{item.tmdb_id}"

    async def request_for(self, item: MediaItem) -> dict | None:
        """Who asked for this, if anyone.

        Returns None rather than raising: a title that was never requested is
        the normal case, not a failure.
        """
        if not (self.configured() and item.tmdb_id):
            return None

        kind = self._kind(item.media_type)
        try:
            detail = await get_json(
                f"{self.base_url}/api/v1/{kind}/{item.tmdb_id}", headers=self.headers
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("seerr lookup failed for %s: %s", item.tmdb_id, exc)
            return None

        requests = (detail.get("mediaInfo") or {}).get("requests") or []
        if not requests:
            return None

        first = requests[0]
        requester = first.get("requestedBy") or {}
        return {
            "requested_by": requester.get("displayName")
            or requester.get("plexUsername")
            or requester.get("username"),
            "requested_at": first.get("createdAt"),
            "status": first.get("status"),
        }


seerr = SeerrIntegration()

"""Radarr and Sonarr.

Both expose the same v3 API shape, so one class covers them. The awkward part
is that neither links by TMDB or TVDB id: their URLs use a `titleSlug`, so the
id has to be traded for a slug through the API and remembered.
"""

from __future__ import annotations

import logging

from app.db import session_scope
from app.integrations.base import Health, describe_failure, get_json
from app.models import MediaItem
from app.settings_store import current

log = logging.getLogger(__name__)


class ArrIntegration:
    def __init__(self, name: str, label: str, path: str, id_param: str, slug_field: str) -> None:
        self.name = name
        self.label = label
        self.path = path  # "movie" or "series"
        self.id_param = id_param  # "tmdbId" or "tvdbId"
        self.slug_field = slug_field  # which column caches the slug

    # ---- configuration -----------------------------------------------------

    @property
    def base_url(self) -> str:
        return str(getattr(current(), f"{self.name}_url", "") or "").rstrip("/")

    @property
    def link_base(self) -> str:
        """Where a person's browser should go, which is not always where this
        app can reach: local for the API, the proxy address for people."""
        public = str(getattr(current(), f"{self.name}_public_url", "") or "").rstrip("/")
        return public or self.base_url

    @property
    def api_key(self) -> str:
        return str(getattr(current(), f"{self.name}_api_key", "") or "")

    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.api_key}

    # ---- health ------------------------------------------------------------

    async def health(self) -> Health:
        if not self.configured():
            return Health(False, "Not set up")
        try:
            status = await get_json(
                f"{self.base_url}/api/v3/system/status", headers=self.headers
            )
            return Health(True, "Connected", status.get("version"))
        except Exception as exc:  # noqa: BLE001 - the failure is the answer
            return Health(False, describe_failure(exc))

    # ---- slugs -------------------------------------------------------------

    async def slug_for(self, external_id: str) -> str | None:
        """Trade a TMDB or TVDB id for the slug the web UI uses in its URLs."""
        if not (self.configured() and external_id):
            return None
        try:
            found = await get_json(
                f"{self.base_url}/api/v3/{self.path}",
                headers=self.headers,
                params={self.id_param: external_id},
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("%s lookup failed for %s: %s", self.name, external_id, exc)
            return None

        items = found if isinstance(found, list) else [found]
        for item in items:
            if isinstance(item, dict) and item.get("titleSlug"):
                return str(item["titleSlug"])
        return None

    async def link_for(self, item: MediaItem) -> str | None:
        """A link to this title, resolving and caching the slug if needed.

        Falls back to the add-search page when the title is not in the library,
        which is still more useful than no button at all.
        """
        if not self.configured():
            return None

        external_id = item.tmdb_id if self.id_param == "tmdbId" else item.tvdb_id
        if not external_id:
            return None

        slug = getattr(item, self.slug_field, None)
        if not slug:
            slug = await self.slug_for(external_id)
            if slug:
                with session_scope() as db:
                    stored = db.get(MediaItem, item.rating_key)
                    if stored is not None:
                        setattr(stored, self.slug_field, slug)

        if slug:
            return f"{self.link_base}/{self.path}/{slug}"
        prefix = "tmdb" if self.id_param == "tmdbId" else "tvdb"
        return f"{self.link_base}/add/new?term={prefix}%3A{external_id}"


radarr = ArrIntegration("radarr", "Radarr", "movie", "tmdbId", "radarr_slug")
sonarr = ArrIntegration("sonarr", "Sonarr", "series", "tvdbId", "sonarr_slug")


def for_media_type(media_type: str | None) -> ArrIntegration:
    """Films go to Radarr, everything episodic to Sonarr."""
    return sonarr if media_type in ("show", "season", "episode") else radarr


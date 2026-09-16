"""TMDB.

Used for one thing so far: artwork for the sign-in backdrop.

That has a constraint worth stating, because it decides the source. The login
screen is seen before anyone signs in, so whatever feeds it is public. Trending
films are global and reveal nothing. Using the server's own library art there
would tell any visitor what is in the library, so it is not an option however
good it would look.

TMDB's image CDN needs no key and sets permissive CORS, so the browser fetches
the pictures directly and only the list comes through here.
"""

from __future__ import annotations

import logging
import time

from app.integrations.base import Health, describe_failure, get_json
from app.settings_store import current

log = logging.getLogger(__name__)

API = "https://api.themoviedb.org/3"
IMAGES = "https://image.tmdb.org/t/p"
CACHE_SECONDS = 6 * 3600

_cache: tuple[float, list[str]] = (0.0, [])


class TmdbIntegration:
    name = "tmdb"
    label = "TMDB artwork"

    @property
    def api_key(self) -> str:
        return current().tmdb_api_key or ""

    def configured(self) -> bool:
        return bool(self.api_key)

    async def health(self) -> Health:
        if not self.configured():
            return Health(False, "Not set up")
        try:
            await get_json(f"{API}/configuration", params={"api_key": self.api_key})
            return Health(True, "Connected")
        except Exception as exc:  # noqa: BLE001
            return Health(False, describe_failure(exc))

    async def trending_backdrops(self, size: str = "w1280", limit: int = 12) -> list[str]:
        """Backdrop URLs for this week's trending films.

        Cached for hours: the list changes daily at most, and the sign-in page
        should not call an external API every time someone loads it.
        """
        global _cache
        cached_at, urls = _cache
        if urls and time.time() - cached_at < CACHE_SECONDS:
            return urls

        if not self.configured():
            return []

        try:
            data = await get_json(
                f"{API}/trending/movie/week", params={"api_key": self.api_key}
            )
        except Exception as exc:  # noqa: BLE001 - a plain background is fine
            log.warning("TMDB trending failed: %s", exc)
            return urls  # whatever was cached beats nothing

        found = [
            f"{IMAGES}/{size}{item['backdrop_path']}"
            for item in (data.get("results") or [])
            if item.get("backdrop_path")
        ][:limit]

        if found:
            _cache = (time.time(), found)
        return found


tmdb = TmdbIntegration()

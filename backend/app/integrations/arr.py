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
    def __init__(
        self, name: str, label: str, path: str, id_param: str, slug_field: str,
        alt_id_param: str | None = None, id_name: str = "", alt_id_name: str = "",
    ) -> None:
        self.name = name
        self.label = label
        self.path = path  # "movie" or "series"
        self.id_param = id_param  # "tmdbId" or "tvdbId"
        self.slug_field = slug_field  # which column caches the slug
        self.alt_id_param = alt_id_param
        """A second id to try, where the service will filter on one. Radarr
        takes imdbId as well as tmdbId; Sonarr's series endpoint takes only
        tvdbId, so it has none and nothing changes for it."""

        self.id_name = id_name or id_param
        self.alt_id_name = alt_id_name or (alt_id_param or "")
        """What to call them in a message. "TMDB id" reads to a person;
        "tmdbId" reads to whoever wrote the query string."""

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


    # ---- replacing a file ------------------------------------------------------
    # Non-destructive only: ask for a search, or tag the title. Neither deletes
    # the current file; a search only grabs something the quality profile
    # rates higher.

    REPLACE_TAG = "cartographarr-replace"

    async def _send(self, method: str, path: str, body: object) -> object:
        import httpx

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.request(method, f"{self.base_url}{path}", headers=self.headers, json=body)
            response.raise_for_status()
            return response.json() if response.content else None

    async def _by(self, param: str, value: str) -> dict | None:
        found = await get_json(
            f"{self.base_url}/api/v3/{self.path}", headers=self.headers, params={param: value}
        )
        items = found if isinstance(found, list) else [found]
        return next((i for i in items if isinstance(i, dict) and i.get("id")), None)

    async def find(self, external_id: str, alt_id: str | None = None) -> dict | None:
        """The movie or series, by the id Plex matched it to, then by the other.

        Two ids because they disagree. Plex matched a film to one Hamlet from
        2024 and the library holds another, and either agreeing is enough to
        find it. One extra request, on a path somebody has already clicked.
        """
        found = await self._by(self.id_param, external_id)
        if found is None and alt_id and self.alt_id_param:
            found = await self._by(self.alt_id_param, alt_id)
        return found

    def _missing(self, external_id: str, alt_id: str | None = None) -> LookupError:
        """Why it was not found, naming what was looked for.

        "Not in Radarr" about a film plainly sitting in Radarr is true and
        useless. The id is the whole answer: seeing it is for a different film
        is a glance, and guessing why the app is wrong is an evening.
        """
        tried = f"{self.id_name} {external_id}"
        if alt_id and self.alt_id_param:
            tried += f" or {self.alt_id_name} {alt_id}"
        return LookupError(
            f"{self.label} has nothing under {tried}, which is what this file is matched to. "
            f"Either it was added to {self.label} under another id, or the match here is for a different title."
        )

    async def _episode_id(self, series_id: int, season: int, episode: int) -> int | None:
        episodes = await get_json(
            f"{self.base_url}/api/v3/episode", headers=self.headers, params={"seriesId": series_id, "seasonNumber": season}
        )
        return next((e["id"] for e in episodes or [] if e.get("episodeNumber") == episode), None)

    async def search(
        self, external_id: str, season: int | None = None, episode: int | None = None,
        alt_id: str | None = None,
    ) -> str:
        """Ask for a search for this movie, or this one episode."""
        found = await self.find(external_id, alt_id)
        if found is None:
            raise self._missing(external_id, alt_id)
        if self.path == "movie":
            await self._send("POST", "/api/v3/command", {"name": "MoviesSearch", "movieIds": [found["id"]]})
            return f"{self.label} is searching for {found.get('title')}"
        if season is None or episode is None:
            raise LookupError("Episode number unknown, so the episode cannot be searched for")
        episode_id = await self._episode_id(found["id"], season, episode)
        if episode_id is None:
            raise LookupError(f"{self.label} does not list S{season:02d}E{episode:02d}")
        await self._send("POST", "/api/v3/command", {"name": "EpisodeSearch", "episodeIds": [episode_id]})
        return f"{self.label} is searching for {found.get('title')} S{season:02d}E{episode:02d}"

    # ---- replacements: find, grab, follow, confirm or deny --------------------------

    async def locate(
        self, external_id: str, season: int | None, episode: int | None, alt_id: str | None = None,
    ) -> tuple[dict, int | None]:
        """The movie or series, and for Sonarr the episode id."""
        found = await self.find(external_id, alt_id)
        if found is None:
            raise self._missing(external_id, alt_id)
        if self.path == "movie":
            return found, None
        if season is None or episode is None:
            raise LookupError("Episode number unknown")
        episode_id = await self._episode_id(found["id"], season, episode)
        if episode_id is None:
            raise LookupError(f"{self.label} does not list S{season:02d}E{episode:02d}")
        return found, episode_id

    async def releases(self, arr_id: int, episode_id: int | None) -> list[dict]:
        """Every release the indexers offer. Slow: this is a live search."""
        params = {"movieId": arr_id} if self.path == "movie" else {"episodeId": episode_id}
        return await get_json(f"{self.base_url}/api/v3/release", headers=self.headers, params=params, timeout=120) or []

    async def grab(self, guid: str, indexer_id: int) -> dict:
        return await self._send("POST", "/api/v3/release", {"guid": guid, "indexerId": indexer_id}) or {}

    async def queue(self) -> list[dict]:
        data = await get_json(
            f"{self.base_url}/api/v3/queue", headers=self.headers,
            params={"pageSize": 500, "includeUnknownMovieItems" if self.path == "movie" else "includeUnknownSeriesItems": "false"},
        )
        return (data or {}).get("records") or [] if isinstance(data, dict) else data or []

    async def history(self, arr_id: int, episode_id: int | None) -> list[dict]:
        """What Radarr or Sonarr recorded for this movie or episode, newest
        first: grabbed, download failed, imported, deleted."""
        if self.path == "movie":
            data = await get_json(f"{self.base_url}/api/v3/history/movie", headers=self.headers, params={"movieId": arr_id})
        else:
            data = await get_json(
                f"{self.base_url}/api/v3/history/series", headers=self.headers,
                params={"seriesId": arr_id, "episodeId": episode_id},
            )
        records = data.get("records") if isinstance(data, dict) else data
        return sorted(records or [], key=lambda r: str(r.get("date") or ""), reverse=True)

    async def manual_import_candidates(self, download_id: str) -> list[dict]:
        return await get_json(
            f"{self.base_url}/api/v3/manualimport", headers=self.headers,
            params={"downloadId": download_id, "filterExistingFiles": "false"}, timeout=60,
        ) or []

    async def manual_import(self, files: list[dict], arr_id: int, episode_id: int | None, download_id: str) -> None:
        """Import the downloaded file, replacing the current one."""
        entries = []
        for f in files:
            entry = {
                "path": f.get("path"),
                "quality": f.get("quality"),
                "languages": f.get("languages"),
                "releaseGroup": f.get("releaseGroup"),
                "downloadId": download_id,
                "indexerFlags": f.get("indexerFlags", 0),
            }
            if self.path == "movie":
                entry["movieId"] = arr_id
            else:
                entry["seriesId"] = arr_id
                entry["episodeIds"] = [episode_id]
            entries.append(entry)
        await self._send("POST", "/api/v3/command", {"name": "ManualImport", "importMode": "auto", "files": entries})

    async def remove_from_queue(self, queue_id: int) -> None:
        """Delete the download and block the release, so it is not grabbed again."""
        import httpx

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.delete(
                f"{self.base_url}/api/v3/queue/{queue_id}", headers=self.headers,
                params={"removeFromClient": "true", "blocklist": "true"},
            )
            response.raise_for_status()

    async def current_file(self, arr_id: int, episode_id: int | None) -> dict | None:
        if self.path == "movie":
            movie = await get_json(f"{self.base_url}/api/v3/movie/{arr_id}", headers=self.headers)
            return (movie or {}).get("movieFile")
        episode = await get_json(f"{self.base_url}/api/v3/episode/{episode_id}", headers=self.headers)
        file_id = (episode or {}).get("episodeFileId")
        if not file_id:
            return None
        return await get_json(f"{self.base_url}/api/v3/episodefile/{file_id}", headers=self.headers)

    async def tag(self, external_id: str) -> str:
        """Add the cartographarr-replace tag to the movie or series."""
        found = await self.find(external_id)
        if found is None:
            raise LookupError(f"Not in {self.label}")
        tags = await get_json(f"{self.base_url}/api/v3/tag", headers=self.headers) or []
        tag = next((t for t in tags if str(t.get("label", "")).lower() == self.REPLACE_TAG), None)
        if tag is None:
            tag = await self._send("POST", "/api/v3/tag", {"label": self.REPLACE_TAG})
        ids_field = "movieIds" if self.path == "movie" else "seriesIds"
        await self._send("PUT", f"/api/v3/{self.path}/editor", {ids_field: [found["id"]], "tags": [tag["id"]], "applyTags": "add"})
        return f"Tagged {found.get('title')} {self.REPLACE_TAG} in {self.label}"


radarr = ArrIntegration(
    "radarr", "Radarr", "movie", "tmdbId", "radarr_slug",
    alt_id_param="imdbId", id_name="TMDB id", alt_id_name="IMDb id",
)
# Sonarr's series endpoint filters on tvdbId alone, so there is no second
# id to try and nothing here changes for it.
sonarr = ArrIntegration("sonarr", "Sonarr", "series", "tvdbId", "sonarr_slug", id_name="TVDB id")


def for_media_type(media_type: str | None) -> ArrIntegration:
    """Films go to Radarr, everything episodic to Sonarr."""
    return sonarr if media_type in ("show", "season", "episode") else radarr


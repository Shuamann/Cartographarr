"""Tautulli API client.

Tautulli's API is one endpoint with a `cmd` parameter, so this is one method.
No per-command wrapper classes; callers pass the command name.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings
from app.redact import redact


class TautulliError(RuntimeError):
    pass


def _api_url(base: str) -> str:
    base = base.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = f"http://{base}"
    return f"{base}/api/v2"


# Which address answered, shared by every client for a while. A client is
# made per request, and each used to try the local URL afresh, so where it is
# unreachable every call waited out the local timeout first.
_RESOLVED: dict[tuple[str, str], tuple[str, float]] = {}
RESOLVE_SECONDS = 600


class TautulliClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        settings.require_tautulli()
        self._api_key = settings.tautulli_api_key
        self._remote = _api_url(settings.tautulli_url)
        self._local = _api_url(settings.tautulli_local_url) if settings.tautulli_local_url else None
        self._local_timeout = settings.tautulli_local_timeout
        self._base: str | None = None if self._local else self._remote
        self._client = client or httpx.AsyncClient(
            timeout=settings.tautulli_timeout,
            verify=settings.tautulli_verify_ssl,
        )

    @property
    def base_url(self) -> str | None:
        """Which URL is in use. None until the first call resolves it."""
        return self._base

    async def _resolve(self) -> str:
        """Prefer the LAN URL, once, then remember the answer.

        A LAN address is faster and keeps traffic off the reverse proxy, but
        it's unreachable from anywhere else, so it gets one short-timeout
        try and the remote URL takes over for the life of the client.
        """
        if self._base is not None:
            return self._base
        import time

        key = (self._local or "", self._remote)
        known = _RESOLVED.get(key)
        if known is not None and time.monotonic() - known[1] < RESOLVE_SECONDS:
            self._base = known[0]
            return self._base
        try:
            await self._request(self._local, "status", timeout=self._local_timeout)
            self._base = self._local
        except Exception:
            self._base = self._remote
        _RESOLVED[key] = (self._base, time.monotonic())
        return self._base

    async def _request(self, base: str, cmd: str, timeout: float | None = None, **params: Any):
        query = {k: v for k, v in params.items() if v is not None}
        query.update(apikey=self._api_key, cmd=cmd, out_type="json")

        kwargs = {"timeout": timeout} if timeout is not None else {}
        try:
            resp = await self._client.get(base, params=query, **kwargs)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # The request URL carries the API key, and so does httpx's message.
            raise TautulliError(f"{cmd}: Tautulli answered {exc.response.status_code}") from None
        except httpx.HTTPError as exc:
            raise TautulliError(f"{cmd}: {type(exc).__name__} {redact(exc)}".strip()) from None

        response = resp.json().get("response") or {}
        if response.get("result") != "success":
            raise TautulliError(f"{cmd}: {response.get('message') or 'unknown error'}")
        return response.get("data")

    async def call(self, cmd: str, **params: Any) -> Any:
        """Run a Tautulli command, return its `data` payload.

        Tautulli answers 200 with the error in the body, so the result envelope
        is what gets checked, not the status code.
        """
        base = await self._resolve()
        try:
            return await self._request(base, cmd, **params)
        except TautulliError as exc:
            # A connection that failed may mean the remembered address has
            # stopped working; forget it so the next client checks again.
            if "Error" in str(exc) or "answered 5" in str(exc):
                _RESOLVED.pop((self._local or "", self._remote), None)
            raise

    async def aclose(self) -> None:
        await self._client.aclose()

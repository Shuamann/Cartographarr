"""What every integration has to answer.

Deliberately small. An integration says whether it is configured, whether it
can be reached, and nothing else is assumed about it, so adding one is a new
module rather than a change to anything that already works.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.redact import redact

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Health:
    ok: bool
    detail: str
    version: str | None = None


class Integration(Protocol):
    name: str
    label: str

    def configured(self) -> bool: ...

    async def health(self) -> Health: ...


async def get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, object] | None = None,
    timeout: float = 15.0,
):
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()


def describe_failure(exc: Exception) -> str:
    """Turn an exception into something worth showing a person."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return "Rejected the API key"
        if code == 404:
            return "Reached it, but that path is not there. Check the base URL."
        return f"Answered {code}"
    if isinstance(exc, httpx.ConnectError):
        return "Could not connect. Check the address and that it is running."
    if isinstance(exc, httpx.TimeoutException):
        return "Timed out"
    return redact(exc)

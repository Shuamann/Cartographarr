"""Keep credentials out of anything a person or a log file can read.

Tautulli takes its API key as a query parameter, so an HTTP error from it
carries the key in the URL, and error text travels: into API responses shown
on the page, into the Log, into container logs someone pastes into a forum.
Every error that might hold a URL goes through `redact()` first.
"""

from __future__ import annotations

import logging
import re

_SECRET_PARAM = re.compile(
    r"(?i)([?&](?:apikey|api_key|x-plex-token|token|access_token|password|pass|secret|key)=)[^&\s'\"#]+"
)
_BASIC_AUTH = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@")


def redact(text: object) -> str:
    """The text with secret query values and user:password@ credentials hidden."""
    s = str(text)
    s = _SECRET_PARAM.sub(r"\1***", s)
    return _BASIC_AUTH.sub(r"\1***@", s)


class RedactingFilter(logging.Filter):
    """Applied to the root handlers, so a library logging a full URL (httpx
    does at debug level) cannot write a key to the container log."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a bad format string is not ours to fix
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            text = str(exc)
            if redact(text) != text:
                # The traceback would print the key; keep the type and a clean message.
                record.msg = f"{record.msg} ({type(exc).__name__}: {redact(text)})"
                record.exc_info = None
                record.exc_text = None
        return True


def install() -> None:
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())

"""Show URLs that hold credentials without showing the credentials.

Apprise, webhook and push URLs carry tokens and passwords in the URL itself.
Masking the whole setting meant retyping every URL to change one. Instead each
URL keeps its shape (scheme, host, the start of each part) with the secret
parts replaced by ****, and on save any URL still showing a mask is swapped
back for the stored original it came from. Change one line, and only that
line needs typing out.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit

MASK = "****"
_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s,]+")


def _mask_part(part: str) -> str:
    if not part or "{" in part or len(part) <= 4:
        return part
    return part[:3] + MASK


def mask_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.netloc
    if "@" in host:
        host = MASK + "@" + host.rsplit("@", 1)[1]
    elif ":" in host and not host.rsplit(":", 1)[1].isdigit():
        # Not a port: a secret after the colon (tgram://bot123:token).
        host = _mask_part(host)
    elif "." not in host and ":" not in host:
        # Some schemes put an id where a host would be (discord://id/token).
        host = _mask_part(host)
    path = "/".join(_mask_part(seg) for seg in parts.path.split("/"))
    query = "&".join(
        f"{k}={v if '{' in v else MASK}" for k, v in parse_qsl(parts.query, keep_blank_values=True)
    )
    return f"{parts.scheme}://{host}{path}" + (f"?{query}" if query else "")


def mask(value: str | None) -> str:
    """Every URL in a setting masked, everything around them kept."""
    return _URL.sub(lambda m: mask_url(m.group(0)), value or "")


def restore(submitted: str | None, stored: str | None) -> str:
    """Put the stored originals back wherever a URL is still masked.

    Raises ValueError for a masked URL that matches nothing stored, which
    means part of one was edited while still masked."""
    originals: dict[str, list[str]] = {}
    for m in _URL.finditer(stored or ""):
        found = originals.setdefault(mask_url(m.group(0)), [])
        if m.group(0) not in found:
            found.append(m.group(0))
    wanted: dict[str, int] = {}
    for m in _URL.finditer(submitted or ""):
        if MASK in m.group(0):
            wanted[m.group(0)] = wanted.get(m.group(0), 0) + 1

    def swap(m: re.Match) -> str:
        url = m.group(0)
        if MASK not in url:
            return url
        choices = originals.get(url)
        if not choices:
            raise ValueError("A masked URL was changed. Replace the whole URL to change it.")
        if len(choices) > 1 and wanted.get(url) != len(choices):
            # Two saved URLs look the same masked and one was removed: which
            # one stays cannot be told, so ask rather than guess.
            raise ValueError("Two saved URLs look the same when masked. Retype the ones you want to keep.")
        return choices.pop(0) if len(choices) > 1 else choices[0]

    return _URL.sub(swap, submitted or "")

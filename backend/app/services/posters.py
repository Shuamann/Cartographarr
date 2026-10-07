"""Posters and backdrops kept on disk, at a few sizes rather than every size.

Every page asks for its pictures at the size it draws them: 46 wide in a
report, 92 in a row, 120 in a list, 200 on a wall, 300 in a panel. Kept at
each, one film's poster was five files, fetched five times. Kept at the next
size up of three, it is two at most, and the browser scales the rest.

The sizes are chosen for what they are shown at. 200 by 300 covers every
small poster on a screen with twice the pixels; 400 by 600 covers the panel
and the wall the same way; 960 by 540 is a backdrop that sits behind a scrim,
where nobody can see more. Each is stored as a JPEG at a quality that cannot
be told from the original at that size: a few kilobytes for a small poster,
tens for a backdrop.

The folder is a setting, so it can live somewhere other than the database:
on a container it is mapped like any other path. Only files with the names
this module gives are ever removed from it, so pointing it at a folder that
holds something else loses nothing.
"""

from __future__ import annotations

import io
import logging
import pathlib
import re
from typing import Any

log = logging.getLogger(__name__)

SMALL = (200, 300)
LARGE = (400, 600)
ART = (960, 540)

QUALITY = 80
"""JPEG quality for a kept picture. Past this the file grows faster than
anybody can see the difference; below it, edges in titles start to smear."""

SMALL_UP_TO = 120
"""Any poster asked for at this width or less is served the small one."""

_OURS = re.compile(r"^\d+-(small|large|art)\.jpg$")
_OLDER = re.compile(r"^\d+-\d+x\d+(-art)?\.(jpg|png)$")
"""Names older builds kept, one per size asked for. Not read any more."""


def bucket(width: int, height: int, kind: str) -> tuple[str, int, int]:
    """The size a request is served at: (name, width, height)."""
    if kind == "art":
        return ("art", *ART)
    if width <= SMALL_UP_TO and height <= SMALL_UP_TO * 1.5:
        return ("small", *SMALL)
    return ("large", *LARGE)


def folder() -> tuple[pathlib.Path, str | None]:
    """Where posters are kept, and why it is not where it was asked to be.

    A configured folder that does not exist is passed over for the data
    directory. Inside a container a missing folder means a path that was never
    mapped, and creating it would keep posters in the container itself, gone
    on the next update.
    """
    from app.settings_store import current

    settings = current()
    default = pathlib.Path(settings.data_dir) / "posters"
    asked = (settings.poster_cache_dir or "").strip()
    if not asked:
        return default, None
    chosen = pathlib.Path(asked)
    if not chosen.is_dir():
        return default, f"{asked} does not exist, so posters are kept in {default} instead"
    return chosen, None


def enabled() -> bool:
    from app.settings_store import current

    return bool(current().poster_cache)


def path_for(rating_key: int, size: str) -> pathlib.Path:
    return folder()[0] / f"{rating_key}-{size}.jpg"


def shrink(content: bytes, width: int, height: int) -> tuple[bytes, str | None]:
    """The picture as a JPEG no larger than the size given.

    Returns the bytes and their type, or the original bytes and None when
    they could not be read as a picture: an answer that cannot be improved is
    passed on as it came rather than lost.
    """
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - a dependency, but not a reason to fail
        return content, None
    try:
        with Image.open(io.BytesIO(content)) as picture:
            picture.load()
            if picture.mode != "RGB":
                # A poster with transparency is laid on black, which is what
                # every surface it is shown on is near.
                flat = Image.new("RGB", picture.size)
                rgba = picture.convert("RGBA")
                flat.paste(rgba, mask=rgba.getchannel("A"))
                picture = flat
            picture.thumbnail((width, height), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            picture.save(out, "JPEG", quality=QUALITY, optimize=True, progressive=True)
    except Exception:  # noqa: BLE001 - anything unreadable goes through untouched
        log.debug("could not re-encode a poster; passing it on as it came")
        return content, None
    shrunk = out.getvalue()
    # A small JPEG from Plex can already be smaller than this would make it.
    if len(shrunk) >= len(content) and content[:3] == b"\xff\xd8\xff":
        return content, "image/jpeg"
    return shrunk, "image/jpeg"


def _files(where: pathlib.Path, pattern: re.Pattern[str]) -> list[pathlib.Path]:
    try:
        return [p for p in where.iterdir() if p.is_file() and pattern.match(p.name)]
    except OSError:
        return []


def stats() -> dict[str, Any]:
    """What is kept and where, for Settings."""
    where, why = folder()
    kept = _files(where, _OURS)
    size = 0
    for p in kept:
        try:
            size += p.stat().st_size
        except OSError:
            pass
    return {
        "enabled": enabled(),
        "folder": str(where),
        "note": why,
        "files": len(kept),
        "bytes": size,
    }


def clear() -> int:
    """Remove every kept picture, and nothing else in the folder."""
    where, _ = folder()
    gone = 0
    for p in _files(where, _OURS) + _files(where, _OLDER):
        try:
            p.unlink()
            gone += 1
        except OSError:
            pass
    return gone


def forget_older() -> int:
    """Remove the per-size files older builds kept, which nothing reads now.

    Looked for in the data directory, where they were always kept, and in the
    configured folder in case it was pointed at the same place.
    """
    from app.settings_store import current

    places = {pathlib.Path(current().data_dir) / "posters", folder()[0]}
    gone = 0
    for where in places:
        for p in _files(where, _OLDER):
            try:
                p.unlink()
                gone += 1
            except OSError:
                pass
    if gone:
        log.info("removed %d posters kept at sizes no longer used", gone)
    return gone

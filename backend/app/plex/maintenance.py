"""Telling Plex that a file has changed under it.

Tidying rewrites a file in place. Until now nothing told Plex, so the server
went on reporting the track list, the size and the duration it read before the
rewrite, and the app's own page disagreed with Plex about a file the app had
just changed. Worse when a step repackages the container: the old file is
deleted and a new one written beside it with a different extension, and Plex
goes on listing a file that is not there until its own nightly scan. Somebody
pressing play gets an error about a file this app removed on purpose.

Two calls, and which ones depend on what changed.

A partial scan of the folder, `/library/sections/{id}/refresh?path=`, is what
finds a file whose name changed and loses the one that went. It is the same
call Plex's own "Scan Library Files" makes, limited to one directory, so it
costs a directory listing rather than a walk of thirty thousand files.

An analyse, `/library/metadata/{key}/analyze`, is what makes Plex re-read a
file whose name did not change. Plex has no reason to look at a file again
when its path is the same, which is exactly the case tidying leaves behind.

Deliberately not `refresh()`, which re-matches the item against the metadata
agent. Nothing about the match changed, and a re-match can quietly decide a
file is a different film.
"""

from __future__ import annotations

import logging
import posixpath
from typing import Any

log = logging.getLogger(__name__)


def section_of(rating_key: int) -> int | None:
    """Which Plex library an item belongs to, from what has been scanned."""
    from app.db import session_scope
    from app.models import MediaItem

    with session_scope() as db:
        item = db.get(MediaItem, rating_key)
        return item.section_id if item else None


def rescan(section_id: int, path: str | None = None) -> None:
    """Ask Plex to look at one folder, or at a whole library.

    The path is Plex's own, not this container's: it is the server that has to
    find the folder, and the two need not be mounted the same way.
    """
    from app.plex.server import server

    plex = server()
    for section in plex.library.sections():
        if int(section.key) == int(section_id):
            section.update(path=path)
            return
    log.warning("no Plex library numbered %s to scan", section_id)


def analyze(rating_key: int) -> None:
    """Ask Plex to read a file's streams again."""
    from app.plex.server import server

    plex = server()
    item = plex.fetchItem(int(rating_key))
    item.analyze()


def file_changed(rating_key: int | None, plex_path: str | None, renamed: bool) -> dict[str, Any]:
    """Tell Plex about one file this app has just rewritten.

    Never raises. A tidy that worked is not a tidy that failed because the
    server was restarting, and the nightly scan is still there as the floor:
    the worst case without this is the state everything was in before it
    existed.
    """
    done: dict[str, Any] = {"scanned": False, "analysed": False}
    if rating_key is None:
        return done
    section = section_of(rating_key)
    # Only when the name changed. Plex finds a file by walking the folder, so
    # a scan teaches it nothing about a file whose path it already has, and
    # asking for one on every tidy is a directory walk for no reason.
    if renamed and plex_path and section is not None:
        try:
            rescan(section, posixpath.dirname(plex_path.replace("\\", "/")))
            done["scanned"] = True
        except Exception as exc:  # noqa: BLE001 - the tidy itself worked
            log.warning("could not ask Plex to scan for %s: %s", plex_path, exc)
    try:
        analyze(rating_key)
        done["analysed"] = True
    except Exception as exc:  # noqa: BLE001 - as above
        log.warning("could not ask Plex to re-read %s: %s", rating_key, exc)
    return done

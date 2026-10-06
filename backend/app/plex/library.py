"""The library, read from Plex itself.

Deliberately the same rows the Tautulli scan produces, field for field, so the
upsert, the size history and every list built on media_items do not know or
care which source answered. Changing where the library comes from should not
change anything that reads it.

It also carries two things the Tautulli scan cannot. The IMDb, TMDB and TVDB
ids come in the listing, so deep links and request matching work on titles
nobody has played, rather than waiting for a play to fetch them one at a time.
And the file path comes with them, which the on-disk check and tidying are
built on.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.library_scan import _int, _resolution

log = logging.getLogger(__name__)

PAGE = 1000
"""Items per request. A library can be tens of thousands of titles, and plexapi
would otherwise ask for them a hundred at a time."""

GUIDS = (("imdb://", "imdb_id"), ("tmdb://", "tmdb_id"), ("tvdb://", "tvdb_id"))


def _first(items):
    return items[0] if items else None


def _still(item: Any) -> Any:
    """Stop plexapi fetching the whole item again to fill a blank.

    A listed item is a partial object, and plexapi reloads it from the server
    whenever anything read from it is empty: a film with no year, an episode
    with no external ids. Across a whole library that is one quiet request per
    such item, thousands of them, to learn that the blank really is blank.
    """
    try:
        item._autoReload = False
    except AttributeError:
        pass
    return item


def _ids(item: Any) -> dict[str, str | None]:
    """The external ids, from Plex's guids. One missing leaves only that one
    empty: an episode Plex matched on TVDB alone still has its TVDB id."""
    out: dict[str, str | None] = {key: None for _, key in GUIDS}
    for guid in getattr(item, "guids", None) or []:
        value = getattr(guid, "id", None)
        if not isinstance(value, str):
            continue
        for prefix, key in GUIDS:
            if value.startswith(prefix) and value[len(prefix):]:
                out[key] = value[len(prefix):]
    return out


def row(item: Any, section_id: int, show: Any = None) -> dict[str, Any] | None:
    """One media_items row, in the shape row_from_media_info makes, or None
    for anything that is not a file of its own."""
    _still(item)
    key = _int(getattr(item, "ratingKey", None))
    media_type = getattr(item, "type", None)
    if key is None or media_type not in ("movie", "episode"):
        return None
    episode = media_type == "episode"
    title = getattr(item, "title", None) or None
    show_title = (
        getattr(item, "grandparentTitle", None) or (getattr(show, "title", None) if show is not None else None)
    ) if episode else None
    # The first version when there are several, as the Tautulli scan does.
    # An item with no file still gets its row: the scan's sighting of it is
    # what keeps it counted as in the library.
    media = _first(getattr(item, "media", None) or [])
    part = _first(getattr(media, "parts", None) or []) if media is not None else None
    return {
        "rating_key": key,
        "parent_rating_key": _int(getattr(item, "parentRatingKey", None)) if episode else None,
        "grandparent_rating_key": (
            _int(getattr(item, "grandparentRatingKey", None))
            or (_int(getattr(show, "ratingKey", None)) if show is not None else None)
        ) if episode else None,
        "section_id": _int(getattr(item, "librarySectionID", None)) or section_id,
        "media_type": media_type,
        "title": title,
        "full_title": f"{show_title} - {title}" if show_title and title else title,
        "grandparent_title": show_title,
        "media_index": _int(getattr(item, "index", None)) if episode else None,
        "parent_media_index": _int(getattr(item, "parentIndex", None)) if episode else None,
        "year": _int(getattr(item, "year", None)),
        "thumb": getattr(item, "thumb", None) or None,
        "file_bitrate": _int(getattr(media, "bitrate", None)) if media is not None else None,
        "file_container": (
            getattr(media, "container", None) or (getattr(part, "container", None) if part is not None else None)
        ) if media is not None else None,
        "video_codec": (getattr(media, "videoCodec", None) or None) if media is not None else None,
        "video_resolution": _resolution(getattr(media, "videoResolution", None)) if media is not None else None,
        "audio_codec": (getattr(media, "audioCodec", None) or None) if media is not None else None,
        "audio_channels": _int(getattr(media, "audioChannels", None)) if media is not None else None,
        "file_size": _int(getattr(part, "size", None)) if part is not None else None,
        # What the Tautulli scan cannot give.
        "file_path": (getattr(part, "file", None) or None) if part is not None else None,
        "duration": _int(getattr(item, "duration", None)),
        **_ids(item),
    }


def section_rows(section: Any) -> list[dict[str, Any]]:
    """Every film or episode in one library. Music and photos give nothing,
    as they do in the Tautulli scan."""
    section_id = _int(getattr(section, "key", None))
    kind = getattr(section, "type", None)
    if section_id is None:
        return []
    out: list[dict[str, Any]] = []
    if kind == "movie":
        for item in section.all(container_size=PAGE):
            found = row(item, section_id)
            if found:
                out.append(found)
    elif kind == "show":
        for show in section.all(container_size=PAGE):
            _still(show)
            for item in show.episodes(container_size=PAGE):
                found = row(item, section_id, show)
                if found:
                    out.append(found)
    return out


def read() -> list[dict[str, Any]]:
    """Every movie and episode, as rows for the library scan.

    Blocking, because plexapi is. Call it in a worker thread.
    """
    from app.plex.server import server

    plex = server()
    rows: list[dict[str, Any]] = []
    for section in plex.library.sections():
        rows.extend(section_rows(section))
    return rows

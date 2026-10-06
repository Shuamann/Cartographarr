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

import json
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

# ---- the tracks in a file ----------------------------------------------------

DETAIL_BATCH = 100
"""Rating keys in one request.

Plex takes a comma separated list of them and answers for all of them at once,
with every audio and subtitle track. Measured against a real server: one key
at a time is 11 ms a file, a hundred at a time is 4. Tautulli has no batch form
at all, so the same work through it is one request per file and took 636 ms
each from here, which is the whole reason this exists.
"""

HDR = {"smpte2084": "HDR10", "arib-std-b67": "HLG"}
"""What the transfer characteristic means, in the words already stored.

Four values are in use in a real library: SDR, HDR10, Dolby Vision and Dolby
Vision/HDR10. They are Tautulli's words, four years of rows already use them,
and the rules and reports people have written match on them, so they are not
up for improvement.
"""


def _range(stream: Any) -> str | None:
    """SDR, HDR10, HLG, Dolby Vision, or both at once.

    Read off real files rather than guessed: every one of the 236 files in this
    library that Tautulli called anything other than SDR was checked against
    what Plex says about the same file, and this is the rule that reproduces
    all four answers.
    """
    if stream is None:
        return None
    dolby = bool(getattr(stream, "DOVIPresent", None))
    kind = HDR.get(str(getattr(stream, "colorTrc", "") or "").lower())
    if dolby and kind:
        return f"Dolby Vision/{kind}"
    if dolby:
        return "Dolby Vision"
    return kind or "SDR"


def _extra(track: dict, stream: Any, fields: tuple[tuple[str, str], ...]) -> dict:
    """Add what Plex happened to say, and nothing for what it did not.

    Plex leaves these out rather than sending a no, so leaving them out here
    keeps that meaning exactly. It also matters for size: most tracks are not
    forced, not for the hard of hearing and have no name, and writing all that
    down as false against every track in a library of thirty thousand files is
    tens of megabytes to say nothing.
    """
    for name, key in fields:
        value = getattr(stream, name, None)
        if value is None or value == "" or value is False:
            continue
        track[key] = _int(value) if key in ("sample_rate", "bit_depth") else (
            True if value is True else str(value)
        )
    return track


AUDIO_EXTRA = (
    # How the channels are actually laid out, where the count alone does not
    # say: 5.1(side) and 5.1(rear) are both six.
    ("audioChannelLayout", "layout"),
    ("profile", "profile"),
    ("samplingRate", "sample_rate"),
    ("bitDepth", "bit_depth"),
    # The one a player picks when nobody chooses, which is the whole question
    # behind somebody watching a film in the wrong language.
    ("default", "default"),
    # The track's own name in the file: "Commentary", "Director's cut".
    ("title", "title"),
)

SUBTITLE_EXTRA = (
    # Subtitles for the hard of hearing, which carry sound effects and speaker
    # names. Somebody who wants plain subtitles does not want these, and until
    # now nothing could tell them apart.
    ("hearingImpaired", "sdh"),
    # Subtitles written to match a dub rather than the original audio.
    ("dub", "dub"),
    ("original", "original"),
    ("default", "default"),
    ("title", "title"),
)


def _tracks(part: Any) -> tuple[list[dict], list[dict], Any]:
    """The audio and subtitle tracks, and the video stream, from one file."""
    audio: list[dict] = []
    subtitles: list[dict] = []
    video = None
    for stream in getattr(part, "streams", None) or []:
        kind = getattr(stream, "streamType", None)
        if kind == 1:
            video = video or stream
        elif kind == 2:
            audio.append(_extra({
                "codec": getattr(stream, "codec", None) or None,
                "channels": _int(getattr(stream, "channels", None)),
                "language": getattr(stream, "languageCode", None) or getattr(stream, "language", None) or None,
                "bitrate": _int(getattr(stream, "bitrate", None)),
            }, stream, AUDIO_EXTRA))
        elif kind == 3:
            subtitles.append(_extra({
                "codec": getattr(stream, "codec", None) or None,
                "language": getattr(stream, "languageCode", None) or getattr(stream, "language", None) or None,
                # Plex only says forced when it is, which is not the same as
                # saying it is not, but the column has always been a yes or no.
                "forced": bool(getattr(stream, "forced", False)),
                # A subtitle beside the file is fetched by its own key. One
                # inside the file has none. Checked against 1,100 tracks
                # Tautulli had already described: no exceptions.
                "location": "external" if getattr(stream, "key", None) else "embedded",
            }, stream, SUBTITLE_EXTRA))
    return audio, subtitles, video


def detail_row(item: Any) -> dict[str, Any]:
    """One media_items row with the file's tracks, in metadata_row's shape."""
    _still(item)
    media = getattr(item, "media", None) or []
    first = _first(media)
    part = _first(getattr(first, "parts", None) or []) if first is not None else None
    audio, subtitles, video = _tracks(part) if part is not None else ([], [], None)
    show_title = getattr(item, "grandparentTitle", None) or None
    title = getattr(item, "title", None) or None
    return {
        "rating_key": _int(getattr(item, "ratingKey", None)),
        "parent_rating_key": _int(getattr(item, "parentRatingKey", None)),
        "grandparent_rating_key": _int(getattr(item, "grandparentRatingKey", None)),
        "section_id": _int(getattr(item, "librarySectionID", None)),
        "media_type": getattr(item, "type", None) or None,
        "title": title,
        "full_title": f"{show_title} - {title}" if show_title and title else title,
        "grandparent_title": show_title,
        "parent_media_index": _int(getattr(item, "parentIndex", None)),
        "media_index": _int(getattr(item, "index", None)),
        "year": _int(getattr(item, "year", None)),
        "thumb": getattr(item, "thumb", None) or None,
        "grandparent_thumb": getattr(item, "grandparentThumb", None) or None,
        "parent_thumb": getattr(item, "parentThumb", None) or None,
        "art": getattr(item, "art", None) or None,
        "duration": _int(getattr(item, "duration", None)),
        "content_rating": getattr(item, "contentRating", None) or None,
        "summary": getattr(item, "summary", None) or None,
        "file_bitrate": _int(getattr(first, "bitrate", None)) if first is not None else None,
        "file_container": (
            getattr(first, "container", None) or (getattr(part, "container", None) if part is not None else None)
        ) if first is not None else None,
        "file_size": _int(getattr(part, "size", None)) if part is not None else None,
        "file_path": (getattr(part, "file", None) or None) if part is not None else None,
        "versions": len(media) or None,
        "video_codec": (
            (getattr(video, "codec", None) if video is not None else None)
            or (getattr(first, "videoCodec", None) if first is not None else None)
            or None
        ),
        "video_resolution": _resolution(getattr(first, "videoResolution", None)) if first is not None else None,
        "video_bit_depth": _int(getattr(video, "bitDepth", None)) if video is not None else None,
        "video_dynamic_range": _range(video),
        "audio_codec": (getattr(first, "audioCodec", None) or None) if first is not None else None,
        "audio_channels": _int(getattr(first, "audioChannels", None)) if first is not None else None,
        "audio_tracks": json.dumps(audio) if media else None,
        "subtitle_tracks": json.dumps(subtitles) if media else None,
        **_ids(item),
    }


def details(keys: list[int]) -> list[dict[str, Any]]:
    """Every track in each of these files, a hundred files a request.

    A key Plex no longer knows simply does not come back, and gets the same
    empty row the Tautulli path gives it, so a deleted item is not asked about
    again on every sync.

    Blocking, because plexapi is. Call it in a worker thread.
    """
    from app.plex.server import server

    plex = server()
    out: list[dict[str, Any]] = []
    answered: set[int] = set()
    for start in range(0, len(keys), DETAIL_BATCH):
        chunk = keys[start:start + DETAIL_BATCH]
        if not chunk:
            continue
        path = "/library/metadata/" + ",".join(str(k) for k in chunk)
        try:
            found = plex.fetchItems(path)
        except Exception as exc:  # noqa: BLE001 - one bad batch should not stop the rest
            log.warning("could not read details for %d items: %s", len(chunk), exc)
            continue
        for item in found:
            row = detail_row(item)
            if row["rating_key"] is None:
                continue
            answered.add(row["rating_key"])
            out.append(row)
    out.extend({"rating_key": key} for key in keys if key not in answered)
    return out

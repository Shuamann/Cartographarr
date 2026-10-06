"""Do the two sources actually say the same thing?

Switching where the data comes from is the one change in this app where
everything can look normal and be wrong. The rows keep arriving, the pages
keep drawing, and a field that is quietly missing shows as a blank rather than
as an error.

Counting is not enough. A total agreeing says nothing about whether the right
value reached the right column, which is exactly how the transcode decision
nearly went wrong: both sources reported a stream, and one called it a copy
where the other called it a transcode, and every rule anybody had written
matches on that word.

So this asks both sources about the same things and compares them field by
field: the same files, and the same streams where anything is playing. It
names the fields that disagree and the fields one source leaves empty, rather
than returning a score.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

SAMPLE = 25
"""How many files to ask both sources about.

Each one is a request to Tautulli, which has no batch form, so this is the
number that keeps the whole check under a few seconds. It is a sample and says
so: it is looking for a field that is wrong everywhere, which shows up in the
first few, not for the one item in ten thousand that differs.
"""

# Worth comparing, and why each one: these are the fields pages draw, rules
# match on, and the tidy decides from.
FILE_FIELDS = (
    "title", "year", "media_type", "file_container", "file_size", "file_bitrate",
    "video_codec", "video_resolution", "video_bit_depth", "video_dynamic_range",
    "audio_codec", "audio_channels", "imdb_id", "tmdb_id", "tvdb_id", "duration",
)

STREAM_FIELDS = (
    # The one the whole session is judged by, and the one that nearly went
    # wrong, so it is first.
    "transcode_decision", "video_decision", "audio_decision",
    "user_id", "machine_id", "ip_address", "location", "media_type", "rating_key",
    "video_codec", "audio_codec", "container", "quality_profile", "state",
)


def _same(a: Any, b: Any) -> bool:
    """Equal once both are read as text, since one source answers in numbers
    and the other in strings for the same fact."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return str(a).strip().lower() == str(b).strip().lower()


def _compare(fields, ours: dict, theirs: dict, differ, blank_here, blank_there) -> None:
    for field in fields:
        mine, other = ours.get(field), theirs.get(field)
        if _same(mine, other):
            continue
        if mine in (None, "") and other not in (None, ""):
            blank_here.setdefault(field, 0)
            blank_here[field] += 1
        elif other in (None, "") and mine not in (None, ""):
            blank_there.setdefault(field, 0)
            blank_there[field] += 1
        else:
            differ.setdefault(field, []).append({"plex": mine, "tautulli": other})


async def files(client, sample: int = SAMPLE) -> dict[str, Any]:
    """The same files, read from both, compared field by field."""
    import asyncio

    from sqlalchemy import select

    from app.db import session_scope
    from app.models import MediaItem
    from app.plex import library as plex_library
    from app.services.sync import metadata_row

    with session_scope() as db:
        keys = [
            k for (k,) in db.execute(
                select(MediaItem.rating_key)
                .where(MediaItem.media_type.in_(("movie", "episode")), MediaItem.file_path.is_not(None))
                .order_by(MediaItem.rating_key)
                .limit(sample)
            ).all()
        ]
    if not keys:
        return {"asked": False, "reason": "nothing in the library to compare yet"}

    mine = {row["rating_key"]: row for row in await asyncio.to_thread(plex_library.details, keys)}
    differ: dict[str, list] = {}
    blank_plex: dict[str, int] = {}
    blank_tautulli: dict[str, int] = {}
    compared = 0
    for key in keys:
        theirs = await metadata_row(client, key)
        ours = mine.get(key) or {}
        if not theirs.get("title") or not ours.get("title"):
            continue
        compared += 1
        _compare(FILE_FIELDS, ours, theirs, differ, blank_plex, blank_tautulli)

    return {
        "asked": True,
        "compared": compared,
        "fields": len(FILE_FIELDS),
        "differ": {f: v[:3] for f, v in differ.items()},
        "differ_counts": {f: len(v) for f, v in differ.items()},
        "empty_from_plex": blank_plex,
        "empty_from_tautulli": blank_tautulli,
    }


async def streams(client) -> dict[str, Any]:
    """Whatever is playing, read from both, compared field by field.

    Only possible while somebody is watching, which is said plainly rather
    than reported as agreement.
    """
    import asyncio

    from app.plex import activity as plex_activity

    mine = await asyncio.to_thread(plex_activity.read)
    ours = {str(s.get("session_key")): s for s in mine.get("sessions") or []}
    answer = await client.call("get_activity") or {}
    theirs = {str(s.get("session_key")): s for s in (answer.get("sessions") or [])}

    shared = sorted(set(ours) & set(theirs))
    if not shared:
        return {
            "asked": False,
            "reason": "nothing is playing, so there are no streams to compare",
            "plex_streams": len(ours),
            "tautulli_streams": len(theirs),
        }

    differ: dict[str, list] = {}
    blank_plex: dict[str, int] = {}
    blank_tautulli: dict[str, int] = {}
    for key in shared:
        _compare(STREAM_FIELDS, ours[key], theirs[key], differ, blank_plex, blank_tautulli)

    return {
        "asked": True,
        "compared": len(shared),
        "only_plex": sorted(set(ours) - set(theirs)),
        "only_tautulli": sorted(set(theirs) - set(ours)),
        "differ": {f: v[:3] for f, v in differ.items()},
        "differ_counts": {f: len(v) for f, v in differ.items()},
        "empty_from_plex": blank_plex,
        "empty_from_tautulli": blank_tautulli,
    }

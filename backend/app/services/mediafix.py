"""Tidying a file's tracks with ffmpeg, in this container.

What the Library finds wrong with a file is mostly not the video: styled
subtitles that make a television burn them in, a pile of duplicate subtitle
tracks, audio no common device can decode, a container from another decade.
All of those are fixable without re-encoding the picture, which means minutes
and no loss of quality.

Two halves, deliberately:

- **The plan** is worked out from what has already been read into the database,
  so it can be shown on a file card whether or not the media is mounted here
  and whether or not ffmpeg is installed. It is an answer to "what would this
  do", in words.
- **The command** is built at the moment of running, from ffprobe's own stream
  list, because mapping streams needs their real indexes and the database's
  summary is not that.

Nothing here re-encodes video. Anything that would is Tdarr's job.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from pathlib import PurePosixPath
from typing import Any

from app.settings_store import current

IMAGE_SUBTITLES = {"pgs", "hdmv_pgs_subtitle", "vobsub", "dvd_subtitle", "dvb_subtitle"}
STYLED_SUBTITLES = {"ass", "ssa"}
PLAYABLE_AUDIO = {"aac", "ac3", "eac3", "mp3", "opus"}
MODERN_CONTAINERS = {"mkv", "mp4", "m4v"}


def tools() -> dict[str, Any]:
    """Which of ffmpeg and ffprobe this container has, and their versions."""
    found: dict[str, Any] = {}
    for name in ("ffmpeg", "ffprobe"):
        path = shutil.which(name)
        version = None
        if path:
            try:
                first = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=10).stdout
                version = first.splitlines()[0] if first else None
            except (OSError, subprocess.SubprocessError):
                version = None
        found[name] = {"path": path, "version": version}
    found["ready"] = bool(found["ffmpeg"]["path"] and found["ffprobe"]["path"])
    return found


def path_map() -> list[tuple[str, str]]:
    """How the paths Plex reports line up with this container's mounts.

    Empty, which is the normal case, means they are the same: mount the shares
    at the paths Plex already uses and there is nothing to configure.
    """
    raw = (current().media_path_map or "").strip()
    pairs = []
    for part in raw.replace(";", ",").split(","):
        if "=" in part:
            plex, _, here = part.partition("=")
            if plex.strip() and here.strip():
                pairs.append((plex.strip(), here.strip()))
    return pairs


def roots() -> list[str]:
    """The mounted directories to look under, in the order they were given."""
    raw = (current().media_roots or "").strip()
    return [part.strip().rstrip("/") for part in raw.replace(";", ",").split(",") if part.strip()]


_found: dict[str, str] = {}
_found_for: tuple[tuple[str, ...], tuple[tuple[str, str], ...]] | None = None
"""Where each Plex library turned out to live in this container.

Worked out once per library by trying, then kept, because the answer is the
same for every file in it and the alternative is several stat calls a file on a
page listing two hundred. Thrown away whenever the settings it was derived from
change, so a wrong guess is never kept past the fix."""


_missed: dict[str, int] = {}
"""How many times a library has been searched for and not found.

A search walks the roots, so it cannot happen once a file. But giving up after
one is worse: the file it searched for may be the one that was deleted this
morning, and a library is not missing because one film is. So a few goes with
different files, then it stops asking. Thrown away with the rest of the memory
whenever the settings change."""

SEARCH_TRIES = 3
"""Files tried for one library before the roots are left alone. Three stale
paths in a row is a library that has moved, not a coincidence."""


def _memory() -> dict[str, str]:
    global _found, _found_for
    now = (tuple(roots()), tuple(path_map()))
    if now != _found_for:
        _found, _found_for = {}, now
        _missed.clear()
    return _found


def library_of(file_path: str) -> str:
    """The top directory of a path, which is the library as Plex reports it."""
    plex_path = PurePosixPath(file_path.replace("\\", "/"))
    parts = plex_path.parts
    if len(parts) > 2 and parts[0] == "/":
        return "/" + parts[1]
    return str(plex_path.parent)


def _guesses(file_path: str) -> list[str]:
    """Every place this file might be, best first."""
    plex_path = PurePosixPath(file_path.replace("\\", "/"))
    library = library_of(file_path)
    tail = plex_path.relative_to(library)
    found = _memory()

    first: list[str] = []
    known = found.get(library)
    if known:
        first.append(str(PurePosixPath(known) / tail))
    for plex, here in path_map():
        if file_path.startswith(plex):
            first.append(str(PurePosixPath(here) / plex_path.relative_to(plex)))

    rest = [file_path]
    for root in roots():
        # A root holding the libraries, then a root that is the library.
        rest.append(str(PurePosixPath(root) / str(plex_path).lstrip("/")))
        rest.append(str(PurePosixPath(root) / tail))
    seen: set[str] = set()
    return [c for c in [*first, *rest] if not (c in seen or seen.add(c))]


SEARCH_WIDTH = 400
"""Directories examined at one level under a root. A share with more than this
many folders at its top is not a media root, it is a mistake."""

SEARCH_DEPTH = 2
"""How far below a root a library may sit. /media/Films is one, and
/media/Archive/Films is two, which covers a share mounted whole."""

SEARCH_SECONDS = 2.0
"""How long one library may be looked for before the search gives up.

The width and depth caps bound how many directories are examined, which is the
wrong thing to bound: the same seven thousand filesystem calls are thirty
milliseconds on a local disk and several seconds on a mounted remote share,
where every one of them is a round trip. A deadline bounds the part that
varies. Giving up is not a failure: the library is reported missing, which is
honest, and the path box in Settings is there to be told the answer."""


def _search(library: str, tail: str) -> str | None:
    """Look under the roots for the directory this library lives in.

    Plex reports the path its own container sees, and that container maps its
    shares however it likes: a library Plex calls /movies can be /media/Films
    here, sharing no name with anything. So when the names do not line up, the
    question asked is not "is there a directory called movies" but "which
    directory under these roots has this film in it", which has one answer and
    does not care what anything is called.

    It asks for the film's own folder rather than the file, because the file is
    the part that gets renamed, re-encoded or deleted while the folder stays.
    Finding the folder settles where the library lives even when that one file
    is gone, and the caller is told None for the file either way.
    """
    import os
    import time

    if _missed.get(library, 0) >= SEARCH_TRIES:
        return None

    # "A Film (2026)" out of "A Film (2026)/A Film (2026).mkv".
    head = tail.split("/")[0]
    deadline = time.monotonic() + SEARCH_SECONDS

    for root in roots():
        frontier = [root]
        for _ in range(SEARCH_DEPTH):
            below: list[str] = []
            for here in frontier:
                if time.monotonic() > deadline:
                    _missed[library] = _missed.get(library, 0) + 1
                    return None
                try:
                    with os.scandir(here) as entries:
                        children = [
                            entry.path.replace("\\", "/")
                            for entry in entries
                            if not entry.name.startswith(".") and entry.is_dir()
                        ]
                except OSError:
                    continue
                for n, child in enumerate(children[:SEARCH_WIDTH]):
                    # Checked every so often rather than every time, because
                    # the clock is not free either and a local pass does
                    # thousands of these.
                    if n % 64 == 0 and time.monotonic() > deadline:
                        _missed[library] = _missed.get(library, 0) + 1
                        return None
                    if os.path.exists(f"{child}/{head}"):
                        _memory()[library] = child
                        _missed.pop(library, None)
                        found = f"{child}/{tail}"
                        return found if os.path.exists(found) else None
                    below.append(child)
            frontier = below

    _missed[library] = _missed.get(library, 0) + 1
    return None


def root_status() -> list[dict[str, Any]]:
    """Whether each mounted directory is there, and what is inside it.

    The one thing a person setting a mount cannot see from outside. A root that
    is empty, missing or unreadable is a different problem from a root whose
    names do not match, and saying which is most of the help.
    """
    import os

    rows = []
    for root in roots():
        names: list[str] = []
        problem = None
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    if entry.name.startswith("."):
                        continue
                    try:
                        if entry.is_dir():
                            names.append(entry.name)
                    except OSError:
                        continue
                    if len(names) >= 30:
                        break
        except OSError as err:
            problem = err.strerror or str(err)
        rows.append({
            "path": root,
            "exists": os.path.isdir(root),
            "contains": sorted(names, key=str.lower),
            "error": problem,
        })
    return rows


def local_path(file_path: str | None) -> str | None:
    """Where this container can read that file, or None if it cannot.

    In order: wherever this library was last found, anything media_path_map
    says, the path exactly as Plex gives it, then that path hung under each
    media root with and without its library name. Failing all of that, the
    roots are walked looking for a directory that holds the file, because a
    library's name here need not be its name in Plex. The first hit wins.
    """
    import os

    if not file_path:
        return None
    library = library_of(file_path)
    tail = str(PurePosixPath(file_path.replace("\\", "/")).relative_to(library))
    for candidate in _guesses(file_path):
        if os.path.exists(candidate):
            if candidate.endswith(tail):
                home = candidate[: -len(tail)].rstrip("/")
                if home and home != library:
                    _memory()[library] = home
            return candidate
    return _search(library, tail)


def where_libraries(paths: list[str]) -> list[dict[str, Any]]:
    """For each library among these files, where it was found and how.

    This is what Settings shows instead of asking somebody to work out a path
    map: one row per library Plex reports, saying either the directory it was
    found in or that it was not found at all.
    """
    import os

    by_library: dict[str, list[str]] = {}
    for path in paths:
        by_library.setdefault(library_of(path), []).append(path)

    rows = []
    for library, files in sorted(by_library.items()):
        # Several files, because the newest one in a library is the one most
        # likely to have been moved since the scan read it.
        here = None
        for path in files[:SEARCH_TRIES + 1]:
            here = local_path(path)
            if here or _memory().get(library):
                break
        home = _memory().get(library)
        if here and not home:
            tail = str(PurePosixPath(files[0].replace("\\", "/")).relative_to(library))
            home = here[: -len(tail)].rstrip("/") if here.endswith(tail) else None
        rows.append({
            "library": library,
            "here": home or (library if here else None),
            # Where it lives is the question, not whether one sampled file is
            # still there: a library found with a stale file is still found.
            "found": bool(here or home),
            "files": len(files),
            "mapped": any(library.startswith(plex) or plex.startswith(library) for plex, _ in path_map()),
            "example": files[0],
            "exists": bool(here) or os.path.isdir(library),
        })
    return rows


def _tracks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
    except ValueError:
        return []
    return parsed if isinstance(parsed, list) else []


def _codec(track: dict[str, Any]) -> str:
    return str(track.get("codec") or "").lower()


def languages(setting: str) -> list[str]:
    """A comma separated list of language codes, tidied."""
    return [part.strip().lower() for part in (setting or "").replace(";", ",").split(",") if part.strip()]


def plan(item: Any) -> dict[str, Any]:
    """What tidying this file would do, in words, from what is already known.

    Each step names the finding it answers, so the card can line them up with
    what it already says is wrong. Nothing here touches the picture.
    """
    audio = _tracks(getattr(item, "audio_tracks", None))
    subs = [s for s in _tracks(getattr(item, "subtitle_tracks", None)) if s.get("location") != "external"]
    container = str(getattr(item, "file_container", "") or "").lower()
    steps: list[dict[str, str]] = []

    styled = [s for s in subs if _codec(s) in STYLED_SUBTITLES]
    if styled:
        steps.append({
            "key": "styled_subtitles",
            "what": f"Convert {len(styled)} styled subtitle track{'s' if len(styled) != 1 else ''} to SRT",
            "why": "Televisions and sticks burn styled subtitles in, which turns a direct play into a transcode. "
                   "The words survive; the fonts and positioning do not.",
        })

    text_languages = {str(s.get("language") or "").lower() for s in subs if _codec(s) not in IMAGE_SUBTITLES}
    spare_images = [s for s in subs if _codec(s) in IMAGE_SUBTITLES
                    and str(s.get("language") or "").lower() in text_languages]
    if spare_images:
        steps.append({
            "key": "image_subtitles_only",
            "what": f"Drop {len(spare_images)} picture subtitle track{'s' if len(spare_images) != 1 else ''} "
                    f"that already {'have' if len(spare_images) != 1 else 'has'} a text version",
            "why": "Picture subtitles can only be burned in. Where the same language exists as text, the picture "
                   "one is a transcode waiting to happen. Any without a text version are left alone.",
        })

    groups = Counter((_codec(s), str(s.get("language") or ""), bool(s.get("forced"))) for s in subs)
    duplicates = sum(n - 1 for n in groups.values() if n > 1)
    if duplicates >= 2:
        steps.append({
            "key": "subtitle_clutter",
            "what": f"Drop {duplicates} duplicate subtitle tracks, keeping the first of each kind",
            "why": "A list of twenty tracks that are the same handful repeated is a menu nobody can use.",
        })

    if audio and not {_codec(a) for a in audio} & PLAYABLE_AUDIO:
        steps.append({
            "key": "no_compatible_audio",
            "what": "Add an AC3 track beside the original audio",
            "why": "Nothing here can be played by most televisions, sticks and browsers, so Plex converts the audio "
                   "for them, and some clients convert the picture too. The original track is kept.",
        })

    # Offered on anything without one already, rather than only on a file
    # something is wrong with. A surround track is the usual reason a phone or
    # a browser converts the audio, and the fix is not to throw the surround
    # away: it is to put a small stereo track beside it and let each client
    # take the one it wants.
    if audio and not any(_codec(a) == "aac" and int(a.get("channels") or 0) <= 2 for a in audio):
        steps.append({
            "key": "add_aac_track",
            "what": "Add an AAC stereo track beside the original audio",
            "why": "AAC stereo is the one thing every television, phone, browser and stick plays without converting "
                   "anything. It costs a few hundred megabytes and the original track is kept untouched.",
        })

    # ---- the ones that answer to Settings -----------------------------------
    #
    # These only appear when somebody has said which languages they care
    # about, because there is no sensible default: a house that watches anime
    # in Japanese and a house that watches it dubbed want opposite things.
    settings = current()
    first = (settings.preferred_audio_language or "").strip().lower()
    spoken = [str(track.get("language") or "").lower() for track in audio]
    if first and len(audio) > 1 and spoken and spoken[0] != first and first in spoken:
        steps.append({
            "key": "default_audio",
            "what": f"Put the {first} audio first",
            "why": "Players take the first track unless somebody goes looking, which is how a film ends up playing "
                   "its commentary or its dubbed track.",
        })

    keep_subs = languages(settings.keep_subtitle_languages)
    droppable = [s for s in subs if str(s.get("language") or "").lower() not in keep_subs]
    if keep_subs and droppable and len(droppable) < len(subs):
        steps.append({
            "key": "keep_subtitle_languages",
            "what": f"Drop {len(droppable)} subtitle track{'s' if len(droppable) != 1 else ''} in other languages",
            "why": f"Keeping {', '.join(keep_subs)}. Every client reads the whole list before a stream starts, and "
                   "nobody scrolls past twenty languages to find theirs.",
        })

    keep_audio = languages(settings.keep_audio_languages)
    extra_audio = [a for a in audio if str(a.get("language") or "").lower() not in keep_audio]
    if keep_audio and extra_audio and len(extra_audio) < len(audio):
        steps.append({
            "key": "keep_audio_languages",
            "what": f"Drop {len(extra_audio)} audio track{'s' if len(extra_audio) != 1 else ''} in other languages",
            "why": f"Keeping {', '.join(keep_audio)}. Spare dubs are often the largest thing in the file after the "
                   "picture. A file that would be left silent keeps everything.",
        })

    if container and container not in MODERN_CONTAINERS:
        steps.append({
            "key": "legacy_container",
            "what": f"Repackage from {container} to mkv",
            "why": "Old containers limit what can be carried and what can be sought through. The streams are "
                   "copied across, not re-encoded.",
        })

    return {
        "rating_key": getattr(item, "rating_key", None),
        "title": getattr(item, "full_title", None) or getattr(item, "title", None),
        "file_path": getattr(item, "file_path", None),
        # Numbered within their own kind, which is how they are chosen and how
        # ffmpeg is told about them: the first audio track, the third subtitle.
        "audio": [
            {"position": n, "codec": track.get("codec"), "channels": track.get("channels"),
             "language": track.get("language"), "title": track.get("title")}
            for n, track in enumerate(audio)
        ],
        "subtitles": [
            {"position": n, "codec": track.get("codec"), "language": track.get("language"),
             "forced": bool(track.get("forced")), "title": track.get("title")}
            for n, track in enumerate(subs)
        ],
        "steps": steps,
        # Everything here is a stream copy except one audio encode, so the cost
        # is reading and writing the file once.
        "re_encodes_video": False,
    }


# ---- the command ------------------------------------------------------------
#
# Built from ffprobe's own stream list rather than the database's summary,
# because mapping streams needs their real indexes, and a file can have been
# replaced since it was last read.


CHOSEN = "chosen_tracks"
"""The step for a choice made on the file itself rather than by a rule.

Everything else here is a judgement the app can defend from what it read: this
one is a person looking at seven subtitle tracks and saying which three they
want. It carries the positions they ticked, counted within each kind."""


def probe(path: str) -> list[dict[str, Any]]:
    """Every stream in the file, as ffprobe sees it."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        capture_output=True, text=True, timeout=120, check=True,
    )
    data = json.loads(out.stdout or "{}")
    return list(data.get("streams") or [])


def seconds(path: str) -> float | None:
    """How long the file is, for checking the result is the same film."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
        capture_output=True, text=True, timeout=120, check=True,
    )
    try:
        return float(json.loads(out.stdout)["format"]["duration"])
    except (ValueError, KeyError, TypeError):
        return None


def _language(stream: dict[str, Any]) -> str:
    return str((stream.get("tags") or {}).get("language") or "").lower()


def _forced(stream: dict[str, Any]) -> bool:
    return bool((stream.get("disposition") or {}).get("forced"))


def build(streams: list[dict[str, Any]], steps: list[str], source: str, target: str,
          chosen: dict[str, Any] | None = None) -> list[str]:
    """The ffmpeg command for these steps against these streams.

    Video and audio are copied across untouched. Only subtitles are dropped or
    rewritten, and at most one audio track is added. Anything the steps do not
    mention is carried over as it was, because this is tidying, not a rebuild.
    """
    wanted = set(steps)
    chosen = chosen or {}
    subs = [s for s in streams if s.get("codec_type") == "subtitle"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]

    # A choice made on the file wins over anything worked out from settings:
    # somebody is looking at the actual track list.
    if CHOSEN in wanted:
        keep_audio_at = chosen.get("audio")
        keep_subs_at = chosen.get("subtitles")
        if keep_audio_at is not None:
            picked = [a for n, a in enumerate(audio) if n in set(keep_audio_at)]
            # Never leave a file with nothing to listen to.
            audio = picked or audio
        if keep_subs_at is not None:
            subs = [s for n, s in enumerate(subs) if n in set(keep_subs_at)]

    text_languages = {_language(s) for s in subs if str(s.get("codec_name") or "").lower() not in IMAGE_SUBTITLES}
    keep: list[dict[str, Any]] = []
    seen: set[tuple[str, str, bool]] = set()
    for stream in subs:
        codec = str(stream.get("codec_name") or "").lower()
        if "image_subtitles_only" in wanted and codec in IMAGE_SUBTITLES and _language(stream) in text_languages:
            continue
        shape = (codec, _language(stream), _forced(stream))
        if "subtitle_clutter" in wanted and shape in seen:
            continue
        seen.add(shape)
        keep.append(stream)

    # Audio: which tracks survive, and which goes first.
    settings = current()
    keep_audio_codes = languages(settings.keep_audio_languages)
    kept_audio = audio
    if "keep_audio_languages" in wanted and keep_audio_codes:
        wanted_audio = [a for a in audio if _language(a) in keep_audio_codes]
        # Never leave a file with nothing to listen to, whatever the setting
        # says: a rule that silences a film is worse than a spare dub.
        kept_audio = wanted_audio or audio

    first_at = chosen.get("default_audio") if CHOSEN in wanted else None
    if first_at is not None and 0 <= first_at < len(kept_audio):
        head = kept_audio[first_at]
        kept_audio = [head] + [a for a in kept_audio if a is not head]

    first = (settings.preferred_audio_language or "").strip().lower()
    if "default_audio" in wanted and first:
        preferred = [a for a in kept_audio if _language(a) == first]
        kept_audio = preferred + [a for a in kept_audio if a not in preferred]

    # Subtitles: the language filter runs after the other subtitle steps, so
    # dropping duplicates and dropping languages compose rather than fight.
    keep_sub_codes = languages(settings.keep_subtitle_languages)
    if "keep_subtitle_languages" in wanted and keep_sub_codes:
        narrowed = [s for s in keep if _language(s) in keep_sub_codes]
        # All of them in one unwanted language is still a file people watch;
        # leaving no subtitles at all is the point of the setting, so this one
        # is allowed to empty the list.
        keep = narrowed

    rest = [s for s in streams if s.get("codec_type") not in ("subtitle", "audio")]

    argv = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-y", "-i", source]
    for stream in rest:
        argv += ["-map", f"0:{stream['index']}"]
    for stream in kept_audio:
        argv += ["-map", f"0:{stream['index']}"]
    for stream in keep:
        argv += ["-map", f"0:{stream['index']}"]
    argv += ["-c", "copy"]

    if (first_at is not None or ("default_audio" in wanted and first)) and kept_audio:
        # Said out loud as well as ordered, because some players read the
        # disposition and ignore the order.
        argv += ["-disposition:a", "0", "-disposition:a:0", "default"]

    if "styled_subtitles" in wanted:
        # Only the text ones can become SRT; a picture subtitle has no text in
        # it to convert, so it is copied as it is.
        for position, stream in enumerate(keep):
            if str(stream.get("codec_name") or "").lower() in STYLED_SUBTITLES:
                argv += [f"-c:s:{position}", "srt"]

    # Added tracks go on the end, in the order asked for, so two of them do not
    # both claim the same position.
    added = 0

    if "no_compatible_audio" in wanted and kept_audio:
        # Beside the original, never instead of it: the lossless track is why
        # somebody keeps the file, and six channels of AC3 play everywhere.
        best = max(kept_audio, key=lambda s: int(s.get("channels") or 0))
        channels = min(int(best.get("channels") or 2), 6)
        position = len(kept_audio) + added
        argv += ["-map", f"0:{best['index']}", f"-c:a:{position}", "ac3",
                 f"-ac:a:{position}", str(channels), f"-b:a:{position}", "640k" if channels > 2 else "192k",
                 f"-metadata:s:a:{position}", "title=AC3 (added by Cartographarr)"]
        added += 1

    if "add_aac_track" in wanted and kept_audio:
        # Downmixed from whichever track has the most channels, so the stereo
        # carries the full mix rather than two of its six channels.
        best = max(kept_audio, key=lambda s: int(s.get("channels") or 0))
        position = len(kept_audio) + added
        argv += ["-map", f"0:{best['index']}", f"-c:a:{position}", "aac",
                 f"-ac:a:{position}", "2", f"-b:a:{position}", "192k",
                 f"-metadata:s:a:{position}", "title=AAC stereo (added by Cartographarr)"]
        if _language(best):
            argv += [f"-metadata:s:a:{position}", f"language={_language(best)}"]
        added += 1

    argv.append(target)
    return argv


# ---- running one -------------------------------------------------------------
#
# One at a time, because these read and write whole films and two at once on
# the same array is slower than one after the other. The original is replaced
# only after the result has been checked against it.

import asyncio
import logging
import os
import tempfile

log = logging.getLogger(__name__)

DURATION_SLACK = 0.01
"""How far the result may differ in length from the original before it is
treated as a different film: one per cent, which covers container rounding and
nothing else."""

_running: asyncio.Task | None = None
_current: dict[str, Any] = {}


def queue(rating_key: int, steps: list[str], asked_by: str | None,
          chosen: dict[str, Any] | None = None) -> int:
    """Write the job down. Returns its id."""
    from datetime import UTC, datetime

    from app.db import session_scope
    from app.models import MediaItem, MediaJob

    with session_scope() as db:
        item = db.get(MediaItem, rating_key)
        if item is None or not item.file_path:
            raise LookupError("That file is not in the library any more")
        here = local_path(item.file_path)
        if here is None:
            raise LookupError(
                f"This container cannot see {item.file_path}. Mount it, or set the path map in Settings."
            )
        if not tools()["ready"]:
            raise LookupError("ffmpeg is not installed in this container")
        known = {step["key"] for step in plan(item)["steps"]}
        wanted = [step for step in steps if step in known]
        if chosen:
            # A choice from the page is its own step, and does not have to be
            # one the plan thought of.
            wanted = [*wanted, CHOSEN]
        if not wanted:
            raise ValueError("Nothing to do to this file")
        job = MediaJob(
            rating_key=rating_key, title=item.full_title or item.title, path=here,
            steps=json.dumps({"steps": wanted, "chosen": chosen or {}}), status="queued", progress=0,
            asked_by=asked_by, created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        db.add(job)
        db.flush()
        return job.id


def start_worker() -> None:
    """Make sure something is working through the queue."""
    global _running

    if _running is not None and not _running.done():
        return
    _running = asyncio.get_event_loop().create_task(_work())


async def _work() -> None:
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import MediaJob

    def take():
        with session_scope() as db:
            job = db.execute(
                select(MediaJob).where(MediaJob.status == "queued").order_by(MediaJob.id)
            ).scalars().first()
            if job is None:
                return None
            job.status = "running"
            db.flush()
            return job.id

    while True:
        job_id = await asyncio.to_thread(take)
        if job_id is None:
            return
        try:
            await _run(job_id)
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the queue
            log.exception("media job %s failed", job_id)
            await asyncio.to_thread(_finish, job_id, "failed", str(exc))


def _say(job_id: int, progress: int | None = None, detail: str | None = None) -> None:
    from app.db import session_scope
    from app.models import MediaJob

    with session_scope() as db:
        job = db.get(MediaJob, job_id)
        if job is None:
            return
        if progress is not None:
            job.progress = max(0, min(100, progress))
        if detail is not None:
            job.detail = detail


def _finish(job_id: int, status: str, detail: str | None, saved: int | None = None) -> None:
    from datetime import UTC, datetime

    from app import audit
    from app.db import session_scope
    from app.models import MediaJob

    with session_scope() as db:
        job = db.get(MediaJob, job_id)
        if job is None:
            return
        job.status = status
        job.detail = detail
        job.saved_bytes = saved
        job.finished_at = datetime.now(UTC).replace(tzinfo=None)
        job.progress = 100 if status == "done" else job.progress
        title, path = job.title, job.path
    audit.record(None, f"library.tidy.{status}", f"{title}: {detail}", target=path, actor="Cartographarr")


async def _run(job_id: int) -> None:
    """Probe, build, run, check, replace."""
    from app.db import session_scope
    from app.models import MediaJob

    with session_scope() as db:
        job = db.get(MediaJob, job_id)
        source, asked = job.path, json.loads(job.steps or "[]")
        rating_key = job.rating_key
    # Older jobs stored a bare list of steps; newer ones carry the choice too.
    steps = asked.get("steps", []) if isinstance(asked, dict) else asked
    chosen = asked.get("chosen", {}) if isinstance(asked, dict) else {}

    if not source or not os.path.exists(source):
        await asyncio.to_thread(_finish, job_id, "failed", "The file is not where it was")
        return

    streams = await asyncio.to_thread(probe, source)
    was = await asyncio.to_thread(seconds, source)
    before = os.path.getsize(source)

    # Beside the original, on the same mount, so the swap at the end is a
    # rename rather than a copy across filesystems.
    #
    # The suffix decides the container ffmpeg writes, so it is the source's own
    # unless repackaging is one of the steps. Writing mkv regardless would
    # rename a perfectly good mp4 and delete it, for a job that was only asked
    # to drop some subtitles.
    folder = os.path.dirname(source)
    suffix = ".mkv" if "legacy_container" in steps else (os.path.splitext(source)[1] or ".mkv")
    handle, target = tempfile.mkstemp(prefix=".cartographarr-", suffix=suffix, dir=folder)
    os.close(handle)
    argv = build(streams, steps, source, target, chosen)
    await asyncio.to_thread(_say, job_id, 0, "Reading the file")

    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _current[str(job_id)] = process
    try:
        assert process.stdout is not None
        async for raw in process.stdout:
            line = raw.decode(errors="ignore").strip()
            if line.startswith("out_time_ms=") and was:
                done = int(line.split("=", 1)[1] or 0) / 1_000_000
                await asyncio.to_thread(_say, job_id, int(done / was * 100), "Writing the tidied copy")
        await process.wait()
    finally:
        _current.pop(str(job_id), None)

    if process.returncode != 0:
        problem = (await process.stderr.read()).decode(errors="ignore").strip() if process.stderr else ""
        os.unlink(target)
        last = problem.splitlines()[-1] if problem else "ffmpeg stopped"
        await asyncio.to_thread(_finish, job_id, "failed", last)
        return

    # Checked before anything is replaced: the same film, the same length, and
    # the picture still in it.
    now = await asyncio.to_thread(seconds, target)
    after_streams = await asyncio.to_thread(probe, target)
    video = sum(1 for s in after_streams if s.get("codec_type") == "video")
    expected_video = sum(1 for s in streams if s.get("codec_type") == "video")
    if was and (now is None or abs(now - was) > was * DURATION_SLACK):
        os.unlink(target)
        await asyncio.to_thread(
            _finish, job_id, "failed", f"The result runs {now} against {was} seconds, so the original was kept"
        )
        return
    if video != expected_video:
        os.unlink(target)
        await asyncio.to_thread(_finish, job_id, "failed", "The result has no picture in it, so the original was kept")
        return

    after = os.path.getsize(target)
    final = os.path.splitext(source)[0] + suffix
    os.replace(target, final)
    if final != source:
        os.unlink(source)
    await asyncio.to_thread(_rewritten, rating_key, final, after)
    changes = len(steps)
    word = "changes" if changes != 1 else "change"
    await asyncio.to_thread(_finish, job_id, "done", f"Tidied, {changes} {word} made", before - after)


def _rewritten(rating_key: int | None, path: str, size: int) -> None:
    """Record that the file on disk is no longer the one we read.

    Without this the stored track list is still the one from before, so the
    page goes on saying the file has the problem that was just fixed until the
    next library scan, and if the name changed the stored path points at
    something that has been deleted. Clearing file_checked_at is what the
    replacement flow does for the same reason: the detail pass runs every
    minute and reads it again.
    """
    from app.db import session_scope
    from app.models import MediaItem

    if rating_key is None:
        return
    with session_scope() as db:
        item = db.get(MediaItem, rating_key)
        if item is None:
            return
        item.file_path = path
        item.file_size = size
        item.file_checked_at = None


def cancel(job_id: int) -> bool:
    """Stop one, whether it is waiting or already running."""
    from app.db import session_scope
    from app.models import MediaJob

    process = _current.get(str(job_id))
    if process is not None:
        process.terminate()
        return True
    with session_scope() as db:
        job = db.get(MediaJob, job_id)
        if job is None or job.status != "queued":
            return False
        job.status = "cancelled"
        job.detail = "Cancelled before it started"
        return True

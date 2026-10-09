"""Replacing a problem file through Radarr or Sonarr, with a look before it lands.

1. **Find**: ask Radarr or Sonarr for releases, and compare each with the
   current file: resolution, video and audio format, HDR, size and rough
   bitrate, and which of the file's problems it would fix.
2. **Queue**: grab the chosen release. It is followed from here.
3. **Ready**: once downloaded, Radarr and Sonarr import a release they rate as
   an upgrade by themselves. One that is not an upgrade, which is most
   compatibility swaps (same quality, better audio), is held for manual
   import. Held releases are shown next to the current file to Confirm, which
   imports it and replaces the old file, or Deny, which removes the download
   and blocks that release.

What a release contains is read from its name until it is downloaded; after,
from what Radarr or Sonarr found in the file.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

log = logging.getLogger(__name__)

ACTIVE = ("queued", "downloading", "ready", "importing")

# ---- reading a release name --------------------------------------------------------

_AUDIO = [
    (r"truehd|atmos", "truehd"),
    (r"dts[-. ]?hd[-. ]?ma|dts[-. ]?x\b", "dca-ma"),
    (r"\bdts\b", "dca"),
    (r"\bddp|dd\+|e-?ac-?3", "eac3"),
    (r"\bdd(?:5|2|7)?|\bac-?3\b", "ac3"),
    (r"\baac\b", "aac"),
    (r"\bopus\b", "opus"),
    (r"\bflac\b", "flac"),
]


def parse_release(title: str) -> dict[str, Any]:
    """What a release name says about the file: resolution, video codec, bit
    depth, HDR, audio codec and channels, and source."""
    t = title.lower().replace("_", ".")
    out: dict[str, Any] = {}
    m = re.search(r"\b(2160|1080|720|576|480)p\b", t)
    if m:
        out["resolution"] = f"{m.group(1)}p"
    elif re.search(r"\b4k\b|\buhd\b", t):
        out["resolution"] = "2160p"
    if re.search(r"x\.?265|h\.?265|hevc", t):
        out["video_codec"] = "hevc"
    elif re.search(r"x\.?264|h\.?264|\bavc\b", t):
        out["video_codec"] = "h264"
    elif re.search(r"\bav1\b", t):
        out["video_codec"] = "av1"
    if re.search(r"10.?bit|hi10", t):
        out["bit_depth"] = 10
    if re.search(r"\bdv\b|dovi|dolby.?vision", t):
        out["hdr"] = "Dolby Vision"
    elif re.search(r"hdr10\+|hdr10plus", t):
        out["hdr"] = "HDR10+"
    elif re.search(r"\bhdr(10)?\b", t):
        out["hdr"] = "HDR10"
    for pattern, codec in _AUDIO:
        if re.search(pattern, t):
            out["audio_codec"] = codec
            break
    ch = re.search(r"(?<!\d)([257])[. ]([01])(?!\d)", t)
    if ch:
        out["audio_channels"] = {"2": 2, "5": 6, "7": 8}[ch.group(1)]
    if re.search(r"remux", t):
        out["source"] = "Remux"
    elif re.search(r"blu-?ray|bdrip|brrip", t):
        out["source"] = "Blu-ray"
    elif re.search(r"web-?dl", t):
        out["source"] = "WEB-DL"
    elif re.search(r"webrip", t):
        out["source"] = "WEBRip"
    elif re.search(r"hdtv", t):
        out["source"] = "HDTV"
    return out


COMPATIBLE_AUDIO = {"aac", "ac3", "eac3", "mp3", "opus"}


def fixes(current: dict[str, Any], candidate: dict[str, Any], duration_ms: int | None, threshold_kbps: int) -> list[str]:
    """Which of the current file's problems this release would likely fix,
    in plain words."""
    found = [f["key"] for f in current.get("findings") or []]
    out = []
    audio = candidate.get("audio_codec")
    if audio and "no_compatible_audio" in found and audio in COMPATIBLE_AUDIO:
        out.append(f"Playable audio ({audio.upper()})")
    if audio in ("ac3", "eac3") and ("aac_surround" in found or "audio_transcoded" in found):
        out.append(f"{audio.upper()} surround instead of AAC")
    if candidate.get("video_codec") == "h264" and "video_codec" in found:
        out.append("H.264, plays nearly everywhere")
    if "hdr_tonemap" in found and not candidate.get("hdr"):
        out.append("SDR, no tone mapping")
    rate = estimated_bitrate(candidate.get("size"), duration_ms)
    if "over_threshold" in found and rate and rate < threshold_kbps:
        out.append(f"About {rate / 1000:.0f} Mbps, under your limit")
    if "legacy_container" in found:
        out.append("Modern container")
    return out


def estimated_bitrate(size: int | None, duration_ms: int | None) -> int | None:
    if not size or not duration_ms:
        return None
    return int(size * 8 / (duration_ms / 1000) / 1000)


def _held(release: dict[str, Any]) -> bool:
    """Whether Radarr or Sonarr would hold this for manual import rather than
    importing it: anything it does not rate as an upgrade."""
    reasons = " ".join(str(r) for r in release.get("rejections") or []).lower()
    return (not release.get("approved")) and ("upgrade" in reasons or "cutoff" in reasons or "existing" in reasons)


def compare_releases(
    releases: list[dict[str, Any]], current: dict[str, Any], duration_ms: int | None, threshold_kbps: int
) -> list[dict[str, Any]]:
    out = []
    for r in releases:
        title = str(r.get("title") or "")
        parsed = parse_release(title)
        parsed["size"] = r.get("size")
        # Rejections that mean the release cannot be used at all, rather than
        # just "not an upgrade", are shown but sorted last.
        reasons = [str(x) for x in r.get("rejections") or []]
        blocking = [x for x in reasons if not re.search(r"upgrade|cutoff|existing|already", x, re.I)]
        out.append({
            "guid": r.get("guid"),
            "indexer_id": r.get("indexerId"),
            "title": title,
            "indexer": r.get("indexer"),
            "size": r.get("size"),
            "age_days": r.get("age"),
            "seeders": r.get("seeders"),
            "protocol": r.get("protocol"),
            "quality": ((r.get("quality") or {}).get("quality") or {}).get("name"),
            "languages": [lang.get("name") for lang in r.get("languages") or [] if isinstance(lang, dict)],
            "custom_format_score": r.get("customFormatScore"),
            "custom_formats": [cf.get("name") for cf in r.get("customFormats") or [] if isinstance(cf, dict) and cf.get("name")],
            "estimated_bitrate": estimated_bitrate(r.get("size"), duration_ms),
            "parsed": parsed,
            "fixes": fixes(current, parsed, duration_ms, threshold_kbps),
            "held": _held(r),
            "rejections": reasons,
            "blocked": bool(blocking),
        })
    # Best first, on two numbers rather than one blended one. How many of this
    # file's problems a release would fix is this app's question and comes
    # first. The custom format score is the service's own opinion of the
    # release against the profile, and settles the rest. Blending them would
    # mean picking what one problem is worth in format points, and nothing
    # about either number says that.
    out.sort(key=lambda x: (
        x["blocked"],
        -len(x["fixes"]),
        x["held"],
        -(x["custom_format_score"] or 0),
        x["size"] or 0,
    ))
    return out


# ---- persistence and following the download -------------------------------------------

def to_dict(row: Any) -> dict[str, Any]:
    def load(value: str | None) -> Any:
        try:
            return json.loads(value) if value else None
        except ValueError:
            return None

    return {
        "id": row.id,
        "rating_key": row.rating_key,
        "title": row.title,
        "service": row.service,
        "status": row.status,
        "progress": row.progress,
        "message": row.message,
        "release": load(row.release),
        "current": load(row.current),
        "candidate": load(row.candidate),
        "auto_confirm": bool(getattr(row, "auto_confirm", False)),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "resolved_by": row.resolved_by,
        "checked_at": row.checked_at.isoformat() if getattr(row, "checked_at", None) else None,
    }


def importable(candidate: str | None) -> dict | None:
    """The file to import out of what the service found in the download.

    The biggest, which is the feature rather than the whole download: a
    release folder carries samples, subtitles and artwork beside the film.
    One function because confirming by hand and confirming because it was
    asked for in advance must not drift into choosing differently.
    """
    files = (json.loads(candidate or "{}") or {}).get("files") or []
    return max(files, key=lambda f: f.get("size") or 0) if files else None


def _service(name: str):
    from app.integrations import arr

    return arr.radarr if name == "radarr" else arr.sonarr


async def poll() -> int:
    """Follow every active replacement one step. Returns how many changed."""
    from app.db import session_scope
    from app.models import Replacement

    with session_scope() as db:
        rows = db.execute(select(Replacement).where(Replacement.status.in_(ACTIVE))).scalars().all()
        for r in rows:
            db.expunge(r)
    changed = 0
    queues: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        service = _service(r.service)
        if not service.configured():
            continue
        try:
            if r.service not in queues:
                queues[r.service] = await service.queue()
            _, update = await live(r, service, queues[r.service])
        except Exception as exc:  # noqa: BLE001 - try again next time
            log.debug("replacement %s poll failed: %s", r.id, exc)
            continue
        if save(r, update):
            changed += 1
    return changed


def save(r: Any, update: dict[str, Any]) -> bool:
    from app.db import session_scope
    from app.models import Replacement

    with session_scope() as db:
        stored = db.get(Replacement, r.id)
        stored.checked_at = datetime.now(UTC)
        if not update:
            return False
        for key, value in update.items():
            setattr(stored, key, value)
        stored.updated_at = datetime.now(UTC)
    if update.get("status") == "ready":
        import asyncio

        try:
            asyncio.get_running_loop().create_task(_tell(r, "is downloaded and waiting for you to confirm or deny it"))
        except RuntimeError:
            pass
    return True


EVENTS = {
    "grabbed": "Sent to the download client",
    "downloadfailed": "Download failed",
    "downloadfolderimported": "Imported",
    "moviefileimported": "Imported",
    "episodefileimported": "Imported",
    "downloadignored": "Ignored",
    "moviefiledeleted": "Old file deleted",
    "episodefiledeleted": "Old file deleted",
    "moviefilerenamed": "Renamed",
    "episodefilerenamed": "Renamed",
}


def _when(value: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        return None


async def live(r: Any, service: Any, queue: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """What Radarr or Sonarr says about this replacement right now, straight
    from its queue and history, and the changes that means for the stored row.

    The download is recognised by its download id once known, otherwise by the
    release name; history events from before the replacement was queued are
    left out."""
    release = json.loads(r.release or "{}")
    name = str(release.get("title") or "").lower()
    now = datetime.now(UTC)
    created = r.created_at if (r.created_at and r.created_at.tzinfo) else (r.created_at or now).replace(tzinfo=UTC)

    if queue is None:
        queue = await service.queue()
    history = await service.history(r.arr_id, r.episode_id)

    events = [
        h for h in history
        if (_when(h.get("date")) or now) >= created - timedelta(minutes=5)
        and ((r.download_id and h.get("downloadId") == r.download_id) or str(h.get("sourceTitle") or "").lower() == name)
    ]
    download_id = r.download_id or next((h.get("downloadId") for h in events if h.get("downloadId")), None)
    if download_id:
        events = [h for h in history if h.get("downloadId") == download_id and (_when(h.get("date")) or now) >= created - timedelta(minutes=5)] or events
    q = next(
        (x for x in queue
         if (download_id and x.get("downloadId") == download_id)
         or (not download_id and _same_item(x, r) and str(x.get("title") or "").lower() == name)),
        None,
    )

    shown = {
        "checked_at": now.isoformat(),
        "queue": None if q is None else {
            "status": q.get("status"),
            "state": q.get("trackedDownloadState"),
            "health": q.get("trackedDownloadStatus"),
            "progress": round(1 - (q.get("sizeleft") or 0) / q["size"], 3) if q.get("size") else None,
            "time_left": q.get("timeleft"),
            "client": q.get("downloadClient"),
            "messages": [m for x in q.get("statusMessages") or [] for m in x.get("messages") or []] + (
                [q["errorMessage"]] if q.get("errorMessage") else []
            ),
        },
        "events": [
            {
                "type": h.get("eventType"),
                "label": EVENTS.get(str(h.get("eventType") or "").lower(), str(h.get("eventType") or "")),
                "date": h.get("date"),
                "title": h.get("sourceTitle"),
                "message": (h.get("data") or {}).get("message"),
            }
            for h in events
        ],
    }

    update: dict[str, Any] = {}
    download_id = download_id or (q or {}).get("downloadId")
    if download_id and download_id != r.download_id:
        update["download_id"] = download_id
    types = [str(h.get("eventType") or "").lower() for h in events]

    if r.status in ACTIVE:
        if any(t in ("downloadfolderimported", "moviefileimported", "episodefileimported") for t in types):
            update.update(await _imported(r, service))
        elif "downloadfailed" in types:
            failed = next(h for h in events if str(h.get("eventType") or "").lower() == "downloadfailed")
            update["status"] = "failed"
            update["message"] = ((failed.get("data") or {}).get("message") or "The download failed")[:500]
        elif q is not None:
            update["queue_id"] = q.get("id")
            update["progress"] = shown["queue"]["progress"]
            state = str(q.get("trackedDownloadState") or "").lower()
            if str(q.get("trackedDownloadStatus") or "").lower() == "error":
                update["status"] = "failed"
                update["message"] = ("; ".join(shown["queue"]["messages"]) or "Download failed")[:500]
            elif state in ("importpending", "importblocked") or (str(q.get("status")).lower() == "completed" and state != "importing"):
                if r.status != "ready":
                    files = await service.manual_import_candidates(q.get("downloadId"))
                    update["candidate"] = json.dumps(_candidate(files))
                    update["status"] = "ready"
                    update["message"] = "; ".join(shown["queue"]["messages"])[:500] or None
                    # Asked for in advance, so it is not held for an answer
                    # somebody has already given. Only ever a step earlier:
                    # the same import, from the same candidate, by the same
                    # call, and if there is nothing to import it waits exactly
                    # as it did before.
                    # Once, ever. The poll runs on a timer and the queue can
                    # sit at importPending for a while after the import is
                    # asked for, so a guard on the status alone asks the
                    # service to import the same download over and over.
                    # `resolved_by` is the record that somebody, or this,
                    # already answered it. A download that is held again after
                    # an import that did not stick is left for a person: it
                    # tried once and that was not enough.
                    if getattr(r, "auto_confirm", False) and not r.resolved_by:
                        wanted = importable(update["candidate"])
                        if wanted is None:
                            update["message"] = (
                                f"{service.label} found no file to import in the download, so this is waiting "
                                "for you after all."
                            )
                        else:
                            await service.manual_import(
                                [wanted], r.arr_id, r.episode_id, q.get("downloadId")
                            )
                            update["status"] = "importing"
                            update["resolved_by"] = r.created_by
            elif state == "importing":
                update["status"] = "importing"
            elif r.status == "queued":
                update["status"] = "downloading"
        elif r.status in ("importing", "downloading", "ready") or now - created > timedelta(minutes=30):
            # Gone from the queue with no event saying why: look at the file.
            file = await service.current_file(r.arr_id, r.episode_id)
            if file and file.get("id") != json.loads(r.current or "{}").get("arr_file_id"):
                update.update(await _imported(r, service, file))
            elif not events:
                update["status"] = "failed"
                update["message"] = f"{service.label} never started this download."
            elif r.status != "importing":
                update["status"] = "failed"
                update["message"] = "It left the download queue without being imported."

    return shown, {k: v for k, v in update.items() if getattr(r, k, None) != v}


async def _imported(r: Any, service: Any, file: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import issues

    if file is None:
        file = await service.current_file(r.arr_id, r.episode_id)
    with session_scope() as db:
        item = db.get(MediaItem, r.rating_key)
        where = item.file_path if item is not None else None
        if item is not None:
            item.file_checked_at = None  # read the new file's details on the next sync
    # Radarr and Sonarr import under a new name and delete the old file, so
    # Plex is left listing one that is gone until its own nightly scan and
    # anybody pressing play gets an error. A scan of that one folder is what
    # finds the new file and loses the old. Radarr can be wired to Plex itself,
    # but assuming somebody did that is assuming the thing that breaks.
    if where:
        import asyncio

        from app.plex import maintenance

        await asyncio.to_thread(maintenance.file_changed, r.rating_key, where, True)
    # What anyone reported about this file was about the old one. Closing it
    # here, with what replaced it, is the end of the loop the report started.
    try:
        closed = await issues.resolve_for_file(
            r.rating_key,
            f"Replaced through {service.label}: {_file_summary(file or {}).get('quality') or 'a new file'}.",
        )
        if closed:
            log.info("replacement for %s closed %d reported issue(s)", r.rating_key, len(closed))
    except Exception:  # noqa: BLE001 - the replacement landing is the important part
        log.exception("could not close issues for %s", r.rating_key)
    return {
        "status": "imported" if r.status == "importing" else "imported_automatically",
        "candidate": json.dumps({**json.loads(r.candidate or "{}"), "imported": _file_summary(file or {})}),
        "progress": 1.0,
    }


def _same_item(q: dict[str, Any], r: Any) -> bool:
    if r.service == "radarr":
        return q.get("movieId") == r.arr_id
    return q.get("episodeId") == r.episode_id


def _candidate(files: list[dict[str, Any]]) -> dict[str, Any]:
    """The downloaded file as Radarr or Sonarr sees it, largest file first
    (samples and extras are small)."""
    files = sorted(files or [], key=lambda f: -(f.get("size") or 0))
    if not files:
        return {"files": []}
    f = files[0]
    return {
        "files": files,
        "name": f.get("name") or f.get("relativePath"),
        "size": f.get("size"),
        "quality": ((f.get("quality") or {}).get("quality") or {}).get("name"),
        "languages": [lang.get("name") for lang in f.get("languages") or [] if isinstance(lang, dict)],
        "release_group": f.get("releaseGroup"),
        "rejections": [x.get("reason") if isinstance(x, dict) else str(x) for x in f.get("rejections") or []],
        "parsed": parse_release(str(f.get("name") or f.get("relativePath") or "")),
    }


def _file_summary(file: dict[str, Any]) -> dict[str, Any]:
    media = file.get("mediaInfo") or {}
    return {
        "path": file.get("relativePath") or file.get("path"),
        "size": file.get("size"),
        "quality": ((file.get("quality") or {}).get("quality") or {}).get("name"),
        "video_codec": media.get("videoCodec"),
        "bit_depth": media.get("videoBitDepth"),
        "hdr": media.get("videoDynamicRangeType") or media.get("videoDynamicRange"),
        "audio_codec": media.get("audioCodec"),
        "audio_channels": media.get("audioChannels"),
        "audio_languages": media.get("audioLanguages"),
        "subtitles": media.get("subtitles"),
        "resolution": media.get("resolution"),
    }


async def _tell(r: Any, what: str) -> None:
    from app.integrations.notify import apprise_notifier

    if not apprise_notifier.configured():
        return
    try:
        await apprise_notifier.send("Replacement ready", f"The replacement for {r.title} {what}, in Library, Replacements.")
    except Exception as exc:  # noqa: BLE001
        log.debug("could not notify: %s", exc)

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
            "estimated_bitrate": estimated_bitrate(r.get("size"), duration_ms),
            "parsed": parsed,
            "fixes": fixes(current, parsed, duration_ms, threshold_kbps),
            "held": _held(r),
            "rejections": reasons,
            "blocked": bool(blocking),
        })
    out.sort(key=lambda x: (x["blocked"], -len(x["fixes"]), not x["held"], x["size"] or 0))
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
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "resolved_by": row.resolved_by,
    }


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
    if not rows:
        return 0
    changed = 0
    queues: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        service = _service(r.service)
        if not service.configured():
            continue
        try:
            if r.service not in queues:
                queues[r.service] = await service.queue()
            update = await _step(r, service, queues[r.service])
        except Exception as exc:  # noqa: BLE001 - try again next time
            log.debug("replacement %s poll failed: %s", r.id, exc)
            continue
        if update:
            with session_scope() as db:
                stored = db.get(Replacement, r.id)
                for key, value in update.items():
                    setattr(stored, key, value)
                stored.updated_at = datetime.now(UTC)
            changed += 1
            if update.get("status") == "ready":
                await _tell(r, "is downloaded and waiting for you to confirm or deny it")
    return changed


async def _step(r: Any, service: Any, queue: list[dict[str, Any]]) -> dict[str, Any]:
    release = json.loads(r.release or "{}")
    mine = [
        q for q in queue
        if (q.get("downloadId") and q.get("downloadId") == r.download_id)
        or (not r.download_id and _same_item(q, r) and str(q.get("title") or "").lower() == str(release.get("title") or "").lower())
    ]
    now = datetime.now(UTC)
    created = r.created_at if (r.created_at and r.created_at.tzinfo) else (r.created_at or now).replace(tzinfo=UTC)

    if mine:
        q = mine[0]
        size, left = q.get("size") or 0, q.get("sizeleft") or 0
        update: dict[str, Any] = {
            "download_id": q.get("downloadId"),
            "queue_id": q.get("id"),
            "progress": round(1 - left / size, 3) if size else None,
        }
        state = str(q.get("trackedDownloadState") or "").lower()
        if state in ("importpending", "importblocked") or (str(q.get("status")).lower() == "completed" and state != "importing"):
            if r.status != "ready":
                files = await service.manual_import_candidates(q.get("downloadId"))
                update["candidate"] = json.dumps(_candidate(files))
                update["status"] = "ready"
                messages = [m for s in q.get("statusMessages") or [] for m in s.get("messages") or []]
                update["message"] = "; ".join(messages)[:500] or None
        elif state == "importing":
            update["status"] = "importing"
        elif r.status == "queued":
            update["status"] = "downloading"
        if str(q.get("trackedDownloadStatus") or "").lower() == "error":
            update["status"], update["message"] = "failed", (q.get("errorMessage") or "Download failed")[:500]
        return {k: v for k, v in update.items() if getattr(r, k, None) != v}

    # Not in the queue any more, or not yet.
    if r.status == "queued" and now - created < timedelta(minutes=30):
        return {}
    file = await service.current_file(r.arr_id, r.episode_id)
    before = json.loads(r.current or "{}").get("arr_file_id")
    if file and file.get("id") != before:
        from app.db import session_scope
        from app.models import MediaItem

        with session_scope() as db:
            item = db.get(MediaItem, r.rating_key)
            if item is not None:
                item.file_checked_at = None  # read the new file's details on the next sync
        status = "imported" if r.status == "importing" else "imported_automatically"
        return {"status": status, "candidate": json.dumps({**json.loads(r.candidate or "{}"), "imported": _file_summary(file)}),
                "progress": 1.0}
    return {"status": "failed", "message": "It left the download queue without being imported."}


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

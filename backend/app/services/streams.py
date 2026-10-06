"""A record of every stream, and of the server's upload, from live activity.

History from Tautulli says a play happened and whether it transcoded. It does
not say why, whether the GPU did the work, what resolution actually reached
the screen, or how busy the upload was at the time. Live activity says all of
that, so each poll is summarised here:

- one `stream_sessions` row per stream, kept up to date while it plays, with
  the worst decision seen (a stream that starts direct and switches to a
  transcode when someone turns subtitles on counts as a transcode) and every
  reason it transcoded
- one `bandwidth_samples` row per minute, the busiest moment of that minute

Only streams seen while Cartographarr was running are recorded, so this starts
empty and grows from the day it is installed.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.dialects.sqlite import insert

log = logging.getLogger(__name__)

# Why a stream was transcoded, in order of how much each one explains. Plex
# reports the decisions, not the reason, so the reason is read from what
# changed between the file and what was sent.
CAUSES: dict[str, str] = {
    "subtitle_burn": "Subtitles burned in",
    "hdr_tonemap": "HDR converted to SDR",
    "video_codec": "Video format the device cannot play",
    "quality_setting": "Quality set below original",
    "video_bitrate": "Video resolution or bitrate reduced",
    "audio_codec": "Audio format the device cannot play",
    "audio_channels": "Audio channels reduced",
    "container": "Container changed (direct stream)",
}
_DECISION_RANK = {None: 0, "": 0, "direct play": 1, "copy": 2, "ignore": 0, "transcode": 3, "burn": 4}


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


def transcode_causes(s: dict[str, Any]) -> list[str]:
    """The reasons this stream is not a plain direct play, most telling first."""
    causes: list[str] = []
    video = _lower(s.get("video_decision") or s.get("stream_video_decision"))
    audio = _lower(s.get("audio_decision") or s.get("stream_audio_decision"))
    subtitle = _lower(s.get("subtitle_decision") or s.get("stream_subtitle_decision"))
    container = _lower(s.get("container_decision") or s.get("stream_container_decision"))

    if subtitle == "burn":
        causes.append("subtitle_burn")
    if video == "transcode":
        source_hdr = _lower(s.get("video_dynamic_range")) not in ("", "sdr")
        sent_hdr = _lower(s.get("stream_video_dynamic_range")) not in ("", "sdr")
        if source_hdr and not sent_hdr:
            causes.append("hdr_tonemap")
        if _lower(s.get("video_codec")) and _lower(s.get("stream_video_codec")) and _lower(s.get("video_codec")) != _lower(s.get("stream_video_codec")):
            causes.append("video_codec")
        quality = _lower(s.get("quality_profile"))
        if quality and quality != "original":
            causes.append("quality_setting")
        elif "subtitle_burn" not in causes and "hdr_tonemap" not in causes and "video_codec" not in causes:
            causes.append("video_bitrate")
    if audio == "transcode":
        if _lower(s.get("audio_codec")) != _lower(s.get("stream_audio_codec")):
            causes.append("audio_codec")
        else:
            causes.append("audio_channels")
    if not causes and (container == "transcode" or video == "copy" or audio == "copy"):
        causes.append("container")
    return causes


def _worst(a: Any, b: Any) -> Any:
    return b if _DECISION_RANK.get(_lower(b) or None, 0) > _DECISION_RANK.get(_lower(a) or None, 0) else a


SPEED_CEILING = 100.0
"""Above this a transcode speed is a measurement artefact rather than a speed.

Plex reports this as a multiple of real time, so 1.0 is keeping up exactly.
A hundred times real time is not something to read anything into, and the
numbers seen below zero certainly are not: this server has a session recorded
at -302.8, which went into the minimum and stayed there, making a stream that
was fine look like one the server could not keep up with."""


def _plausible_speed(value: float | None) -> float | None:
    if value is None or value <= 0 or value > SPEED_CEILING:
        return None
    return value


def _hw(s: dict[str, Any]) -> bool:
    return bool(_int(s.get("transcode_hw_encoding")) or _int(s.get("transcode_hw_decoding")) or s.get("transcode_hw_full_pipeline"))


def row_for(s: dict[str, Any], now: float) -> dict[str, Any]:
    """The columns a stream contributes on first sight."""
    stamp = datetime.fromtimestamp(now, UTC)
    causes = transcode_causes(s)
    return {
        "session_key": str(s.get("session_key")),
        "user_id": _int(s.get("user_id")),
        "username": s.get("friendly_name") or s.get("username"),
        "machine_id": s.get("machine_id"),
        "player": s.get("player"),
        "platform": s.get("platform"),
        "product": s.get("product"),
        "ip_address": s.get("ip_address"),
        "location": s.get("location"),
        "relayed": bool(_int(s.get("relayed"))),
        "secure": bool(_int(s.get("secure"))),
        "rating_key": _int(s.get("rating_key")),
        "grandparent_rating_key": _int(s.get("grandparent_rating_key")),
        "full_title": s.get("full_title"),
        "grandparent_title": s.get("grandparent_title"),
        "parent_media_index": _int(s.get("parent_media_index")),
        "media_index": _int(s.get("media_index")),
        "media_type": s.get("media_type"),
        "quality_profile": s.get("quality_profile"),
        "file_bitrate": _int(s.get("bitrate")),
        "video_codec": s.get("video_codec") or None,
        "video_resolution": s.get("video_full_resolution") or None,
        "video_bit_depth": _int(s.get("video_bit_depth")),
        "video_dynamic_range": s.get("video_dynamic_range") or None,
        "audio_codec": s.get("audio_codec") or None,
        "subtitle_codec": s.get("subtitle_codec") or None,
        "stream_bitrate": _int(s.get("stream_bitrate")),
        "stream_video_codec": s.get("stream_video_codec") or None,
        "stream_video_resolution": s.get("stream_video_full_resolution") or None,
        "stream_audio_codec": s.get("stream_audio_codec") or None,
        "transcode_decision": s.get("transcode_decision") or None,
        "video_decision": s.get("video_decision") or None,
        "audio_decision": s.get("audio_decision") or None,
        "subtitle_decision": s.get("subtitle_decision") or None,
        "container_decision": s.get("container_decision") or None,
        "transcode_hw": _hw(s),
        # Only Plex reports these, so a stream recorded through Tautulli
        # leaves them empty rather than claiming something it was not told.
        "transcode_hw_requested": s.get("transcode_hw_requested"),
        "transcode_hw_decode": s.get("transcode_hw_decode"),
        "transcode_hw_encode": s.get("transcode_hw_encode"),
        "transcode_protocol": s.get("transcode_protocol"),
        "video_profile": s.get("video_profile"),
        "video_frame_rate": s.get("video_frame_rate"),
        "audio_channels": _int(s.get("audio_channels")),
        "audio_language": s.get("audio_language"),
        "subtitle_language": s.get("subtitle_language"),
        "transcode_speed_min": _plausible_speed(_float(s.get("transcode_speed"))),
        "causes": ",".join(causes) or None,
        "primary_cause": causes[0] if causes else None,
        "bandwidth_max": _int(s.get("bandwidth")),
        "progress_start": _int(s.get("progress_percent")),
        "progress_end": _int(s.get("progress_percent")),
        "started_at": stamp,
        "last_seen_at": stamp,
    }


def merge(previous: dict[str, Any], s: dict[str, Any], now: float) -> dict[str, Any]:
    """A later poll folded into what was already known: worst decisions, every
    cause, peak bandwidth, slowest transcode, and the latest position."""
    fresh = row_for(s, now)
    out = dict(previous)
    for key in ("transcode_decision", "video_decision", "audio_decision", "subtitle_decision", "container_decision"):
        out[key] = _worst(previous.get(key), fresh.get(key))
    for key in ("stream_video_codec", "stream_video_resolution", "stream_audio_codec", "quality_profile",
                "subtitle_codec", "ip_address", "location"):
        if fresh.get(key):
            out[key] = fresh[key]
    causes = [c for c in (previous.get("causes") or "").split(",") if c]
    for c in (fresh.get("causes") or "").split(","):
        if c and c not in causes:
            causes.append(c)
    ordered = [c for c in CAUSES if c in causes]
    out["causes"] = ",".join(ordered) or None
    out["primary_cause"] = ordered[0] if ordered else None
    out["transcode_hw"] = bool(previous.get("transcode_hw")) or bool(fresh.get("transcode_hw"))
    speeds = [v for v in (previous.get("transcode_speed_min"), fresh.get("transcode_speed_min")) if v]
    out["transcode_speed_min"] = min(speeds) if speeds else None
    peaks = [v for v in (previous.get("bandwidth_max"), fresh.get("bandwidth_max")) if v is not None]
    out["bandwidth_max"] = max(peaks) if peaks else None
    rates = [v for v in (previous.get("stream_bitrate"), fresh.get("stream_bitrate")) if v is not None]
    out["stream_bitrate"] = max(rates) if rates else None
    out["progress_end"] = fresh.get("progress_end")
    out["last_seen_at"] = fresh["last_seen_at"]
    return out


# ---- persistence -------------------------------------------------------------------

def save(row: dict[str, Any], row_id: int | None) -> int | None:
    """Insert or update one stream. Never raises: losing a row must not stop
    the enforcer, which calls this from its poll."""
    from app.db import session_scope
    from app.models import StreamSession

    try:
        with session_scope() as db:
            if row_id is None:
                obj = StreamSession(**row)
                db.add(obj)
                db.flush()
                return obj.id
            db.execute(update(StreamSession).where(StreamSession.id == row_id).values(**row))
            return row_id
    except Exception:  # noqa: BLE001
        log.exception("could not record a stream")
        return row_id


def seen(sessions: list[dict[str, Any]], now: float | None = None) -> None:
    """Record the devices in these live sessions, so one that has never
    finished a play still has a page to open.

    Deliberately narrow: it writes what is on screen now and nothing derived.
    The play count and the earliest sighting are still the GROUP BY's job in
    refresh_devices, which runs over the whole of history and is the authority.
    Never raises, for the same reason save does not: the enforcer polls this.
    """
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import Device

    pairs = {
        (s.get("machine_id"), s.get("user_id"))
        for s in sessions
        if s.get("machine_id") and s.get("user_id") is not None
    }
    if not pairs:
        return
    try:
        stamp = int(time.time() if now is None else now)
        with session_scope() as db:
            # On a fresh install everything is unknown, and flagging the lot as
            # new is noise rather than a signal. refresh_devices makes the same
            # call for the same reason.
            first_run = db.execute(select(Device.machine_id).limit(1)).first() is None
            for s in sessions:
                machine_id, user_id = s.get("machine_id"), s.get("user_id")
                if not machine_id or user_id is None:
                    continue
                row = db.execute(
                    select(Device).where(Device.machine_id == machine_id, Device.user_id == user_id)
                ).scalar_one_or_none()
                if row is None:
                    db.add(Device(
                        machine_id=machine_id, user_id=user_id, player=s.get("player"),
                        platform=s.get("platform"), product=s.get("product"),
                        first_seen=stamp, last_seen=stamp, play_count=0,
                        is_new_unreviewed=not first_run,
                    ))
                    continue
                # Only what this sighting actually knows. first_seen is never
                # moved forward, and the review flag is left where it is.
                row.last_seen = max(row.last_seen or 0, stamp)
                for field in ("player", "platform", "product"):
                    if s.get(field):
                        setattr(row, field, s[field])
    except Exception:  # noqa: BLE001
        log.exception("could not record the devices that are streaming")


def finish(row_id: int, ended: float, buffer_count: int, buffer_seconds: float) -> None:
    from app.db import session_scope
    from app.models import StreamSession

    try:
        with session_scope() as db:
            db.execute(
                update(StreamSession)
                .where(StreamSession.id == row_id)
                .values(ended_at=datetime.fromtimestamp(ended, UTC), buffer_count=buffer_count,
                        buffer_seconds=round(buffer_seconds, 1))
            )
    except Exception:  # noqa: BLE001
        log.exception("could not close a stream record")


_last_alert = 0.0

PLEX_UPLOAD_KEY = "plex_upload_kbps"
PLEX_STREAM_LIMIT_KEY = "plex_stream_limit_kbps"


def plex_upload() -> tuple[int | None, int | None]:
    """Plex's own Internet upload speed and remote stream limit, in kbps, as
    last read from the server (None if never read; 0 means unlimited)."""
    from app.db import session_scope
    from app.models import SyncState

    with session_scope() as db:
        values = [db.get(SyncState, k) for k in (PLEX_UPLOAD_KEY, PLEX_STREAM_LIMIT_KEY)]
        return tuple(_int(v.value) if v is not None else None for v in values)  # type: ignore[return-value]


def upload_capacity() -> tuple[float, str]:
    """The upload to measure against, in Mbps, and where it came from: the
    Settings value when set, otherwise Plex's Internet upload speed."""
    from app.settings_store import current

    configured = float(getattr(current(), "upload_capacity_mbps", 0) or 0)
    if configured > 0:
        return configured, "settings"
    plex, _ = plex_upload()
    if plex:
        return plex / 1000, "plex"
    return 0.0, "unknown"


async def read_plex_upload(client) -> tuple[int | None, int | None]:
    """Read and remember Plex's upload settings, through Tautulli."""
    from app.db import session_scope
    from app.models import SyncState

    found = []
    for pref, key in (("WanTotalMaxUploadRate", PLEX_UPLOAD_KEY), ("WanPerStreamMaxUploadRate", PLEX_STREAM_LIMIT_KEY)):
        try:
            value = _int(await client.call("get_server_pref", pref=pref))
        except Exception as exc:  # noqa: BLE001 - an old Tautulli or a blip; keep the last value
            log.debug("could not read %s: %s", pref, exc)
            value = None
        if value is not None:
            with session_scope() as db:
                db.merge(SyncState(key=key, value=str(value)))
        found.append(value)
    return found[0], found[1]


def sample(activity: dict[str, Any], sessions: list[dict[str, Any]], now: float) -> None:
    """Fold one poll into this minute's bandwidth sample, keeping the peak."""
    from app.db import session_scope
    from app.models import BandwidthSample

    minute = int(now // 60 * 60)
    wan = _int(activity.get("wan_bandwidth")) or 0
    lan = _int(activity.get("lan_bandwidth")) or 0
    transcodes = sum(1 for s in sessions if _lower(s.get("transcode_decision")) == "transcode")
    values = {
        "minute": minute,
        "wan_kbps": wan,
        "lan_kbps": lan,
        "streams": len(sessions),
        "remote_streams": sum(1 for s in sessions if _lower(s.get("location")) == "wan"),
        "transcodes": transcodes,
        "hw_transcodes": sum(1 for s in sessions if _hw(s)),
    }
    try:
        with session_scope() as db:
            stmt = insert(BandwidthSample).values(**values)
            from sqlalchemy import func

            stmt = stmt.on_conflict_do_update(
                index_elements=["minute"],
                set_={k: func.max(getattr(BandwidthSample, k), stmt.excluded[k]) for k in values if k != "minute"},
            )
            db.execute(stmt)
    except Exception:  # noqa: BLE001
        log.exception("could not record a bandwidth sample")
    _maybe_alert(wan, values["remote_streams"], now)


def _maybe_alert(wan_kbps: int, remote: int, now: float) -> None:
    """One notification when upload use crosses the alert level, then quiet
    for half an hour, so a busy evening is one message, not hundreds."""
    global _last_alert
    from app.settings_store import current

    settings = current()
    capacity, _ = upload_capacity()
    percent = int(getattr(settings, "upload_alert_percent", 0) or 0)
    if capacity <= 0 or percent <= 0:
        return
    used = wan_kbps / 1000 / capacity * 100
    if used < percent or now - _last_alert < 1800:
        return
    _last_alert = now
    message = (
        f"Upload at {used:.0f}% ({wan_kbps / 1000:.1f} of {capacity:g} Mbps) with "
        f"{remote} remote stream{'' if remote == 1 else 's'}. Streams may start buffering."
    )
    log.warning(message)
    from app import audit

    audit.record(None, "server.upload_alert", message, actor="Cartographarr")

    import asyncio

    from app.integrations.notify import apprise_notifier

    if apprise_notifier.configured():
        try:
            asyncio.get_running_loop().create_task(apprise_notifier.send("Upload nearly full", message))
        except RuntimeError:
            # Called from the sweep's worker thread, which has no event loop.
            try:
                asyncio.run(apprise_notifier.send("Upload nearly full", message))
            except Exception:  # noqa: BLE001 - a failed notification must not stop recording
                log.exception("could not send the upload alert")


def prune(keep_days: int = 400) -> int:
    from app.db import session_scope
    from app.models import BandwidthSample

    cutoff = int(time.time() - keep_days * 86400)
    with session_scope() as db:
        result = db.execute(delete(BandwidthSample).where(BandwidthSample.minute < cutoff))
        return result.rowcount or 0


# ---- what a remote viewer can actually take ---------------------------------

WINDOW_DAYS = 90
"""How far back to look for an answer. A season of watching, so a month of one
household's bad line does not decide it."""

ENOUGH_CLEAN = 25
ENOUGH_STALLED = 5
"""Below this there is no answer worth giving, only a guess dressed up as one."""


def _percentile(values: list[int], share: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))]


def bitrate_advice(days: int = WINDOW_DAYS) -> dict[str, Any]:
    """Where remote watching starts going wrong on this server.

    The threshold in Settings decides which files Library calls a problem for
    remote viewers, and out of the box it is a round number rather than
    anything about this house. Every remote stream is already recorded with
    the file's bitrate and whether it stalled, so the answer is in there: the
    bitrate most remote streams manage, against the bitrate the ones that
    stalled were at.

    It is deliberately not automatic. A stall can be a bad evening on somebody
    else's line as easily as a file that is too big, so this offers a number
    and says what it is made of.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.db import session_scope
    from app.models import StreamSession

    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    with session_scope() as db:
        rows = db.execute(
            select(StreamSession.file_bitrate, StreamSession.buffer_count)
            .where(StreamSession.started_at >= cutoff, StreamSession.location == "wan",
                   StreamSession.file_bitrate.is_not(None))
        ).all()

    clean = [int(bitrate) for bitrate, buffers in rows if not buffers]
    stalled = [int(bitrate) for bitrate, buffers in rows if buffers]
    mbps = lambda kbps: round(kbps / 1000, 1) if kbps else None  # noqa: E731

    answer: dict[str, Any] = {
        "days": days,
        "clean_streams": len(clean),
        "stalled_streams": len(stalled),
        "clean_typical": mbps(_percentile(clean, 0.5)),
        "clean_high": mbps(_percentile(clean, 0.9)),
        "stalled_typical": mbps(_percentile(stalled, 0.5)),
        "stalled_high": mbps(_percentile(stalled, 0.75)),
        "suggestion": None,
        "why": None,
    }
    if len(clean) < ENOUGH_CLEAN or len(stalled) < ENOUGH_STALLED:
        answer["why"] = (
            f"Not enough remote watching yet to say: {len(clean)} streams that played cleanly and "
            f"{len(stalled)} that stalled, in {days} days."
        )
        return answer

    clean_high = answer["clean_high"]
    stalled_high = answer["stalled_high"]
    if clean_high is None or stalled_high is None or stalled_high <= clean_high:
        answer["why"] = (
            "The files that stalled are no bigger than the ones that played cleanly, so the bitrate is not what "
            "is going wrong out there. Look at Why beside the store, or at the viewers themselves."
        )
        return answer

    # Rounded to the nearest half, because a threshold of 8.4 implies a
    # precision that watching 200 streams does not give you.
    answer["suggestion"] = round(clean_high * 2) / 2
    answer["why"] = (
        f"Nine in ten remote streams that played cleanly were {clean_high} Mbps or under, while the ones that "
        f"stalled ran up to {stalled_high} Mbps. Flagging files above {answer['suggestion']} Mbps catches the "
        "band your remote viewers struggle with."
    )
    return answer

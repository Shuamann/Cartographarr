"""Live activity, read from Plex itself.

Deliberately the same shape Tautulli's activity comes back in, field for
field, because everything downstream, the tracker, the rules, the ban list,
the map and the stream cards, already understands that shape. Changing where
the sessions come from should not change anything that reads them.

Everything the app records about a stream is here: the viewer's address, and
whether they are local, relayed and secure, which is what the map, the geo
rules and the address bans are built on. Tautulli is not needed for any of it.
Only history from before the app started watching needs Tautulli, and that is
an import rather than a dependency.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# How Plex names a transcode decision against how this app does.
DECISIONS = {
    "directplay": "direct play",
    "copy": "copy",
    "transcode": "transcode",
}


def _decision(value: Any) -> str | None:
    if not value:
        return None
    return DECISIONS.get(str(value).lower().replace(" ", ""), str(value).lower())


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _flag(obj: Any, name: str) -> bool | None:
    """True, False, or not said. Plex leaves these out rather than saying no,
    and "we were not told" is not the same answer as "no"."""
    if obj is None:
        return None
    value = getattr(obj, name, None)
    return None if value is None else bool(value)


def _first(items):
    return items[0] if items else None


def _session(video: Any) -> dict[str, Any]:
    """One live session, in the shape the rest of the app already reads."""
    player = _first(getattr(video, "players", []) or [])
    # Plex names it in the singular, and its id is the Plex account id, which
    # is the same number this app already files everything under: a ban, a
    # privacy scope and four years of history all key on it.
    account = getattr(video, "user", None)
    user = _first(getattr(video, "usernames", []) or [])
    media = _first(getattr(video, "media", []) or [])
    part = _first(getattr(media, "parts", []) or []) if media else None
    session = getattr(video, "session", None)
    session = _first(session) if isinstance(session, list) else session
    transcode = getattr(video, "transcodeSession", None)

    stream_video = stream_audio = stream_subtitle = None
    if part is not None:
        for stream in getattr(part, "streams", []) or []:
            kind = getattr(stream, "streamType", None)
            # The selected one, where Plex says which: a file with six audio
            # tracks has one that is actually being played.
            chosen = bool(getattr(stream, "selected", False))
            if kind == 1 and (stream_video is None or chosen):
                stream_video = stream
            elif kind == 2 and (stream_audio is None or chosen):
                stream_audio = stream
            elif kind == 3 and (stream_subtitle is None or chosen):
                stream_subtitle = stream

    duration = _int(getattr(video, "duration", None)) or 0
    offset = _int(getattr(video, "viewOffset", None)) or 0
    decision = _decision(getattr(transcode, "videoDecision", None) if transcode else None)
    audio = _decision(getattr(transcode, "audioDecision", None) if transcode else None)
    overall = _overall(transcode, decision, audio)

    return {
        "session_key": str(getattr(video, "sessionKey", "") or ""),
        "session_id": getattr(session, "id", None) if session else None,
        "user_id": _int(getattr(player, "userID", None) if player else None)
        or _int(getattr(account, "id", None) if account else None),
        "username": (getattr(account, "username", None) if account else None) or user,
        "friendly_name": (getattr(account, "title", None) if account else None) or user,
        "user_thumb": getattr(account, "thumb", None) if account else None,
        # Plex calls it a machine identifier, which is the same thing Tautulli
        # reports and what every ban is written against.
        "machine_id": getattr(player, "machineIdentifier", None) if player else None,
        "player": getattr(player, "title", None) if player else None,
        "platform": getattr(player, "platform", None) if player else None,
        "product": getattr(player, "product", None) if player else None,
        "device": getattr(player, "device", None) if player else None,
        # The whole reason this is possible: Plex tells us where they are.
        "ip_address": getattr(player, "address", None) if player else None,
        "ip_address_public": getattr(player, "remotePublicAddress", None) if player else None,
        "location": ("lan" if getattr(player, "local", False) else "wan") if player else None,
        "secure": bool(getattr(player, "secure", False)) if player else None,
        "relayed": bool(getattr(player, "relayed", False)) if player else None,
        "state": getattr(player, "state", None) if player else None,
        "progress_percent": round(offset / duration * 100) if duration else 0,
        "view_offset": offset,
        "duration": duration,
        "media_type": getattr(video, "type", None),
        "full_title": _full_title(video),
        "title": getattr(video, "title", None),
        "grandparent_title": getattr(video, "grandparentTitle", None),
        "parent_title": getattr(video, "parentTitle", None),
        "media_index": _int(getattr(video, "index", None)),
        "parent_media_index": _int(getattr(video, "parentIndex", None)),
        "year": _int(getattr(video, "year", None)),
        "thumb": getattr(video, "thumb", None),
        "art": getattr(video, "art", None),
        "rating_key": _int(getattr(video, "ratingKey", None)),
        "grandparent_rating_key": _int(getattr(video, "grandparentRatingKey", None)),
        "section_id": _int(getattr(video, "librarySectionID", None)),
        "library_name": getattr(video, "librarySectionTitle", None),
        "transcode_decision": overall,
        "video_decision": decision,
        "audio_decision": audio,
        "subtitle_decision": _decision(getattr(transcode, "subtitleDecision", None) if transcode else None),
        "video_full_resolution": getattr(media, "videoResolution", None) if media else None,
        "stream_video_full_resolution": (
            getattr(transcode, "videoDecision", None) and getattr(media, "videoResolution", None)
        ) if media else None,
        "quality_profile": _quality(media, transcode),
        "bandwidth": _int(getattr(session, "bandwidth", None) if session else None),
        "container": getattr(media, "container", None) if media else None,
        "stream_container": getattr(transcode, "container", None) if transcode else None,
        "stream_bitrate": _int(getattr(media, "bitrate", None)) if media else None,
        "transcode_speed": getattr(transcode, "speed", None) if transcode else None,
        "throttled": bool(getattr(transcode, "throttled", False)) if transcode else None,
        "video_codec": getattr(stream_video, "codec", None) if stream_video else (
            getattr(media, "videoCodec", None) if media else None
        ),
        "stream_video_codec": getattr(transcode, "videoCodec", None) if transcode else None,
        "audio_codec": getattr(stream_audio, "codec", None) if stream_audio else (
            getattr(media, "audioCodec", None) if media else None
        ),
        "stream_audio_codec": getattr(transcode, "audioCodec", None) if transcode else None,
        "audio_channel_layout": getattr(stream_audio, "audioChannelLayout", None) if stream_audio else None,
        "summary": getattr(video, "summary", None),
        "content_rating": getattr(video, "contentRating", None),
        "originally_available_at": str(getattr(video, "originallyAvailableAt", "") or "") or None,
        # Detail Tautulli does not report, kept because this app exists to
        # judge how a stream went.
        #
        # The hardware ones are the useful find. Plex says whether hardware
        # was asked for and, separately, whether it was actually used to
        # decode and to encode. Asked for and not granted is the case somebody
        # wants explained, and nothing could say it before.
        "transcode_hw_requested": _flag(transcode, "transcodeHwRequested"),
        "transcode_hw_decode": _flag(transcode, "transcodeHwDecoding"),
        "transcode_hw_encode": _flag(transcode, "transcodeHwEncoding"),
        "transcode_hw_full": _flag(transcode, "transcodeHwFullPipeline"),
        "transcode_protocol": getattr(transcode, "protocol", None) if transcode else None,
        "transcode_progress": _float(getattr(transcode, "progress", None) if transcode else None),
        "video_profile": getattr(media, "videoProfile", None) if media else None,
        "video_frame_rate": getattr(media, "videoFrameRate", None) if media else None,
        "video_width": _int(getattr(media, "width", None)) if media else None,
        "video_height": _int(getattr(media, "height", None)) if media else None,
        "audio_channels": _int(getattr(media, "audioChannels", None)) if media else None,
        # Which track they are actually listening to and reading, which is the
        # question behind half the findings this app makes about a file.
        "audio_language": getattr(stream_audio, "language", None) if stream_audio else None,
        "subtitle_language": getattr(stream_subtitle, "language", None) if stream_subtitle else None,
        "subtitle_codec": getattr(stream_subtitle, "codec", None) if stream_subtitle else None,
        "optimized_for_streaming": _flag(media, "optimizedForStreaming"),
    }


def _overall(transcode: Any, video_decision: str | None, audio_decision: str | None) -> str:
    """The one word the whole session is judged by.

    Plex answers per stream; the rest of this app, every rule anybody has
    written and four years of history all use one word for the session, the
    way Tautulli reports it. A stream whose video is copied and whose audio is
    being converted is a transcode, because something is being converted and
    that is what the word is for. Getting this wrong would silently change
    what every existing rule matches.
    """
    if transcode is None:
        return "direct play"
    if "transcode" in (video_decision, audio_decision):
        return "transcode"
    if "copy" in (video_decision, audio_decision):
        return "copy"
    return "direct play"


def _full_title(video: Any) -> str | None:
    show = getattr(video, "grandparentTitle", None)
    title = getattr(video, "title", None)
    return f"{show} - {title}" if show and title else title


def _quality(media: Any, transcode: Any) -> str | None:
    if transcode is not None and getattr(transcode, "videoDecision", None) == "transcode":
        return getattr(transcode, "videoCodec", None)
    return getattr(media, "videoResolution", None) if media else None


def read() -> dict[str, Any]:
    """Everything playing now, in the shape Tautulli's activity comes back in.

    Blocking, because plexapi is. Call it in a worker thread.
    """
    from app.plex.server import server

    plex = server()
    sessions = [_session(v) for v in plex.sessions()]
    return {
        "sessions": sessions,
        "stream_count": len(sessions),
        "transcode_count": sum(1 for s in sessions if s["transcode_decision"] == "transcode"),
        "total_bandwidth": sum(s["bandwidth"] or 0 for s in sessions),
        "wan_bandwidth": sum(s["bandwidth"] or 0 for s in sessions if s["location"] == "wan"),
    }

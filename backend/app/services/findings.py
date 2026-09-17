"""What exactly is wrong with a file, and what to do about it.

Library lists say a file is a problem. This says why, in terms of this file's
own tracks and how it was watched, and gives a fix a person can act on:
something to do in Radarr or Sonarr, a remux, or a setting.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from app.services.library import COMPATIBLE_AUDIO, IMAGE_SUBTITLES, LEGACY_CONTAINERS

# How much a finding matters, for ordering: "stops playback working well"
# before "tidy up".
SEVERITY = {"high": 0, "medium": 1, "low": 2}

AUDIO_NAMES = {
    "truehd": "Dolby TrueHD", "dca": "DTS", "dca-ma": "DTS-HD MA", "dts": "DTS", "dtshd": "DTS-HD",
    "flac": "FLAC", "pcm": "PCM", "mlp": "Dolby TrueHD", "aac": "AAC", "ac3": "Dolby Digital (AC3)",
    "eac3": "Dolby Digital Plus (EAC3)", "mp3": "MP3", "opus": "Opus",
}
SUB_NAMES = {"pgs": "PGS", "vobsub": "VobSub", "dvd_subtitle": "DVD", "hdmv_pgs_subtitle": "PGS", "ass": "ASS", "ssa": "SSA", "srt": "SRT"}


def _tracks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except ValueError:
        return []


def _audio_list(tracks: list[dict[str, Any]]) -> str:
    parts = []
    for t in tracks:
        codec = str(t.get("codec") or "").lower()
        name = AUDIO_NAMES.get(codec, codec.upper() or "unknown")
        ch = t.get("channels")
        layout = {2: "stereo", 6: "5.1", 8: "7.1"}.get(ch, f"{ch} channels" if ch else "")
        parts.append(" ".join(x for x in (name, layout, f"({t.get('language')})" if t.get("language") else "") if x))
    return ", ".join(parts)


def _finding(key: str, severity: str, title: str, detail: str, fix: str, arr: str | None = None) -> dict[str, Any]:
    return {"key": key, "severity": severity, "title": title, "detail": detail, "fix": fix, "arr": arr}


def _mbps(kbps: int | None) -> str:
    return f"{(kbps or 0) / 1000:.1f} Mbps"


def explain(file: dict[str, Any], threshold_kbps: int, transcode_causes: list[dict[str, Any]] | None = None,
            stall_causes: list[dict[str, Any]] | None = None, arr_label: str = "Radarr") -> list[dict[str, Any]]:
    """Every finding for one file, most serious first.

    `file` is library.describe_file() plus play figures (plays, remote_plays,
    transcodes). Causes are counts from live streams and stalls.
    """
    out: list[dict[str, Any]] = []
    audio = _tracks(file.get("audio_tracks"))
    subs = _tracks(file.get("subtitle_tracks"))
    codecs = {str(a.get("codec") or "").lower() for a in audio}
    sub_codecs = [str(s.get("codec") or "").lower() for s in subs]
    remote = int(file.get("remote_plays") or 0)
    plays = int(file.get("plays") or 0)
    transcodes = int(file.get("transcodes") or 0)
    causes = {c["cause"]: c["streams"] for c in (transcode_causes or [])}
    # Reasons read back from Tautulli for older plays, rather than seen live.
    from_history = any(c.get("from_history") for c in (transcode_causes or []))
    stalls = {c["cause"]: c["stalls"] for c in (stall_causes or [])}

    # ---- audio --------------------------------------------------------------
    if audio and not codecs & COMPATIBLE_AUDIO:
        out.append(_finding(
            "no_compatible_audio", "high", "No audio most devices can play",
            f"The only audio is {_audio_list(audio)}. TVs, streaming sticks, phones and browsers mostly cannot "
            "decode these, so Plex converts the audio for them, and some clients convert the video too.",
            "Replace it with a release that also has an AC3, EAC3 or AAC track, or add one by remuxing "
            "(ffmpeg or a Tdarr flow can add an AAC stereo track and keep the original).",
            arr=f"In {arr_label}, a custom format that scores releases with a compatible audio track helps "
                "future downloads; Search for a replacement looks now.",
        ))
    elif causes.get("audio_channels") and any(
        str(a.get("codec") or "").lower() == "aac" and (a.get("channels") or 0) > 2 for a in audio
    ) and not any(str(a.get("codec") or "").lower() in ("ac3", "eac3") for a in audio):
        n = causes["audio_channels"]
        out.append(_finding(
            "aac_surround", "medium", "AAC surround audio",
            f"The audio is {_audio_list(audio)}. Surround AAC is unusual: Roku, many TVs and soundbars only take AAC "
            f"in stereo, so Plex converted the audio on {n} recorded stream{'s' if n != 1 else ''}.",
            "Replace it with a release that has AC3 or EAC3 5.1 audio (passed straight through almost everywhere), "
            "or add an AC3 5.1 or AAC stereo track by remuxing.",
            arr=f"Search for a replacement in {arr_label} only helps if the new release has different audio; "
                "tagging and picking one by hand is more reliable here.",
        ))
    elif causes.get("audio_codec") or causes.get("audio_channels"):
        n = causes.get("audio_codec", 0) + causes.get("audio_channels", 0)
        out.append(_finding(
            "audio_transcoded", "medium", "Audio converted for some viewers",
            f"Audio was converted on {n} recorded stream{'s' if n != 1 else ''}. The file has {_audio_list(audio) or 'no recorded audio tracks'}; "
            "the devices involved could not play the track chosen, or not with that many channels.",
            "Add a stereo AAC track for devices limited to two channels, or check the viewer has not picked a "
            "lossless track in the Plex app.",
        ))

    untagged = [a for a in audio if not a.get("language") or str(a.get("language")).lower() in ("und", "unknown")]
    if len(audio) > 1 and untagged:
        out.append(_finding(
            "untagged_audio", "low", "Audio track with no language",
            f"{len(untagged)} of {len(audio)} audio tracks have no language set, so Plex cannot pick the viewer's "
            "language automatically and may start on the wrong one.",
            "Set the language without re-encoding: mkvpropedit file.mkv --edit track:a2 --set language=jpn "
            "(track number and language to suit).",
        ))

    # ---- subtitles --------------------------------------------------------------
    if subs and all(c in IMAGE_SUBTITLES for c in sub_codecs):
        kinds = Counter(SUB_NAMES.get(c, c.upper()) for c in sub_codecs)
        out.append(_finding(
            "image_subtitles_only", "medium", "Only image subtitles",
            f"All {len(subs)} subtitle tracks are pictures ({', '.join(f'{k} x{v}' for k, v in kinds.items())}). "
            "Most clients cannot overlay them, so turning subtitles on makes Plex burn them into the video, "
            "which is a full video transcode.",
            "Add SRT subtitles (Bazarr fetches them automatically), or convert these with OCR (Subtitle Edit).",
            arr=f"Bazarr, beside {arr_label}, can keep SRT subtitles for everything.",
        ))
    styled = sum(1 for c in sub_codecs if c in ("ass", "ssa"))
    if styled:
        burned = causes.get("subtitle_burn", 0)
        out.append(_finding(
            "styled_subtitles", "medium" if burned else "low", "Styled (ASS) subtitles",
            f"{styled} subtitle track{'s are' if styled != 1 else ' is'} ASS or SSA, with fonts and positioning. Many TVs and "
            "sticks cannot draw them, so Plex burns them in and transcodes the video. Common with anime, and a "
            "likely cause of stalls when someone switches language or turns subtitles on."
            + (f" Subtitles were burned in on {burned} recorded stream{'s' if burned != 1 else ''}." if burned else ""),
            "Add an SRT copy of the same subtitles so devices without ASS support get plain text, or ask "
            "viewers on those devices to pick the SRT track. Plex Web and some Android TV clients draw ASS "
            "themselves.",
        ))
    if len(subs) >= 6:
        groups = Counter((str(s.get("codec")), str(s.get("language")), bool(s.get("forced"))) for s in subs)
        (codec, language, _), count = groups.most_common(1)[0]
        if count >= 3:
            out.append(_finding(
                "subtitle_clutter", "low", "Many duplicate subtitle tracks",
                f"{len(subs)} subtitle tracks, {count} of them the same ({SUB_NAMES.get(codec.lower(), codec.upper())}, "
                f"{language if language != 'None' else 'no language'}). Every client reads the full list when a "
                "stream starts, and a long one can slow the start on older devices.",
                "Remux without the duplicates (MKVToolNix, no re-encode), or remove external duplicates Bazarr "
                "or Plex agents added.",
            ))

    # ---- video and bitrate ----------------------------------------------------
    bitrate = file.get("file_bitrate")
    if bitrate and bitrate >= threshold_kbps and remote:
        out.append(_finding(
            "over_threshold", "high" if transcodes else "medium", "Bitrate high for remote viewing",
            f"Averages {_mbps(bitrate)}, over your {_mbps(threshold_kbps)} limit, and was played remotely "
            f"{remote} time{'s' if remote != 1 else ''}. Peaks run well above the average, so a remote viewer's "
            "connection or your upload may not keep up, which shows as stalls or a quality drop.",
            "Keep a smaller copy for remote viewers: Plex Optimize (Optimized for TV or Mobile), or a second "
            "1080p version, or replace it with a smaller release.",
            arr=f"Search for a replacement in {arr_label} only helps if the quality profile prefers a smaller "
                "release; otherwise tag it and pick one by hand.",
        ))
    if causes.get("video_codec") or (file.get("video_codec") in ("hevc", "av1", "vc1", "mpeg2video") and transcodes and not causes):
        codec = str(file.get("video_codec") or "").upper()
        depth = f" {file.get('video_bit_depth')}-bit" if file.get("video_bit_depth") else ""
        seen = causes.get("video_codec")
        out.append(_finding(
            "video_codec", "high" if (plays and transcodes / plays >= 0.5) else "medium", "Video format not supported everywhere",
            f"The video is {codec}{depth}. "
            + (f"On {seen} recorded stream{'s' if seen != 1 else ''} the device could not play it, so Plex converted it. "
               if seen else f"{transcodes} of {plays} plays were transcoded, and this format is the likely reason. ")
            + "Older Fire TV sticks, some Rokus and many browsers lack HEVC or 10-bit support.",
            "Keep an H.264 version beside it for those devices, or replace it with an H.264 release if most "
            "viewers are on older hardware.",
            arr=f"Search for a replacement in {arr_label} follows its quality profile; a custom format that "
                "prefers x264 steers it.",
        ))
    if causes.get("hdr_tonemap"):
        n = causes["hdr_tonemap"]
        out.append(_finding(
            "hdr_tonemap", "high", "HDR converted to SDR",
            f"This is {file.get('video_dynamic_range') or 'HDR'} and was tone mapped to SDR on {n} recorded stream"
            f"{'s' if n != 1 else ''}, one of the heaviest transcodes Plex does.",
            "Make sure hardware tone mapping is on in Plex (Settings, Transcoder), or keep an SDR version for "
            "viewers without HDR screens.",
        ))
    if causes.get("quality_setting"):
        n = causes["quality_setting"]
        out.append(_finding(
            "quality_setting", "low", "Viewer's quality set below original",
            f"On {n} stream{'s' if n != 1 else ''} the Plex app asked for less than Original quality, so the "
            "server converted it down. That is the viewer's app setting, not the file.",
            "Ask them to set Remote Streaming quality to Original or Maximum in their Plex app, if your upload "
            "allows it.",
        ))
    if causes.get("video_bitrate") and not causes.get("quality_setting"):
        n = causes["video_bitrate"]
        out.append(_finding(
            "video_bitrate", "medium", "Resolution or bitrate reduced",
            f"On {n} stream{'s' if n != 1 else ''} the video was reduced to fit, usually because of your remote "
            "streaming limit in Plex or the viewer's connection.",
            "Raise Plex's remote streaming limit if upload allows (Settings, Remote Access), or keep a smaller "
            "version.",
        ))
    if causes.get("subtitle_burn") and not styled and not (subs and all(c in IMAGE_SUBTITLES for c in sub_codecs)):
        n = causes["subtitle_burn"]
        out.append(_finding(
            "subtitle_burn", "medium", "Subtitles burned in",
            f"Subtitles were burned into the video on {n} stream{'s' if n != 1 else ''}, which forces a video transcode.",
            "Offer SRT subtitles, which nearly every client draws itself.",
        ))
    if not causes and plays and remote >= 2 and transcodes / max(plays, 1) >= 0.5 and not out:
        out.append(_finding(
            "transcoded_unknown", "medium", "Usually transcoded, reason not recorded yet",
            f"{transcodes} of {plays} plays were transcoded. These plays happened before streams were recorded "
            "live, so the exact reason is not known.",
            "The reason appears here after the next few plays. Meanwhile the file details below (video format, "
            "audio, subtitles) usually show it.",
        ))

    # ---- container ------------------------------------------------------------
    container = str(file.get("file_container") or "").lower()
    if container in LEGACY_CONTAINERS:
        out.append(_finding(
            "legacy_container", "low", f"Old container ({container.upper()})",
            f"{container.upper()} files seek slowly, lack modern track features, and some clients will not direct "
            "play them.",
            "Remux to MKV or MP4 without re-encoding (ffmpeg -i in.avi -c copy out.mkv), or replace with a "
            "modern release.",
            arr=f"Search for a replacement in {arr_label} usually finds a modern release.",
        ))

    # ---- stalls ----------------------------------------------------------------
    total_stalls = sum(stalls.values())
    if total_stalls:
        top = max(stalls, key=stalls.get)
        why = {
            "file": ("several people have stalled on this title, so the file is the common factor",
                     "Look at the bitrate and formats above; a smaller or more compatible copy is the usual fix."),
            "server": ("others stalled at the same time, so it was the server or its connection",
                       "Check upload use in Reports, Server load, around those times."),
            "upload": ("your upload was nearly full at the time",
                       "Lower Plex's remote streaming limit or keep smaller versions of busy titles."),
            "viewer": ("the viewer stalls on many titles, so it is their device or connection",
                       "Nothing to change in the file; suggest wired or 5 GHz Wi-Fi, or a lower quality setting."),
        }.get(top, ("no pattern yet", "Watch whether it happens again."))
        out.append(_finding(
            "stalls", "high" if top == "file" else "medium", "Stalls",
            f"{total_stalls} stall{'s' if total_stalls != 1 else ''} recorded; most likely {why[0]}.",
            why[1],
        ))

    if from_history:
        for f in out:
            if f["key"] in ("audio_transcoded", "aac_surround", "styled_subtitles", "video_codec", "hdr_tonemap", "quality_setting",
                            "video_bitrate", "subtitle_burn"):
                f["detail"] = f["detail"].replace("recorded stream", "recent play") + " (Read from Tautulli's details of the latest transcoded plays.)"

    out.sort(key=lambda f: SEVERITY[f["severity"]])
    return out

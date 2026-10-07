"""What a tidy would be worth, per step.

The panel said what each step would do and never what it would be worth, so
somebody deciding whether to tidy two hundred files had no number to decide
on. It is computable from what is already stored: a track's bitrate and how
long the file runs. Measured across the library this was written against,
160 GB sat in audio tracks past the first, in 431 files over two gigabytes.

Each test here was watched failing against the mistake it names.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.services import mediafix

HOUR = 3_600_000  # milliseconds


def item(audio=(), subtitles=(), duration=HOUR, container="mkv"):
    return SimpleNamespace(
        rating_key=1,
        title="A Film",
        full_title="A Film",
        file_path="/tv/A Film.mkv",
        file_container=container,
        duration=duration,
        audio_tracks=json.dumps(list(audio)),
        subtitle_tracks=json.dumps(list(subtitles)),
    )


def track(codec="aac", language="eng", bitrate=None, channels=2, **kw):
    return {"codec": codec, "language": language, "bitrate": bitrate, "channels": channels, **kw}


def steps(plan):
    return {s["key"]: s.get("size_change") for s in plan["steps"]}


def test_a_track_being_added_is_an_exact_figure(client):
    """The encoder is told a fixed bitrate, so this is not an estimate. 192
    kilobits a second over an hour is 86.4 megabytes, and the number on the
    card has to be the number the file grows by."""
    plan = mediafix.plan(item(audio=[track(codec="dca", channels=6, bitrate=1500)]))
    assert steps(plan)["add_aac_track"] == int(192 * 1000 / 8 * 3600)


def test_a_surround_file_is_quoted_the_surround_bitrate(client):
    """AC3 is written at 640k for surround and 192k for stereo, and quoting
    the stereo figure for a 5.1 file understates it by a factor of three."""
    surround = mediafix.plan(item(audio=[track(codec="dca", channels=6, bitrate=1500)]))
    stereo = mediafix.plan(item(audio=[track(codec="dca", channels=2, bitrate=1500)]))
    assert steps(surround)["no_compatible_audio"] == int(640 * 1000 / 8 * 3600)
    assert steps(stereo)["no_compatible_audio"] == int(192 * 1000 / 8 * 3600)


def test_dropping_a_track_makes_the_file_smaller(client, monkeypatch):
    """One sign throughout, so the card adds the steps up rather than working
    out per step which way each one goes."""
    # Patched on mediafix, not on settings_store: the module binds the name at
    # import, so patching the source leaves the copy it already holds.
    monkeypatch.setattr(mediafix, "current", lambda: SimpleNamespace(
        preferred_audio_language="", keep_subtitle_languages="", keep_audio_languages="eng",
    ))
    plan = mediafix.plan(item(audio=[
        track(language="eng", bitrate=640, channels=6),
        track(language="jpn", bitrate=1500, channels=6),
    ]))
    assert steps(plan)["keep_audio_languages"] == -int(1500 * 1000 / 8 * 3600)


def test_a_track_with_no_bitrate_is_not_counted_as_nothing(client, monkeypatch):
    """A picture subtitle often carries no bitrate, and some muxers write none
    for audio either: about one file in ten. Zero reads as "this step frees
    nothing", which is an answer, and the truth is that nobody knows."""
    # Patched on mediafix, not on settings_store: the module binds the name at
    # import, so patching the source leaves the copy it already holds.
    monkeypatch.setattr(mediafix, "current", lambda: SimpleNamespace(
        preferred_audio_language="", keep_subtitle_languages="eng", keep_audio_languages="",
    ))
    plan = mediafix.plan(item(
        audio=[track(language="eng", bitrate=640)],
        subtitles=[
            {"codec": "srt", "language": "eng"},
            {"codec": "pgs", "language": "fre", "bitrate": None},
        ],
    ))
    assert steps(plan)["keep_subtitle_languages"] is None


def test_one_unknown_track_makes_the_whole_step_unknown(client, monkeypatch):
    """A total missing a term is not a total, and printing it as one
    understates what is there while reading like a complete answer."""
    # Patched on mediafix, not on settings_store: the module binds the name at
    # import, so patching the source leaves the copy it already holds.
    monkeypatch.setattr(mediafix, "current", lambda: SimpleNamespace(
        preferred_audio_language="", keep_subtitle_languages="", keep_audio_languages="eng",
    ))
    plan = mediafix.plan(item(audio=[
        track(language="eng", bitrate=640),
        track(language="jpn", bitrate=1500),
        track(language="fre", bitrate=None),
    ]))
    assert steps(plan)["keep_audio_languages"] is None


def test_a_step_that_only_reorders_says_so(client, monkeypatch):
    """Zero is a real answer here and must not be confused with not knowing:
    putting a track first changes nothing about the size."""
    # Patched on mediafix, not on settings_store: the module binds the name at
    # import, so patching the source leaves the copy it already holds.
    monkeypatch.setattr(mediafix, "current", lambda: SimpleNamespace(
        preferred_audio_language="eng", keep_subtitle_languages="", keep_audio_languages="",
    ))
    plan = mediafix.plan(item(audio=[
        track(language="jpn", bitrate=640),
        track(language="eng", bitrate=640),
    ]))
    assert steps(plan)["default_audio"] == 0


def test_rewrapping_a_container_changes_nothing(client):
    plan = mediafix.plan(item(audio=[track(bitrate=192)], container="avi"))
    assert steps(plan)["legacy_container"] == 0


def test_a_file_of_unknown_length_can_say_nothing_about_size(client):
    """Without a duration a bitrate is not a number of bytes. Treating a
    missing duration as zero would quote every step as freeing nothing."""
    plan = mediafix.plan(item(audio=[track(codec="dca", channels=6, bitrate=1500)], duration=None))
    assert steps(plan)["add_aac_track"] is None


def test_the_plan_carries_how_long_the_file_runs(client):
    assert mediafix.plan(item(audio=[track(bitrate=192)]))["duration"] == HOUR

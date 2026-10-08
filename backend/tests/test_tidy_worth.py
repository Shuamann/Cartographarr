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


def test_a_whole_list_totals_what_it_would_come_to(client, monkeypatch):
    """A dry run that says "two hundred files" answers how many and not
    whether it is worth it."""
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import cleanup
    from tests.test_auth import claim

    claim(client)
    with session_scope() as db:
        for key, bitrate in ((1, 1500), (2, 900)):
            db.add(MediaItem(
                rating_key=key, media_type="movie", title=f"Film {key}", full_title=f"Film {key}",
                file_path=f"/movies/{key}.mkv", file_container="mkv", duration=HOUR, section_id=1,
                audio_tracks=json.dumps([
                    {"codec": "ac3", "language": "eng", "bitrate": 640, "channels": 6},
                    {"codec": "dca", "language": "jpn", "bitrate": bitrate, "channels": 6},
                ]),
                subtitle_tracks=json.dumps([]),
            ))

    monkeypatch.setattr(cleanup, "attention", lambda *a, **k: {
        "items": [{"rating_key": 1, "title": "Film 1"}, {"rating_key": 2, "title": "Film 2"}]
    })
    monkeypatch.setattr(mediafix, "current", lambda: SimpleNamespace(
        preferred_audio_language="", keep_subtitle_languages="", keep_audio_languages="eng",
    ))

    out = client.post("/api/library/tidy/many", json={"kind": "messy", "dry_run": True}).json()
    assert out["queued"] == 2
    assert out["size_unknown"] == 0
    # Both dubs dropped, 1500 and 900 kbps over an hour, less the AAC stereo
    # track each one is offered because neither has one, at 192 kbps. Adds and
    # drops net off against each other, which is the point of one sign: the
    # answer is what the disk ends up with, not what was taken away.
    assert out["size_change"] == -int((1500 + 900 - 192 * 2) * 1000 / 8 * 3600)


def test_a_file_whose_tracks_state_no_size_is_counted_apart(client, monkeypatch):
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import cleanup
    from tests.test_auth import claim

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(
            rating_key=1, media_type="movie", title="Film", full_title="Film",
            file_path="/movies/1.mkv", file_container="mkv", duration=HOUR, section_id=1,
            audio_tracks=json.dumps([
                {"codec": "ac3", "language": "eng", "bitrate": 640, "channels": 6},
                {"codec": "dca", "language": "jpn", "bitrate": None, "channels": 6},
            ]),
            subtitle_tracks=json.dumps([]),
        ))
    monkeypatch.setattr(cleanup, "attention", lambda *a, **k: {"items": [{"rating_key": 1, "title": "Film"}]})
    monkeypatch.setattr(mediafix, "current", lambda: SimpleNamespace(
        preferred_audio_language="", keep_subtitle_languages="", keep_audio_languages="eng",
    ))
    out = client.post("/api/library/tidy/many", json={"kind": "messy", "dry_run": True}).json()
    assert out["size_unknown"] == 1
    assert out["size_change"] == 0


def test_a_tidy_that_grows_a_file_records_the_growth_as_a_loss(client):
    """What the file lost, so a negative number means it grew. Adding a track
    every television can play costs a few hundred megabytes and is the point
    of the step, so this is a normal outcome and not an error. It is written
    down here because the column is read in two places and a negative read as
    a saving prints "350 MB smaller" about a file that got bigger.
    """
    from app.db import session_scope
    from app.models import MediaJob
    from app.services import mediafix

    with session_scope() as db:
        db.add(MediaJob(id=1, rating_key=1, path="/movies/1.mkv", status="running"))
    mediafix._finish(1, "done", "Tidied, 1 change made, Plex told", saved=-350_000_000)
    with session_scope() as db:
        assert db.get(MediaJob, 1).saved_bytes == -350_000_000

"""Tidying a file's tracks: what it would do, and the command it builds.

The command is the part worth pinning down. It runs against somebody's only
copy of a film, so every one of these checks is about what must survive:
the picture, the original audio, and anything the plan did not mention.
"""

import json
from types import SimpleNamespace

from app.services import mediafix
from tests.test_auth import claim


def item(**over):
    base = dict(
        rating_key=1,
        title="A Film",
        full_title="A Film",
        file_path="/movies/A Film/a.mkv",
        file_container="mkv",
        audio_tracks=json.dumps([{"codec": "aac", "channels": 2, "language": "eng"}]),
        subtitle_tracks=json.dumps([]),
    )
    return SimpleNamespace(**{**base, **over})


# ---- the plan ---------------------------------------------------------------

def test_a_tidy_file_has_nothing_to_do():
    assert mediafix.plan(item())["steps"] == []


def test_styled_subtitles_are_offered_as_srt():
    subs = [{"codec": "ass", "language": "eng", "location": "embedded"}]
    steps = mediafix.plan(item(subtitle_tracks=json.dumps(subs)))["steps"]
    assert [s["key"] for s in steps] == ["styled_subtitles"]
    assert "SRT" in steps[0]["what"]


def test_picture_subtitles_go_only_when_the_same_language_is_there_as_text():
    both = [
        {"codec": "pgs", "language": "eng", "location": "embedded"},
        {"codec": "srt", "language": "eng", "location": "embedded"},
    ]
    assert "image_subtitles_only" in [s["key"] for s in mediafix.plan(item(subtitle_tracks=json.dumps(both)))["steps"]]

    # The only way to read it: left alone, whatever it costs in transcoding.
    alone = [{"codec": "pgs", "language": "eng", "location": "embedded"}]
    assert "image_subtitles_only" not in [
        s["key"] for s in mediafix.plan(item(subtitle_tracks=json.dumps(alone)))["steps"]
    ]


def test_sidecar_subtitles_are_not_touched():
    """An external .srt is a file of its own, not a track in this one."""
    subs = [{"codec": "ass", "language": "eng", "location": "external"}]
    assert mediafix.plan(item(subtitle_tracks=json.dumps(subs)))["steps"] == []


def test_audio_nothing_can_play_gets_a_track_added_not_replaced():
    audio = [{"codec": "truehd", "channels": 8, "language": "eng"}]
    steps = mediafix.plan(item(audio_tracks=json.dumps(audio)))["steps"]
    assert [s["key"] for s in steps] == ["no_compatible_audio"]
    assert "beside the original" in steps[0]["what"]


def test_an_old_container_is_offered_a_repackage():
    steps = mediafix.plan(item(file_container="avi"))["steps"]
    assert [s["key"] for s in steps] == ["legacy_container"]


def test_nothing_in_a_plan_re_encodes_the_picture():
    busy = item(
        file_container="avi",
        audio_tracks=json.dumps([{"codec": "dca", "channels": 6}]),
        subtitle_tracks=json.dumps([{"codec": "ass", "language": "eng", "location": "embedded"}]),
    )
    assert mediafix.plan(busy)["re_encodes_video"] is False


# ---- the command ------------------------------------------------------------

STREAMS = [
    {"index": 0, "codec_type": "video", "codec_name": "h264"},
    {"index": 1, "codec_type": "audio", "codec_name": "dts", "channels": 6, "tags": {"language": "eng"}},
    {"index": 2, "codec_type": "subtitle", "codec_name": "ass", "tags": {"language": "eng"}},
    {"index": 3, "codec_type": "subtitle", "codec_name": "pgs", "tags": {"language": "eng"}},
    {"index": 4, "codec_type": "subtitle", "codec_name": "ass", "tags": {"language": "eng"}},
    {"index": 5, "codec_type": "subtitle", "codec_name": "srt", "tags": {"language": "fra"}},
]


def mapped(argv):
    return [argv[i + 1] for i, part in enumerate(argv) if part == "-map"]


def test_the_picture_and_the_original_audio_always_come_across():
    argv = mediafix.build(STREAMS, [], "in.mkv", "out.mkv")
    assert "0:0" in mapped(argv) and "0:1" in mapped(argv)
    assert "-c" in argv and argv[argv.index("-c") + 1] == "copy"


def test_nothing_is_dropped_by_a_step_that_was_not_asked_for():
    argv = mediafix.build(STREAMS, ["styled_subtitles"], "in.mkv", "out.mkv")
    assert mapped(argv) == ["0:0", "0:1", "0:2", "0:3", "0:4", "0:5"]


def test_duplicates_go_but_one_of_each_kind_stays():
    argv = mediafix.build(STREAMS, ["subtitle_clutter"], "in.mkv", "out.mkv")
    # The second English ASS goes; the first, the picture track and the French
    # one stay, because they are each the first of their kind.
    assert mapped(argv) == ["0:0", "0:1", "0:2", "0:3", "0:5"]


def test_a_picture_track_goes_only_when_its_language_exists_as_text():
    argv = mediafix.build(STREAMS, ["image_subtitles_only"], "in.mkv", "out.mkv")
    assert "0:3" not in mapped(argv)  # English exists as ASS

    only_pictures = [STREAMS[0], STREAMS[1], {"index": 2, "codec_type": "subtitle", "codec_name": "pgs",
                                              "tags": {"language": "eng"}}]
    argv = mediafix.build(only_pictures, ["image_subtitles_only"], "in.mkv", "out.mkv")
    assert "0:2" in mapped(argv)


def test_only_the_styled_tracks_are_rewritten():
    argv = mediafix.build(STREAMS, ["styled_subtitles"], "in.mkv", "out.mkv")
    # Output positions 0 and 2 are the two ASS tracks; the picture track at 1
    # and the French SRT at 3 are left as they are.
    assert "-c:s:0" in argv and argv[argv.index("-c:s:0") + 1] == "srt"
    assert "-c:s:2" in argv
    assert "-c:s:1" not in argv and "-c:s:3" not in argv


def test_the_added_audio_sits_after_the_original_and_keeps_it():
    argv = mediafix.build(STREAMS, ["no_compatible_audio"], "in.mkv", "out.mkv")
    assert mapped(argv).count("0:1") == 2  # once copied, once encoded
    assert argv[argv.index("-c:a:1") + 1] == "ac3"
    assert argv[argv.index("-ac:a:1") + 1] == "6"


def test_an_added_track_never_claims_more_channels_than_it_has():
    stereo = [STREAMS[0], {"index": 1, "codec_type": "audio", "codec_name": "truehd", "channels": 2}]
    argv = mediafix.build(stereo, ["no_compatible_audio"], "in.mkv", "out.mkv")
    assert argv[argv.index("-ac:a:1") + 1] == "2"


# ---- what the page is told ---------------------------------------------------

def test_the_page_is_told_when_the_media_is_not_mounted(client):
    from app.db import session_scope
    from app.models import MediaItem

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=5, title="Somewhere Else", media_type="movie",
                         file_path="/nowhere/that/exists.mkv", file_container="avi"))
    answer = client.get("/api/library/file/5/tidy").json()
    assert answer["local_path"] is None
    assert [s["key"] for s in answer["steps"]] == ["legacy_container"]


def test_tidying_is_refused_when_the_file_cannot_be_reached(client):
    from app.db import session_scope
    from app.models import MediaItem

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=6, title="Somewhere Else", media_type="movie",
                         file_path="/nowhere/that/exists.mkv", file_container="avi"))
    answer = client.post("/api/library/file/6/tidy", json={"steps": ["legacy_container"]})
    assert answer.status_code == 409 and "cannot see" in answer.json()["detail"]


def test_viewers_cannot_tidy_anything(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "all")
    assert client.get("/api/library/file/1/tidy").status_code == 403
    assert client.post("/api/library/file/1/tidy", json={"steps": ["legacy_container"]}).status_code == 403
    assert client.get("/api/library/tidy/jobs").status_code == 403


# ---- the language steps ------------------------------------------------------

def settings(monkeypatch, **over):
    """Settings as the page would have saved them."""
    import app.settings_store as store

    real = store.current()
    patched = lambda: real.model_copy(update=over)  # noqa: E731
    monkeypatch.setattr(store, "current", patched)
    monkeypatch.setattr(mediafix, "current", patched)


MANY = [
    {"index": 0, "codec_type": "video", "codec_name": "h264"},
    {"index": 1, "codec_type": "audio", "codec_name": "eac3", "channels": 6, "tags": {"language": "jpn"}},
    {"index": 2, "codec_type": "audio", "codec_name": "aac", "channels": 2, "tags": {"language": "eng"}},
    {"index": 3, "codec_type": "audio", "codec_name": "aac", "channels": 2, "tags": {"language": "fra"}},
    {"index": 4, "codec_type": "subtitle", "codec_name": "srt", "tags": {"language": "eng"}},
    {"index": 5, "codec_type": "subtitle", "codec_name": "srt", "tags": {"language": "zho"}},
    {"index": 6, "codec_type": "subtitle", "codec_name": "srt", "tags": {"language": "spa"}},
]


def test_the_preferred_language_goes_first(monkeypatch):
    """Players take the first track, which is how a film ends up in Japanese
    for a household that does not read subtitles."""
    settings(monkeypatch, preferred_audio_language="eng")
    argv = mediafix.build(MANY, ["default_audio"], "in.mkv", "out.mkv")
    assert mapped(argv) == ["0:0", "0:2", "0:1", "0:3", "0:4", "0:5", "0:6"]
    # Said in the disposition too, since some players ignore the order.
    assert argv[argv.index("-disposition:a:0") + 1] == "default"


def test_only_the_wanted_subtitle_languages_survive(monkeypatch):
    settings(monkeypatch, keep_subtitle_languages="eng, spa ,jpn")
    argv = mediafix.build(MANY, ["keep_subtitle_languages"], "in.mkv", "out.mkv")
    assert "0:5" not in mapped(argv)  # Chinese
    assert "0:4" in mapped(argv) and "0:6" in mapped(argv)
    # Audio is untouched by a subtitle step.
    assert all(f"0:{n}" in mapped(argv) for n in (1, 2, 3))


def test_spare_dubs_go_but_a_file_is_never_left_silent(monkeypatch):
    settings(monkeypatch, keep_audio_languages="eng,jpn")
    argv = mediafix.build(MANY, ["keep_audio_languages"], "in.mkv", "out.mkv")
    assert "0:3" not in mapped(argv) and "0:1" in mapped(argv) and "0:2" in mapped(argv)

    # Nothing matches: everything is kept rather than leaving no sound at all.
    settings(monkeypatch, keep_audio_languages="kor")
    argv = mediafix.build(MANY, ["keep_audio_languages"], "in.mkv", "out.mkv")
    assert all(f"0:{n}" in mapped(argv) for n in (1, 2, 3))


def test_the_added_track_is_numbered_after_the_ones_that_survived(monkeypatch):
    """Dropping a dub moves the output positions, and the encoder flags are
    written against those, not against what the file used to have."""
    settings(monkeypatch, keep_audio_languages="eng")
    argv = mediafix.build(MANY, ["keep_audio_languages", "no_compatible_audio"], "in.mkv", "out.mkv")
    # One audio track survives, so the added one is output audio 1.
    assert "-c:a:1" in argv and argv[argv.index("-c:a:1") + 1] == "ac3"
    assert "-c:a:3" not in argv


def test_the_language_steps_are_offered_only_when_settings_say_so(monkeypatch):
    tracks = json.dumps([{"codec": "eac3", "channels": 6, "language": "jpn"},
                         {"codec": "aac", "channels": 2, "language": "eng"}])
    subs = json.dumps([{"codec": "srt", "language": "eng", "location": "embedded"},
                       {"codec": "srt", "language": "zho", "location": "embedded"}])

    settings(monkeypatch)
    assert mediafix.plan(item(audio_tracks=tracks, subtitle_tracks=subs))["steps"] == []

    settings(monkeypatch, preferred_audio_language="eng", keep_subtitle_languages="eng")
    keys = [s["key"] for s in mediafix.plan(item(audio_tracks=tracks, subtitle_tracks=subs))["steps"]]
    assert "default_audio" in keys and "keep_subtitle_languages" in keys


def test_a_rule_can_ask_for_the_tidying(client, monkeypatch):
    """The action is the same work as the button, driven by the rules engine,
    so it answers to the cap and the record only switch like anything else."""
    import asyncio

    from app.actions import registry
    from app.db import session_scope
    from app.models import MediaItem

    claim(client)
    settings(monkeypatch, keep_subtitle_languages="eng")
    with session_scope() as db:
        db.add(MediaItem(rating_key=42, title="Subtitled", full_title="Subtitled", media_type="movie",
                         file_path="/nowhere/that/exists.mkv", file_container="mkv",
                         audio_tracks=json.dumps([{"codec": "aac", "channels": 2, "language": "eng"}]),
                         subtitle_tracks=json.dumps([
                             {"codec": "srt", "language": "eng", "location": "embedded"},
                             {"codec": "srt", "language": "zho", "location": "embedded"},
                         ])))

    action = registry.get("tidy_file")
    assert action.triggers == ("file", "issue")
    # The file cannot be reached from here, which is a refusal rather than a
    # half done job.
    try:
        asyncio.run(action.execute({"subject": "file", "rating_key": 42}, {}))
        raise AssertionError("should have refused")
    except LookupError as exc:
        assert "cannot see" in str(exc) or "ffmpeg" in str(exc)

    # And a file with nothing to do is said so, not queued.
    with session_scope() as db:
        db.add(MediaItem(rating_key=43, title="Fine", full_title="Fine", media_type="movie",
                         file_path="/nowhere/fine.mkv", file_container="mkv",
                         audio_tracks=json.dumps([{"codec": "aac", "channels": 2, "language": "eng"}]),
                         subtitle_tracks=json.dumps([])))
    assert "nothing to tidy" in asyncio.run(action.execute({"subject": "file", "rating_key": 43}, {}))

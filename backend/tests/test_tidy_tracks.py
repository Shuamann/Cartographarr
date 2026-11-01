from app.services import mediafix
from app.settings_store import trial

STREAMS = [
    {"index": 0, "codec_type": "video", "codec_name": "h264"},
    {"index": 1, "codec_type": "audio", "codec_name": "dts", "channels": 6, "tags": {"language": "eng"}},
    {"index": 2, "codec_type": "audio", "codec_name": "aac", "channels": 2, "tags": {"language": "fra"}},
    {"index": 3, "codec_type": "subtitle", "codec_name": "subrip", "tags": {"language": "eng"}},
    {"index": 4, "codec_type": "subtitle", "codec_name": "subrip", "tags": {"language": "fra"}},
]

ENGLISH_ONLY = {"keep_subtitle_languages": "eng", "keep_audio_languages": "eng", "preferred_audio_language": "eng"}


def kept(argv):
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-map"]


def test_a_ticked_subtitle_survives_a_setting_that_would_drop_it():
    """Somebody ticks the French subtitle on a server set to keep English."""
    with trial(ENGLISH_ONLY):
        argv = mediafix.build(
            STREAMS, [mediafix.CHOSEN, "keep_subtitle_languages"], "s.mkv", "t.mkv",
            {"subtitles": [1]},
        )
    assert "0:4" in kept(argv), "the French subtitle was ticked and must be kept"
    assert "0:3" not in kept(argv), "and the English one was not"


def test_a_ticked_audio_track_survives_the_same_way():
    with trial(ENGLISH_ONLY):
        argv = mediafix.build(
            STREAMS, [mediafix.CHOSEN, "keep_audio_languages"], "s.mkv", "t.mkv",
            {"audio": [1]},
        )
    assert "0:2" in kept(argv) and "0:1" not in kept(argv)


def test_the_track_chosen_to_play_first_is_the_one_that_plays_first():
    with trial(ENGLISH_ONLY):
        argv = mediafix.build(
            STREAMS, [mediafix.CHOSEN, "default_audio"], "s.mkv", "t.mkv",
            {"audio": [0, 1], "default_audio": 1},
        )
    audio = [m for m in kept(argv) if m in ("0:1", "0:2")]
    assert audio[0] == "0:2", "the French track was chosen to play first"


def test_the_settings_still_apply_when_nobody_has_chosen_anything():
    """The filters are not broken, only outranked."""
    with trial(ENGLISH_ONLY):
        argv = mediafix.build(STREAMS, ["keep_subtitle_languages", "keep_audio_languages"], "s.mkv", "t.mkv", {})
    assert kept(argv) == ["0:0", "0:1", "0:3"], "English audio and English subtitle only"


def test_choosing_subtitles_does_not_stop_the_audio_setting_applying():
    """Per kind, not all or nothing."""
    with trial(ENGLISH_ONLY):
        argv = mediafix.build(
            STREAMS, [mediafix.CHOSEN, "keep_subtitle_languages", "keep_audio_languages"], "s.mkv", "t.mkv",
            {"subtitles": [1]},
        )
    assert "0:4" in kept(argv), "the ticked subtitle survives"
    assert "0:2" not in kept(argv), "and the French audio still goes, because nobody said otherwise"


def test_a_choice_that_would_leave_the_file_silent_is_refused():
    with trial(ENGLISH_ONLY):
        argv = mediafix.build(STREAMS, [mediafix.CHOSEN], "s.mkv", "t.mkv", {"audio": []})
    assert any(m in kept(argv) for m in ("0:1", "0:2"))


# ---- one view of the file, not two -------------------------------------------


def an_item(subs, audio=None, container="mkv"):
    import json

    class Item:
        rating_key = 1
        full_title = title = "A Film"
        file_path = "/media/a.mkv"
        file_container = container
        audio_tracks = json.dumps(audio or [{"codec": "eac3", "channels": 6, "language": "eng"}])
        subtitle_tracks = json.dumps(subs)

    return Item()


def test_a_step_says_which_tracks_it_would_drop():
    """The panel showed a step reading "drop 79" above a list reading "keeping 90 of 90"."""
    subs = [
        {"codec": "subrip", "language": "eng", "location": "embedded"},
        {"codec": "subrip", "language": "fra", "location": "embedded"},
        {"codec": "subrip", "language": "deu", "location": "embedded"},
    ]
    with trial({"keep_subtitle_languages": "eng"}):
        found = mediafix.plan(an_item(subs))
    step = next(s for s in found["steps"] if s["key"] == "keep_subtitle_languages")
    assert step["drops_subtitles"] == [1, 2]


def test_the_duplicate_step_names_the_repeats_and_not_the_first_of_each():
    subs = [
        {"codec": "subrip", "language": "eng", "location": "embedded"},
        {"codec": "subrip", "language": "eng", "location": "embedded"},
        {"codec": "subrip", "language": "eng", "location": "embedded"},
        {"codec": "subrip", "language": "fra", "location": "embedded"},
        {"codec": "subrip", "language": "fra", "location": "embedded"},
    ]
    found = mediafix.plan(an_item(subs))
    step = next(s for s in found["steps"] if s["key"] == "subtitle_clutter")
    assert step["drops_subtitles"] == [1, 2, 4], "the second and third English, and the second French"


def test_the_audio_language_step_names_its_own_tracks():
    audio = [
        {"codec": "eac3", "channels": 6, "language": "eng"},
        {"codec": "ac3", "channels": 6, "language": "deu"},
    ]
    with trial({"keep_audio_languages": "eng"}):
        found = mediafix.plan(an_item([], audio))
    step = next(s for s in found["steps"] if s["key"] == "keep_audio_languages")
    assert step["drops_audio"] == [1]


def test_a_step_that_drops_nothing_says_nothing():
    found = mediafix.plan(an_item([]))
    for step in found["steps"]:
        assert not step.get("drops_subtitles") and not step.get("drops_audio"), step["key"]


def test_the_panel_can_tell_two_tracks_of_one_language_apart():
    subs = [
        {"codec": "pgs", "language": "eng", "location": "embedded", "forced": True, "title": "Forced"},
        {"codec": "pgs", "language": "eng", "location": "embedded", "sdh": True, "default": True},
    ]
    found = mediafix.plan(an_item(subs))
    first, second = found["subtitles"]
    assert first["forced"] is True and first["title"] == "Forced"
    assert second["sdh"] is True and second["default"] is True

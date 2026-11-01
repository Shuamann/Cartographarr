import json
import os
from types import SimpleNamespace

from app.db import session_scope
from app.models import MediaItem, MediaJob
from app.services import mediafix


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


# ---- the name the result is written under -----------------------------------


def suffix_for(source: str, steps: list[str]) -> str:
    """The same expression `_run` uses to pick the temporary file's suffix."""
    return ".mkv" if "legacy_container" in steps else (os.path.splitext(source)[1] or ".mkv")


def test_an_mp4_tidied_for_its_subtitles_stays_an_mp4():
    assert suffix_for("/movies/A Film/a.mp4", ["subtitle_clutter"]) == ".mp4"


def test_repackaging_is_the_one_thing_that_changes_the_container():
    assert suffix_for("/movies/A Film/a.avi", ["legacy_container"]) == ".mkv"


def test_an_mkv_stays_an_mkv():
    assert suffix_for("/movies/A Film/a.mkv", ["subtitle_clutter"]) == ".mkv"


def test_a_file_with_no_extension_gets_one():
    assert suffix_for("/movies/A Film/a", ["subtitle_clutter"]) == ".mkv"


def test_the_plan_never_offers_to_repackage_a_modern_container():
    """Which is why writing mkv regardless was wrong rather than merely odd."""
    for container in ("mkv", "mp4", "m4v"):
        steps = [s["key"] for s in mediafix.plan(item(file_container=container))["steps"]]
        assert "legacy_container" not in steps
    assert "legacy_container" in [s["key"] for s in mediafix.plan(item(file_container="avi"))["steps"]]


# ---- what the app knows afterwards ------------------------------------------


def test_the_item_is_marked_for_rereading(client):
    """Otherwise the page keeps reporting the problem that was just fixed."""
    with session_scope() as db:
        db.add(MediaItem(
            rating_key=7, title="A Film", media_type="movie",
            file_path="/movies/A Film/a.mkv", file_size=1000,
            file_checked_at=__import__("datetime").datetime(2026, 1, 1),
        ))

    mediafix._rewritten(7, "/movies/A Film/a.mkv", 400)

    with session_scope() as db:
        after = db.get(MediaItem, 7)
        assert after.file_checked_at is None
        assert after.file_size == 400


def test_a_renamed_file_takes_its_new_path_with_it(client):
    """The stored path pointed at something that had been deleted."""
    with session_scope() as db:
        db.add(MediaItem(rating_key=8, title="A Film", media_type="movie",
                         file_path="/movies/A Film/a.avi", file_size=1000))

    mediafix._rewritten(8, "/movies/A Film/a.mkv", 900)

    with session_scope() as db:
        assert db.get(MediaItem, 8).file_path == "/movies/A Film/a.mkv"


def test_an_item_that_has_gone_is_not_a_crash(client):
    """A file tidied and then removed from Plex before the job finished."""
    mediafix._rewritten(999, "/movies/Gone/x.mkv", 1)
    mediafix._rewritten(None, "/movies/Gone/x.mkv", 1)


# ---- the job record ---------------------------------------------------------


def test_a_queued_job_carries_the_item_it_is_for(client, monkeypatch):
    """`_run` reads rating_key off the job to say what changed afterwards."""
    # ffmpeg is in the image but not on a development machine, and queueing
    # refuses without it. What is being checked here is the row, not the tool.
    monkeypatch.setattr(mediafix, "tools", lambda: {"ready": True})
    with session_scope() as db:
        db.add(MediaItem(
            rating_key=9, title="A Film", media_type="movie",
            file_path=__file__,  # a file that exists, so queueing is allowed
            file_container="avi",
            audio_tracks=json.dumps([{"codec": "aac", "channels": 2}]),
            subtitle_tracks=json.dumps([]),
        ))

    job_id = mediafix.queue(9, ["legacy_container"], "a test")

    with session_scope() as db:
        job = db.get(MediaJob, job_id)
        assert job.rating_key == 9
        assert json.loads(job.steps)["steps"] == ["legacy_container"]

from __future__ import annotations

import pytest

from app.plex import maintenance


class Caught:
    """What was asked of Plex, instead of asking it."""

    def __init__(self):
        self.scans: list[tuple[int, str | None]] = []
        self.analysed: list[int] = []

    def install(self, monkeypatch, scan_raises=None, analyze_raises=None):
        def rescan(section_id, path=None):
            if scan_raises:
                raise scan_raises
            self.scans.append((section_id, path))

        def analyze(rating_key):
            if analyze_raises:
                raise analyze_raises
            self.analysed.append(rating_key)

        monkeypatch.setattr(maintenance, "rescan", rescan)
        monkeypatch.setattr(maintenance, "analyze", analyze)
        monkeypatch.setattr(maintenance, "section_of", lambda key: 7)


def test_a_file_rewritten_in_place_is_read_again(client, monkeypatch):
    """The whole point."""
    caught = Caught()
    caught.install(monkeypatch)
    done = maintenance.file_changed(100, "/tv/Show/S01E01.mkv", renamed=False)
    assert caught.analysed == [100]
    assert done["analysed"] is True


def test_a_file_whose_name_changed_makes_plex_walk_its_folder(client, monkeypatch):
    caught = Caught()
    caught.install(monkeypatch)
    maintenance.file_changed(100, "/tv/Show/Season 1/S01E01.avi", renamed=True)
    assert caught.scans == [(7, "/tv/Show/Season 1")]
    assert caught.analysed == [100]


def test_nothing_is_scanned_when_the_name_did_not_change(client, monkeypatch):
    """A scan walks a directory."""
    caught = Caught()
    caught.install(monkeypatch)
    maintenance.file_changed(100, "/tv/Show/S01E01.mkv", renamed=False)
    assert caught.scans == []


def test_a_server_that_will_not_answer_does_not_fail_the_job(client, monkeypatch):
    """A tidy that worked is not a tidy that failed because the server was restarting."""
    caught = Caught()
    caught.install(monkeypatch, scan_raises=RuntimeError("no"), analyze_raises=RuntimeError("no"))
    done = maintenance.file_changed(100, "/tv/Show/S01E01.mkv", renamed=True)
    assert done == {"scanned": False, "analysed": False}


def test_a_file_plex_never_knew_about_is_left_alone(client, monkeypatch):
    caught = Caught()
    caught.install(monkeypatch)
    assert maintenance.file_changed(None, "/tv/Show/S01E01.mkv", renamed=True)["analysed"] is False
    assert caught.scans == [] and caught.analysed == []


def test_the_folder_handed_over_is_plexs_own_and_not_this_containers(client, monkeypatch):
    """The two need not be mounted the same way."""
    caught = Caught()
    caught.install(monkeypatch)
    maintenance.file_changed(100, "/mnt/user/media/tv/Show/One.mkv", renamed=True)
    assert caught.scans == [(7, "/mnt/user/media/tv/Show")]


def test_an_item_in_no_known_library_is_still_read_again(client, monkeypatch):
    caught = Caught()
    caught.install(monkeypatch)
    monkeypatch.setattr(maintenance, "section_of", lambda key: None)
    maintenance.file_changed(100, "/tv/Show/One.mkv", renamed=True)
    assert caught.scans == []
    assert caught.analysed == [100]


@pytest.mark.parametrize("renamed", [True, False])
def test_the_row_keeps_plexs_path_and_not_the_one_ffmpeg_wrote_to(client, renamed):
    import os

    from app.db import session_scope
    from app.models import MediaItem
    from app.services import mediafix

    plex_path = "/mnt/user/media/tv/Show/One.avi"
    with session_scope() as db:
        db.add(MediaItem(rating_key=100, media_type="episode", file_path=plex_path, section_id=7))

    suffix = ".mkv" if renamed else ".avi"
    mediafix._rewritten(100, os.path.splitext(plex_path)[0] + suffix, 123)
    with session_scope() as db:
        assert db.get(MediaItem, 100).file_path == "/mnt/user/media/tv/Show/One" + suffix

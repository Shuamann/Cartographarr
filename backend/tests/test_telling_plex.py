"""Telling Plex that a file changed under it.

Tidying rewrote a file in place and never told the server, so Plex went on
reporting the tracks, the size and the duration from before the rewrite while
this app's own page showed the new ones. When a step repackaged the container
it was worse: the old file was deleted, a new one written beside it with a
different ending, and Plex went on listing a file that was not there until its
nightly scan. Pressing play got an error about a file this app removed on
purpose.

Each test here was watched failing against the mistake it names.
"""

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
    """The whole point. Plex has no reason to look at a file whose path has
    not changed, which is exactly what tidying leaves behind, so without this
    the server keeps answering with the tracks from before."""
    caught = Caught()
    caught.install(monkeypatch)
    done = maintenance.file_changed(100, "/tv/Show/S01E01.mkv", renamed=False)
    assert caught.analysed == [100]
    assert done["analysed"] is True


def test_a_file_whose_name_changed_makes_plex_walk_its_folder(client, monkeypatch):
    """Analysing alone cannot help here: the old file is gone and Plex is
    still listing it, and an analyse of a key whose file has vanished teaches
    the server nothing. Only a scan of the folder finds the new name."""
    caught = Caught()
    caught.install(monkeypatch)
    maintenance.file_changed(100, "/tv/Show/Season 1/S01E01.avi", renamed=True)
    assert caught.scans == [(7, "/tv/Show/Season 1")]
    assert caught.analysed == [100]


def test_nothing_is_scanned_when_the_name_did_not_change(client, monkeypatch):
    """A scan walks a directory. Asking for one on every tidy is that walk for
    no reason, since Plex already has the path."""
    caught = Caught()
    caught.install(monkeypatch)
    maintenance.file_changed(100, "/tv/Show/S01E01.mkv", renamed=False)
    assert caught.scans == []


def test_a_server_that_will_not_answer_does_not_fail_the_job(client, monkeypatch):
    """A tidy that worked is not a tidy that failed because the server was
    restarting. The nightly scan is still the floor, so the worst case without
    this call is the state everything was in before it existed."""
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
    """The two need not be mounted the same way. It is the server that has to
    find the folder, so handing it the path ffmpeg wrote to gives it a
    directory it cannot see."""
    caught = Caught()
    caught.install(monkeypatch)
    maintenance.file_changed(100, "/mnt/user/media/tv/Show/One.mkv", renamed=True)
    assert caught.scans == [(7, "/mnt/user/media/tv/Show")]


def test_an_item_in_no_known_library_is_still_read_again(client, monkeypatch):
    """Not knowing which library it is in is a reason not to scan, not a
    reason to give up on the item."""
    caught = Caught()
    caught.install(monkeypatch)
    monkeypatch.setattr(maintenance, "section_of", lambda key: None)
    maintenance.file_changed(100, "/tv/Show/One.mkv", renamed=True)
    assert caught.scans == []
    assert caught.analysed == [100]


@pytest.mark.parametrize("renamed", [True, False])
def test_the_row_keeps_plexs_path_and_not_the_one_ffmpeg_wrote_to(client, renamed):
    """media_items holds the paths Plex reports, and everything that reads
    them maps them to this container on the way out. Writing the container's
    path back in attributes the file to the wrong store on the Storage page,
    and hands Plex a folder it cannot find."""
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

"""Being told how big a disk really is, where it will not say.

A twenty terabyte NAS reported sixty one terabytes free, and the host agreed,
because the share told it so. The usual cause is a user share answering for
the whole array rather than for itself. Nothing read through statvfs can see
past that: the number is wrong before it arrives.

So it can be told. The stated capacity replaces the total, and what is in use
is then counted from the files this app can actually see there, which is a
different kind of answer and is said to be one.
"""

from app.services import space

TB = 1_000_000_000_000


def test_a_size_is_read_in_whatever_unit_reads_naturally():
    found = space.stated_sizes("/mnt/a = 20 TB\n/mnt/b=1500GB\n/mnt/c = 500 mb\n/mnt/d = 12345")
    assert found == {"/mnt/a": 20 * TB, "/mnt/b": 1_500_000_000_000, "/mnt/c": 500_000_000, "/mnt/d": 12345}


def test_a_typo_costs_the_override_and_not_the_page():
    """Guessing at what somebody meant by a size is how a disk ends up
    reported as a thousand times too big."""
    found = space.stated_sizes("/mnt/a = 20 TB\n/mnt/bad = notasize\nno equals here\n= 5TB\n/mnt/b =")
    assert found == {"/mnt/a": 20 * TB}


def test_a_trailing_slash_is_the_same_mount():
    assert space.stated_sizes("/mnt/a/ = 1TB") == {"/mnt/a": TB}


def test_a_file_under_a_stated_mount_counts_towards_it():
    """The share is stated once; the files live in folders under it."""
    stated = {"/mnt/user/media2": 20 * TB}
    assert space._stated_for("/mnt/user/media2/movies/a.mkv", stated) == 20 * TB
    assert space._stated_for("/mnt/user/media2", stated) == 20 * TB


def test_a_mount_nobody_wrote_down_is_left_as_the_disk_reported_it():
    """Only the shares that lie need telling, and the rest are read normally."""
    assert space._stated_for("/mnt/user/other", {"/mnt/user/media2": TB}) is None


def test_nothing_written_down_at_all_changes_nothing():
    assert space.stated_sizes("") == {} and space.stated_sizes("   \n\n") == {}


def test_the_page_is_told_which_kind_of_answer_it_is_looking_at(client, monkeypatch):
    """A figure worked out from the files this app knows about is not the same
    as a figure read off the disk, and presenting it as one would be the app
    being confidently wrong about somebody's array."""
    import shutil
    from types import SimpleNamespace

    from app.db import session_scope
    from app.models import MediaItem
    from app.services import mediafix
    from app.settings_store import save
    from tests.test_auth import claim

    claim(client)
    save({"disk_sizes": "/mnt/user/media2 = 20 TB"})
    with session_scope() as db:
        db.add(MediaItem(rating_key=1, section_id=1, media_type="movie", title="A", full_title="A",
                         file_path="/mnt/user/media2/films/a.mkv", file_size=5 * TB))

    monkeypatch.setattr(mediafix, "local_path", lambda path: path)
    monkeypatch.setattr(space, "forget_mounts", lambda: None)
    space._mounts["key"], space._mounts["value"] = None, None
    # The share answering for the whole array, which is the fault being fixed.
    monkeypatch.setattr(shutil, "disk_usage", lambda path: SimpleNamespace(total=61 * TB, free=61 * TB, used=0))
    monkeypatch.setattr("os.stat", lambda path: SimpleNamespace(st_dev=1))

    found = space.disks({"Films": ["/mnt/user/media2/films/a.mkv"]})
    row = found["Films"]
    assert row["total"] == 20 * TB, "the stated size, not the array's"
    assert row["used"] == 5 * TB, "counted from the files here"
    assert row["free"] == 15 * TB
    assert row["stated"] is True, "and the page is told which kind of answer it is"

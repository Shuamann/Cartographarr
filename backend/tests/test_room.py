"""Telling somebody before a disk fills.

A media server fills up. It is the one thing that goes wrong on every one of
them eventually, it gives plenty of warning, and nothing here was watching for
it: the Storage page says how much room is left and somebody has to go and
look.

The shape is the alert for a job that has stopped: one message when a disk
crosses a line, nothing more about that disk until it gets worse or recovers.
A warning sent every hour is a warning nobody reads.
"""

import pytest

from app.services import room


def disk(path="/mnt/array", free=100, total=1000, labels=None):
    return {"path": path, "free": free, "total": total, "labels": labels or ["Movies"]}


@pytest.fixture(autouse=True)
def clean():
    room.forget()
    yield
    room.forget()


def test_a_disk_crossing_the_line_is_news():
    news = room.check([disk(free=90, total=1000)], warn_at=10, critical_at=3)
    assert len(news) == 1 and news[0]["state"] == "low" and news[0]["percent"] == 9.0


def test_saying_it_again_every_hour_is_not_news():
    """The thing that makes an alert worth reading is that it is rare."""
    first = room.check([disk(free=90)], 10, 3)
    assert len(first) == 1
    for _ in range(5):
        assert room.check([disk(free=88)], 10, 3) == []


def test_getting_worse_is_news_again():
    room.check([disk(free=90)], 10, 3)
    news = room.check([disk(free=20)], 10, 3)
    assert len(news) == 1 and news[0]["state"] == "critical"


def test_recovering_is_news_too():
    """Otherwise somebody who cleared space is still waiting to hear."""
    room.check([disk(free=20)], 10, 3)
    news = room.check([disk(free=500)], 10, 3)
    assert len(news) == 1 and news[0]["state"] == "fine"
    assert "room again" in room.words(news[0])[0]


def test_a_disk_that_was_always_fine_says_nothing():
    """The alert is for news, and "this disk is fine" is not news."""
    assert room.check([disk(free=900)], 10, 3) == []


def test_two_disks_are_told_apart():
    news = room.check([disk(path="/a", free=900), disk(path="/b", free=20)], 10, 3)
    assert [n["path"] for n in news] == ["/b"]


def test_a_disk_nothing_can_read_is_skipped_rather_than_counted_as_full():
    """An unreadable mount with no free space reported is not a disk at zero,
    and treating it as one would cry wolf on every restart."""
    assert room.check([{"path": "/x", "free": None, "total": None}], 10, 3) == []
    assert room.check([{"path": "/y", "free": 0, "total": 0}], 10, 3) == []


def test_what_it_says_names_the_store_and_the_room_left():
    news = room.check([disk(free=2_000_000_000, total=100_000_000_000, labels=["Movies", "TV"])], 10, 3)
    heading, body = room.words(news[0])
    assert "Movies, TV" in heading and "nearly full" in heading
    assert "2.0 GB" in body and "100.0 GB" in body and "2.0%" in body


def test_it_is_a_task_so_it_runs_without_anybody_asking():
    from app import main, tasks  # noqa: F401 - importing main is what registers them

    assert "room_check" in tasks.TASKS
    assert tasks.TASKS["room_check"].interval() == 3600

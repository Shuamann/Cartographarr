"""Poster art: kept on disk, and never holding the database while it waits.

The second part is why this file exists. A poster wall asks for a hundred at
once; each one held a database session while Tautulli answered, out of a pool
of fifteen, so every other page waited behind the pictures.
"""

import inspect

from app.routers import data as data_router
from tests.test_auth import claim


def test_the_image_route_takes_no_database_session():
    """A session is a connection out of a small pool. This route talks to
    Tautulli, so it opens one only after the answer is back."""
    taken = inspect.signature(data_router.media_image).parameters
    assert "db" not in taken, "the image route must not hold a session while it fetches"
    assert set(taken) == {"rating_key", "width", "height"}


def test_live_activity_takes_no_session_either():
    """Polled by three pages at once, and it calls Tautulli first."""
    from app.routers import live

    assert "db" not in inspect.signature(live.activity_endpoint).parameters


def test_the_dashboard_does_not_hold_one_either():
    """It awaits Tautulli before counting anything, so a session taken as a
    dependency would be held for the whole round trip, once per open browser.
    The counts open their own inside the worker thread."""
    from app.routers import live

    assert "db" not in inspect.signature(live.dashboard).parameters
    assert "session_scope" in inspect.getsource(live.dashboard)


def test_a_kept_poster_is_served_from_disk(client, tmp_path, monkeypatch):
    claim(client)
    kept = data_router._poster_file(99, 200, 300)
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_bytes(b"\xff\xd8\xff" + b"pretend jpeg")

    def refuse(*a, **k):
        raise AssertionError("asked Tautulli for a poster it already had")

    monkeypatch.setattr(data_router.httpx, "AsyncClient", refuse)
    answer = client.get("/api/media/99/image?width=200&height=300")
    assert answer.status_code == 200 and answer.content.startswith(b"\xff\xd8\xff")
    kept.unlink()


def test_fetching_posters_is_bounded():
    """Four at a time: a wall of them should not become a flood Tautulli
    answers slowly for everybody."""
    assert data_router.POSTER_FETCHES._value == 4


def test_a_half_written_poster_is_never_served(tmp_path):
    where = tmp_path / "poster.jpg"
    data_router._keep_poster(where, b"some bytes")
    assert where.read_bytes() == b"some bytes"
    assert not (tmp_path / "poster.part").exists()


def test_an_unwritable_cache_costs_the_cache_not_the_picture(tmp_path):
    # A directory where the file should be: writing fails, and the request it
    # came from must not.
    where = tmp_path / "poster.jpg"
    where.mkdir()
    data_router._keep_poster(where, b"some bytes")
    assert where.is_dir()


def test_posters_are_asked_for_as_jpeg():
    """Left alone Tautulli returns PNG, and a 200x300 poster is 120 KB instead
    of 21 KB. The spelling matters: `jpeg` is accepted and ignored."""
    from app.routers import data

    assert data.POSTER_FORMAT == "jpg"
    source = inspect.getsource(data.media_image)
    assert '"img_format": POSTER_FORMAT' in source


def test_the_cache_name_carries_the_format():
    """So the PNGs kept by older builds are missed rather than served as JPEG."""
    from app.routers import data

    assert data._poster_file(7, 200, 300).name.endswith(".jpg")

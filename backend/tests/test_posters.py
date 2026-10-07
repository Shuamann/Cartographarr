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
    # Naming any of these would have FastAPI hand the route a session, which
    # it would then hold across a call to Tautulli. Query parameters it takes
    # besides those are its own business.
    assert not {"db", "session", "Db"} & set(taken), (
        "the image route must not hold a session while it fetches"
    )
    assert "rating_key" in taken


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
    from app.services import posters

    claim(client)
    kept = posters.path_for(99, "large")
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_bytes(b"\xff\xd8\xff" + b"pretend jpeg")

    def refuse(*a, **k):
        raise AssertionError("asked Tautulli for a poster it already had")

    monkeypatch.setattr(data_router.httpx, "AsyncClient", refuse)
    answer = client.get("/api/media/99/image?width=200&height=300")
    assert answer.status_code == 200 and answer.content.startswith(b"\xff\xd8\xff")
    kept.unlink()


def test_fetching_posters_is_bounded():
    """A wall of them should not become a flood Tautulli answers slowly for
    everybody. The exact number is a judgement, so this pins the bound rather
    than the figure: narrow enough to be polite, wide enough that opening a
    show does not leave its seasons queued behind the shows."""
    assert 4 <= data_router.POSTER_FETCHES._value <= 12


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


def test_the_cache_name_carries_the_format(client):
    """So the PNGs kept by older builds are missed rather than served as JPEG."""
    from app.services import posters

    assert posters.path_for(7, "large").name.endswith(".jpg")


# ---- the cache: three sizes, a modest JPEG, a folder of its own -------------


def _picture(width=1000, height=1500, mode="RGBA") -> bytes:
    """A large PNG, the kind Tautulli hands back when asked for a JPEG."""
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new(mode, (width, height), (200, 40, 40, 255) if mode == "RGBA" else (200, 40, 40)).save(out, "PNG")
    return out.getvalue()


class _Upstream:
    """Stands in for Plex's resizer, and counts what it was asked for."""

    def __init__(self, picture: bytes):
        self.picture = picture
        self.asked: list[dict] = []

    async def get(self, url, params=None, headers=None):
        self.asked.append(dict(params or {}))
        picture = self.picture

        class Answer:
            content = picture
            headers = {"content-type": "image/png"}

            def raise_for_status(self):
                return None

        return Answer()


def _plex_only(monkeypatch, picture: bytes) -> _Upstream:
    upstream = _Upstream(picture)
    monkeypatch.setattr(data_router, "plex_configured", lambda: True)
    monkeypatch.setattr(data_router, "tautulli_configured", lambda: False)
    monkeypatch.setattr(data_router, "_poster_art", lambda key, kind="poster": f"/library/metadata/{key}/thumb")
    monkeypatch.setattr(data_router, "_image_client", lambda settings: upstream)
    return upstream


def test_every_small_poster_is_one_file_fetched_once(client, monkeypatch):
    """A report, a row and a list ask at 46, 92 and 120 wide. One fetch, one
    file, and the browser scales it."""
    import io

    from PIL import Image

    from app.services import posters

    claim(client)
    upstream = _plex_only(monkeypatch, _picture())
    for width, height in ((46, 69), (92, 138), (120, 180)):
        answer = client.get(f"/api/media/5/image?width={width}&height={height}")
        assert answer.status_code == 200 and answer.headers["content-type"] == "image/jpeg"
    assert len(upstream.asked) == 1, "asked again for a size it already kept"
    assert (upstream.asked[0]["width"], upstream.asked[0]["height"]) == posters.SMALL
    kept = posters.path_for(5, "small")
    with Image.open(kept) as picture:
        assert picture.format == "JPEG" and picture.size[0] <= posters.SMALL[0] and picture.size[1] <= posters.SMALL[1]
    # A PNG of that size is a few hundred kilobytes; this is a few.
    assert kept.stat().st_size < 20_000
    assert io.BytesIO(answer.content).getvalue()[:3] == b"\xff\xd8\xff"


def test_larger_posters_and_backdrops_have_a_size_each(client, monkeypatch):
    from app.services import posters

    claim(client)
    upstream = _plex_only(monkeypatch, _picture())
    client.get("/api/media/6/image?width=200&height=300")
    client.get("/api/media/6/image?width=300&height=450")
    client.get("/api/media/6/image?kind=art&width=600&height=338")
    client.get("/api/media/6/image?kind=art&width=900&height=506")
    assert [(a["width"], a["height"]) for a in upstream.asked] == [posters.LARGE, posters.ART]
    assert posters.path_for(6, "large").exists() and posters.path_for(6, "art").exists()


def test_switched_off_nothing_is_kept_or_read(client, monkeypatch):
    from app.services import posters

    claim(client)
    assert client.put("/api/settings", json={"poster_cache": False}).status_code == 200
    stale = posters.path_for(8, "small")
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"\xff\xd8\xff" + b"an old one")
    upstream = _plex_only(monkeypatch, _picture())
    client.get("/api/media/8/image?width=92&height=138")
    client.get("/api/media/8/image?width=92&height=138")
    assert len(upstream.asked) == 2, "off means asked each time, not read from disk"
    assert stale.read_bytes().endswith(b"an old one"), "nor written"


def test_the_folder_is_a_setting_and_a_missing_one_is_not_made(client, tmp_path, monkeypatch):
    """A folder that does not exist is, in a container, a path nobody mapped.
    Making it would keep posters inside the container, gone on the next
    update, so the data directory is used and Settings says why."""
    from app.services import posters

    claim(client)
    elsewhere = tmp_path / "fast-pool" / "posters"
    client.put("/api/settings", json={"poster_cache_dir": str(elsewhere)})
    where, why = posters.folder()
    assert where == tmp_path / "posters" and str(elsewhere) in why
    assert not elsewhere.exists()

    elsewhere.mkdir(parents=True)
    _plex_only(monkeypatch, _picture())
    client.get("/api/media/9/image?width=92&height=138")
    assert (elsewhere / "9-small.jpg").exists()
    shown = client.get("/api/posters").json()
    assert shown["folder"] == str(elsewhere) and shown["note"] is None and shown["files"] == 1 and shown["bytes"] > 0


def test_clearing_removes_posters_and_nothing_else(client, tmp_path):
    """The folder is somebody's choice, so it may hold other things."""
    from app.services import posters

    claim(client)
    where = posters.folder()[0]
    where.mkdir(parents=True, exist_ok=True)
    for name in ("1-small.jpg", "1-large.jpg", "1-art.jpg", "2-200x300.jpg", "3-300x450-art.png"):
        (where / name).write_bytes(b"x")
    (where / "holiday.jpg").write_bytes(b"keep me")
    (where / "notes.txt").write_bytes(b"keep me")
    answer = client.delete("/api/posters").json()
    assert answer["removed"] == 5 and answer["files"] == 0
    assert sorted(p.name for p in where.iterdir()) == ["holiday.jpg", "notes.txt"]


def test_posters_kept_at_the_old_sizes_are_forgotten(client):
    from app.services import posters

    claim(client)
    where = posters.folder()[0]
    where.mkdir(parents=True, exist_ok=True)
    for name in ("4-200x300.jpg", "4-92x138.jpg", "4-900x506-art.jpg", "4-200x300.png", "4-small.jpg", "cover.jpg"):
        (where / name).write_bytes(b"x")
    assert posters.forget_older() == 4
    assert sorted(p.name for p in where.iterdir()) == ["4-small.jpg", "cover.jpg"]


def test_a_picture_that_cannot_be_read_is_passed_on_as_it_came():
    from app.services import posters

    assert posters.shrink(b"not a picture", 200, 300) == (b"not a picture", None)


def test_only_an_admin_sees_or_clears_the_cache(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "own")
    assert client.get("/api/posters").status_code == 403
    assert client.delete("/api/posters").status_code == 403

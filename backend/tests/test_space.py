from datetime import date, datetime, timedelta

from tests.test_auth import claim


def seed():
    from app.db import session_scope
    from app.models import Library, MediaItem

    with session_scope() as db:
        db.add(Library(section_id=1, name="Movies"))
        db.add(Library(section_id=2, name="TV"))
        db.add(MediaItem(rating_key=1, title="A", media_type="movie", section_id=1,
                         file_size=8_000_000_000, file_path="/movies/A/a.mkv"))
        db.add(MediaItem(rating_key=2, title="B", media_type="movie", section_id=1,
                         file_size=2_000_000_000, file_path="/movies/B/b.mkv"))
        db.add(MediaItem(rating_key=3, title="C", media_type="episode", section_id=2,
                         file_size=1_000_000_000, file_path="/tv/C/c.mkv"))
        # Metadata for something with no file is not space on a disk.
        db.add(MediaItem(rating_key=4, title="D", media_type="show", section_id=2))


def test_what_each_library_holds(client):
    from app.db import SessionLocal
    from app.services import space

    claim(client)
    seed()
    db = SessionLocal()
    try:
        r = space.report(db)
    finally:
        db.close()

    by_name = {lib["name"]: lib for lib in r["libraries"]}
    assert by_name["Movies"]["size"] == 10_000_000_000 and by_name["Movies"]["files"] == 2
    assert by_name["TV"]["size"] == 1_000_000_000 and by_name["TV"]["files"] == 1
    assert r["total"] == 11_000_000_000
    # Biggest first, since that is the one somebody is looking for.
    assert [lib["name"] for lib in r["libraries"]] == ["Movies", "TV"]
    # Nothing written down yet, so no change is claimed.
    assert by_name["Movies"]["change_week"] is None and r["recorded_days"] == 0


def test_change_needs_history_and_uses_the_nearest_earlier_day(client):
    from app.db import SessionLocal, session_scope
    from app.models import LibrarySize
    from app.services import space

    claim(client)
    seed()
    with session_scope() as db:
        # Nine days ago rather than exactly seven: the scan only writes on
        # days the app was running, and the nearest earlier day is the answer.
        db.add(LibrarySize(section_id=1, on_day=(date.today() - timedelta(days=9)).isoformat(),
                           files=1, bytes=6_000_000_000, at=datetime.now()))
        db.add(LibrarySize(section_id=1, on_day=(date.today() - timedelta(days=40)).isoformat(),
                           files=1, bytes=3_000_000_000, at=datetime.now()))

    db = SessionLocal()
    try:
        r = space.report(db)
    finally:
        db.close()
    movies = next(lib for lib in r["libraries"] if lib["name"] == "Movies")
    assert movies["change_week"] == 4_000_000_000 and movies["files_week"] == 1
    assert movies["change_month"] == 7_000_000_000
    # TV has nothing written down, and says so rather than claiming no change.
    tv = next(lib for lib in r["libraries"] if lib["name"] == "TV")
    assert tv["change_week"] is None
    assert r["recorded_days"] == 2


def test_the_scan_writes_one_row_a_day_and_the_last_one_wins(client):
    from app.db import session_scope
    from app.models import LibrarySize
    from app.services.library_scan import _record_sizes

    claim(client)
    seed()
    _record_sizes(datetime.now())
    with session_scope() as db:
        rows = db.query(LibrarySize).all()
        assert {r.section_id: r.bytes for r in rows} == {1: 10_000_000_000, 2: 1_000_000_000}
        assert len(rows) == 2

    # A second scan the same day replaces rather than adds.
    with session_scope() as db:
        from app.models import MediaItem

        db.add(MediaItem(rating_key=5, title="E", media_type="movie", section_id=1, file_size=5_000_000_000))
    _record_sizes(datetime.now())
    with session_scope() as db:
        rows = db.query(LibrarySize).all()
        assert len(rows) == 2
        assert {r.section_id: r.bytes for r in rows}[1] == 15_000_000_000


def test_free_space_is_per_disk_and_says_who_shares_it(client, tmp_path):
    """Two stores on one share have one answer between them, not two."""
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import mediafix, space

    claim(client)
    seed()
    # A real directory holding both, mounted as a media root.
    for name in ("movies", "tv"):
        folder = tmp_path / name / "A"
        folder.mkdir(parents=True)
        (folder / "a.mkv").write_bytes(b"x")
    with session_scope() as db:
        for key, path in ((1, "/movies/A/a.mkv"), (3, "/tv/A/a.mkv")):
            db.query(MediaItem).filter(MediaItem.rating_key == key).update({"file_path": path})
    assert client.put("/api/settings", json={"media_roots": str(tmp_path)}).status_code == 200
    mediafix._memory()
    space.forget_mounts()

    rows = space.disks({"Movies": ["/movies/A/a.mkv"], "TV": ["/tv/A/a.mkv"]})
    assert set(rows) == {"Movies", "TV"}
    # One disk, so one answer, and each is told who it shares with rather than
    # the page showing the same free space twice.
    assert rows["Movies"]["free"] == rows["TV"]["free"]
    assert rows["Movies"]["shared_with"] == ["TV"] and rows["TV"]["shared_with"] == ["Movies"]
    assert rows["Movies"]["used"] == rows["Movies"]["total"] - rows["Movies"]["free"]

    # And the Storage page carries it, since that is the page about mounts.
    stores = client.get("/api/library/stores").json()["stores"]
    assert any(s["free"] for s in stores)


def test_unmounted_media_is_not_an_error(client):
    """Running without the media mounted is a normal way to run this app."""
    from app.services import space

    claim(client)
    seed()
    space.forget_mounts()
    r = client.get("/api/library/space").json()
    assert r["total"] == 11_000_000_000
    assert "mounts" not in r
    # Storage still answers, with nothing to say about room left.
    stores = client.get("/api/library/stores").json()["stores"]
    assert stores and all(s["free"] is None for s in stores)


def test_space_is_admin_only(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "all")
    assert client.get("/api/library/space").status_code == 403

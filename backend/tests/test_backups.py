"""A copy of the database, taken while it is in use.

Everything the app works out lives in one file and nowhere else, so these are
about the two ways a backup can be worthless: one that cannot be opened, and
one that was never taken.

A plain file copy would be the first kind. SQLite runs here in WAL mode, so the
newest writes live in a sidecar and a copy can catch the pair mid-transaction.
`VACUUM INTO` is the supported way, and the test that matters is that the
result opens and has the rows in it.
"""

import sqlite3

from app.db import session_scope
from app.models import MediaItem
from app.services import backups
from app.settings_store import trial


def a_film(db, rating_key: int):
    db.add(MediaItem(rating_key=rating_key, title=f"Film {rating_key}", media_type="movie"))


def test_a_snapshot_opens_and_has_the_rows_in_it(client):
    with session_scope() as db:
        a_film(db, 1)
        a_film(db, 2)

    with trial({"backup_keep": 7}):
        out = backups.take()

    copy = backups.folder() / out["file"]
    assert copy.exists() and out["bytes"] > 0

    # Opened as a plain SQLite file, with nothing of the app's involved.
    con = sqlite3.connect(copy)
    try:
        assert con.execute("select count(*) from media_items").fetchone()[0] == 2
        assert con.execute("pragma integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()


def test_writing_carries_on_afterwards(client):
    """The snapshot must not leave a lock behind."""
    with session_scope() as db:
        a_film(db, 1)

    with trial({"backup_keep": 7}):
        backups.take()

    with session_scope() as db:
        a_film(db, 2)
    with session_scope() as db:
        assert db.get(MediaItem, 2) is not None


def test_only_the_last_few_are_kept(client):
    with trial({"backup_keep": 3}):
        for n in range(5):
            # The name carries the second it was taken, so they are nudged
            # apart rather than waiting five seconds.
            backups.take()
            _age(backups, n)

    assert len(backups.existing()) <= 3


def _age(mod, n: int) -> None:
    """Rename the newest snapshot so the next one does not collide."""
    newest = mod.existing()[-1] if mod.existing() else None
    if newest is not None:
        newest.rename(newest.with_name(f"cartographarr-2026010{n}-000000.db"))


def test_switched_off_takes_nothing(client):
    with trial({"backup_keep": 0}):
        assert backups.take() == {"status": "off"}
    assert backups.existing() == []


def test_the_folder_is_made_if_it_is_not_there(client):
    assert not backups.folder().exists()
    with trial({"backup_keep": 2}):
        backups.take()
    assert backups.folder().is_dir()


def test_something_that_is_not_a_snapshot_is_left_alone(client):
    """The pruning only ever touches files it recognises."""
    with trial({"backup_keep": 1}):
        backups.take()
        stray = backups.folder() / "notes.txt"
        stray.write_text("keep me")
        _age(backups, 1)
        backups.take()

    assert stray.exists()
    assert all(f.suffix == ".db" for f in backups.existing())


# ---- the clock everything time-based reads ----------------------------------


def test_the_server_says_what_time_it_thinks_it_is(client):
    """Nothing showed this, so a wrong TZ shifted every time-of-day rule and
    the backup hour silently and for ever."""
    from tests.test_auth import claim

    claim(client)
    answer = client.get("/api/server-time").json()
    assert 0 <= answer["hour"] <= 23
    assert answer["now"].startswith("20")
    assert answer["zone"]


def test_the_clock_is_admin_only(client):
    assert client.get("/api/server-time").status_code in (401, 403)

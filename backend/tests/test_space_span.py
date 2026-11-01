from datetime import date, timedelta

from tests.test_auth import claim


def wrote(db, section_id, days_ago, files, size):
    from app.models import LibrarySize

    db.add(LibrarySize(
        section_id=section_id, on_day=(date.today() - timedelta(days=days_ago)).isoformat(),
        files=files, bytes=size,
    ))


def seed(db):
    from app.models import Library, MediaItem

    db.add(Library(section_id=1, name="Movies", type="movie"))
    for key in range(1, 4):
        db.add(MediaItem(rating_key=key, section_id=1, media_type="movie", title=f"Film {key}",
                         full_title=f"Film {key}", file_size=1_000_000_000, file_path=f"/films/{key}.mkv"))


def report():
    from app.db import session_scope
    from app.services import space

    with session_scope() as db:
        return space.report(db)


def test_a_few_days_of_history_is_used_rather_than_withheld(client):
    from app.db import session_scope

    claim(client)
    with session_scope() as db:
        seed(db)
        wrote(db, 1, 3, files=1, size=1_000_000_000)
    row = report()["libraries"][0]
    assert row["change_week"] == 2_000_000_000
    assert row["files_week"] == 2
    assert row["week_days"] == 3, "and it says how long that covers"


def test_a_full_week_is_compared_against_the_week(client):
    """The fallback must not elbow out the real answer: with both, the one a week old wins."""
    from app.db import session_scope

    claim(client)
    with session_scope() as db:
        seed(db)
        wrote(db, 1, 30, files=0, size=0)
        wrote(db, 1, 8, files=2, size=2_000_000_000)
        wrote(db, 1, 1, files=3, size=3_000_000_000)
    row = report()["libraries"][0]
    assert row["change_week"] == 1_000_000_000 and row["week_days"] == 8


def test_nothing_written_down_is_still_nothing(client):
    from app.db import session_scope

    claim(client)
    with session_scope() as db:
        seed(db)
    row = report()["libraries"][0]
    assert row["change_week"] is None and row["week_days"] is None


def test_today_against_today_says_nothing(client):
    from app.db import session_scope

    claim(client)
    with session_scope() as db:
        seed(db)
        wrote(db, 1, 0, files=3, size=3_000_000_000)
    row = report()["libraries"][0]
    assert row["change_week"] is None

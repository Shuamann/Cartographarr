"""Grouping by what a title is, not only by what its file is.

Genre, director, writer, collection and country are lists, so they live in
their own table and are reached by a join. The whole point is grouping by one
of them: a column holding "Animation, Anime, Fantasy" answers nothing.

A title in three genres becomes three rows under the join, so it counts in all
three. That is right for counting plays and wrong for counting bytes, which is
why the dimension says so rather than leaving somebody to find out.
"""

from tests.test_auth import claim


def seed():
    from app.db import session_scope
    from app.models import History, MediaItem, MediaTag

    with session_scope() as db:
        db.add(MediaItem(rating_key=1, title="A", full_title="A", media_type="movie",
                         file_size=1_000, studio="Big Studio", section_id=1))
        db.add(MediaItem(rating_key=2, title="B", full_title="B", media_type="movie",
                         file_size=2_000, studio="Small Studio", section_id=1))
        for key, kind, value in [
            (1, "genre", "Animation"), (1, "genre", "Fantasy"), (1, "director", "Someone"),
            (2, "genre", "Animation"), (2, "director", "Another"), (2, "collection", "A Set"),
        ]:
            db.add(MediaTag(rating_key=key, kind=kind, value=value))
        # Two plays of the first title, one of the second.
        for row_id, key in ((1, 1), (2, 1), (3, 2)):
            db.add(History(row_id=row_id, user_id=1, rating_key=key, started=1000 * row_id,
                           stopped=1000 * row_id + 600, full_title="x", media_type="movie"))


def test_a_title_counts_in_every_genre_it_is_in(client):
    claim(client)
    seed()
    r = client.get("/api/reports/run?source=library&measure=items&group=genre").json()
    rows = {row["label"]: row["value"] for row in r["rows"]}
    assert rows == {"Animation": 2, "Fantasy": 1}


def test_grouping_by_director_uses_the_director_rows_and_not_the_genre_ones(client):
    """One join, for the one kind being grouped by. Without the kind on the
    join every tag of every sort would come back as a row."""
    claim(client)
    seed()
    r = client.get("/api/reports/run?source=library&measure=items&group=director").json()
    assert {row["label"] for row in r["rows"]} == {"Someone", "Another"}


def test_a_single_valued_one_needs_no_join_at_all(client):
    claim(client)
    seed()
    r = client.get("/api/reports/run?source=library&measure=items&group=studio").json()
    rows = {row["label"]: row["value"] for row in r["rows"]}
    assert rows == {"Big Studio": 1, "Small Studio": 1}


def test_a_genre_can_be_split_by_something_else(client):
    """The split is the whole reason the reports engine is worth joining to
    rather than putting this on a page of its own."""
    claim(client)
    seed()
    r = client.get("/api/reports/run?source=library&measure=items&group=genre&then=studio").json()
    rows = {row["label"]: row["cells"] for row in r["rows"]}
    assert rows["Animation"] == {"Big Studio": 1, "Small Studio": 1}
    assert rows["Fantasy"] == {"Big Studio": 1}


def test_two_tag_groupings_at_once_are_refused_rather_than_crossed(client):
    """Genre against director is two joins to the same table and a cross
    product nobody asked for."""
    claim(client)
    seed()
    r = client.get("/api/reports/run?source=library&measure=items&group=genre&then=director").json()
    assert r["ignored"], "it says it could not do one of them"


def test_the_dimension_warns_that_bytes_are_counted_more_than_once(client):
    """Counting plays by genre is right. Counting size by genre adds a film
    into each of its genres, and somebody reading a total needs telling."""
    from app.services.reports import DIMENSION

    assert "counting bytes" in (DIMENSION["genre"].hint or "")

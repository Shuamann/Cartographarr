from __future__ import annotations

from app.db import session_scope
from app.services import conditions as c


def cond(op, value):
    return {"type": "condition", "field": "collection", "op": op, "value": value}


def group(op, *items, negate=False):
    return {"type": "group", "op": op, "negate": negate, "items": list(items)}


def film(db, rating_key, title="A Film"):
    from app.models import MediaItem

    db.add(MediaItem(rating_key=rating_key, media_type="movie", title=title, full_title=title, section_id=1))


def episode(db, rating_key, show, season, title="An Episode"):
    from app.models import MediaItem

    db.add(MediaItem(
        rating_key=rating_key, media_type="episode", title=title, full_title=title, section_id=2,
        parent_rating_key=season, grandparent_rating_key=show,
    ))


def collect(db, name, *keys):
    from app.models import MediaTag

    for key in keys:
        db.add(MediaTag(rating_key=key, kind="collection", value=name))


def test_a_film_in_the_collection_matches(client):
    with session_scope() as db:
        film(db, 1, "Toy Story")
        collect(db, "Kids", 1)
    session = {"rating_key": 1}
    assert c.evaluate(group("and", cond("any", ["Kids"])), session, {}) is True
    assert c.evaluate(group("and", cond("any", ["4K Demos"])), session, {}) is False


def test_an_episode_is_matched_through_its_show(client):
    """Plex never files a collection against an episode."""
    with session_scope() as db:
        episode(db, 11, show=10, season=100)
        collect(db, "Saturday Mornings", 10)
    session = {"rating_key": 11, "parent_rating_key": 100, "grandparent_rating_key": 10}
    assert c.evaluate(group("and", cond("any", ["Saturday Mornings"])), session, {}) is True


def test_an_episode_is_matched_through_its_season_too(client):
    """The rarer case, where Plex has filed the collection against a season rather than the show."""
    with session_scope() as db:
        episode(db, 11, show=10, season=100)
        collect(db, "Just That Season", 100)
    session = {"rating_key": 11, "parent_rating_key": 100, "grandparent_rating_key": 10}
    assert c.evaluate(group("and", cond("any", ["Just That Season"])), session, {}) is True


def test_an_item_in_no_collection_is_not_in_the_one_named(client):
    with session_scope() as db:
        film(db, 1, "Unfiled")
    session = {"rating_key": 1}
    assert c.evaluate(group("and", cond("none", ["Kids"])), session, {}) is True
    assert c.evaluate(group("and", cond("any", ["Kids"])), session, {}) is False


def test_an_item_in_another_collection_is_not_in_this_one(client):
    with session_scope() as db:
        film(db, 1, "Casino Royale")
        collect(db, "James Bond Collection", 1)
    session = {"rating_key": 1}
    assert c.evaluate(group("and", cond("none", ["Kids"])), session, {}) is True
    assert c.evaluate(group("and", cond("none", ["James Bond Collection"])), session, {}) is False


def test_an_item_with_no_key_at_all_matches_neither_way(client):
    assert c.evaluate(group("and", cond("none", ["Kids"])), {}, {}) is False
    assert c.evaluate(group("and", cond("any", ["Kids"])), {}, {}) is False


def test_a_key_the_library_does_not_know_matches_neither_way(client):
    with session_scope() as db:
        film(db, 1, "Filed")
        collect(db, "Kids", 1)
    assert c.evaluate(group("and", cond("none", ["Kids"])), {"rating_key": 999}, {}) is True


def test_the_key_can_arrive_as_a_string(client):
    with session_scope() as db:
        film(db, 1, "Toy Story")
        collect(db, "Kids", 1)
    assert c.evaluate(group("and", cond("any", ["Kids"])), {"rating_key": "1"}, {}) is True


def test_the_name_is_matched_ignoring_case_and_spare_spaces(client):
    with session_scope() as db:
        film(db, 1)
        collect(db, "James Bond Collection", 1)
    assert c.evaluate(group("and", cond("any", ["  james bond COLLECTION "])), {"rating_key": 1}, {}) is True


def test_several_collections_in_one_condition(client):
    """"Is in any of these" is what saves listing the titles."""
    with session_scope() as db:
        film(db, 1, "Toy Story")
        film(db, 2, "Casino Royale")
        collect(db, "Kids", 1)
        collect(db, "James Bond Collection", 2)
    tree = group("and", cond("any", ["Kids", "James Bond Collection"]))
    assert c.evaluate(tree, {"rating_key": 1}, {}) is True
    assert c.evaluate(tree, {"rating_key": 2}, {}) is True
    assert c.evaluate(tree, {"rating_key": 3}, {}) is False


def test_a_condition_naming_nothing_is_refused_when_saved(client):
    import pytest

    with pytest.raises(ValueError, match="Collection"):
        c.validate(group("and", cond("any", [])))


def test_it_survives_a_round_trip_through_validate(client):
    saved = c.validate(group("and", cond("any", ["Kids"])))
    assert saved["items"][0] == {"type": "condition", "field": "collection", "op": "any", "value": ["Kids"]}


def test_a_file_rule_can_ask_it_too(client):
    allowed = {f.key for f in c.fields_for("file")}
    assert "collection" in allowed
    assert "collection" in {f.key for f in c.fields_for("stream")}


def test_a_file_subject_carries_the_keys_the_condition_needs(client):
    """The condition is only as good as what the sweep hands it."""
    import time

    from app.services import subjects

    with session_scope() as db:
        from app.models import History, MediaItem

        db.add(MediaItem(
            rating_key=11, media_type="episode", title="Pilot", full_title="Pilot", section_id=2,
            parent_rating_key=100, grandparent_rating_key=10, file_path="/tv/11.mkv",
            file_size=2_000_000_000, library_seen_at=None,
        ))
        db.add(History(row_id=1, reference_id=1, rating_key=11, started=int(time.time()) - 3600,
                       user_id=1, media_type="episode"))
        collect(db, "Saturday Mornings", 10)

    pool = subjects.files()
    assert pool, "the sweep found no files to ask about"
    assert c.evaluate(group("and", cond("any", ["Saturday Mornings"])), pool[0], {}) is True

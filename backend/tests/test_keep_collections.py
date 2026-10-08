"""Never suggest deleting anything in these collections.

The cleanup list works from how a file has been played, which is all it can
measure. A collection is the one place somebody has already written down what
they care about, and 510 of them sat in the database unread by anything except
a report grouping.

Keeping a file at a time already worked and does not scale: a box set of forty
films is forty clicks, and another one each time a film in it ages past the
threshold.
"""

from __future__ import annotations

import time

from app.db import session_scope
from app.services import cleanup

YEAR = 365 * 86400
BIG = 20_000_000_000


def film(key, title, added_years_ago=3):
    from app.models import MediaItem

    return MediaItem(
        rating_key=key, media_type="movie", title=title, full_title=title, section_id=1,
        file_path=f"/movies/{title}.mkv", file_size=BIG, duration=7_200_000,
        added_at=int(time.time()) - int(added_years_ago * YEAR),
    )


def episode(key, show, title, added_years_ago=3):
    from app.models import MediaItem

    return MediaItem(
        rating_key=key, media_type="episode", title=title, full_title=title, section_id=2,
        grandparent_rating_key=show, parent_media_index=1, media_index=key,
        file_path=f"/tv/{title}.mkv", file_size=BIG, duration=2_700_000,
        added_at=int(time.time()) - int(added_years_ago * YEAR),
    )


def tag(key, name):
    from app.models import MediaTag

    return MediaTag(rating_key=key, kind="collection", value=name)


def put(rows):
    with session_scope() as db:
        for row in rows:
            db.add(row)


def keeping(names, monkeypatch):
    monkeypatch.setattr(cleanup, "kept_collections", lambda: [n.lower() for n in names])


def listed():
    return {row["rating_key"] for row in cleanup.candidates()["items"]}


def test_a_film_in_a_kept_collection_is_not_suggested(client, monkeypatch):
    put([film(1, "One"), film(2, "Two"), tag(1, "Keep Forever")])
    keeping(["Keep Forever"], monkeypatch)
    assert listed() == {2}


def test_how_many_were_left_alone_is_said(client, monkeypatch):
    """Counted rather than silently dropped. A list that quietly shrinks is a
    list nobody can reason about, which is the rule the other two exclusions
    already follow."""
    put([film(1, "One"), film(2, "Two"), tag(1, "Keep Forever"), tag(2, "Keep Forever")])
    keeping(["Keep Forever"], monkeypatch)
    assert cleanup.candidates()["in_collection"] == 2


def test_an_episode_is_covered_through_its_show(client, monkeypatch):
    """Plex files a collection against a film or a show, never an episode, so
    matching on the item's own key alone protects nothing on television."""
    put([episode(11, 100, "A"), episode(12, 100, "B"), episode(21, 200, "C"), tag(100, "Keep Forever")])
    keeping(["Keep Forever"], monkeypatch)
    assert listed() == {21}


def test_the_name_is_matched_whatever_the_case(client, monkeypatch):
    """Somebody typing it into a settings box will not match Plex's
    capitalisation, and a setting that silently protects nothing is the worst
    way for this to fail."""
    put([film(1, "One"), tag(1, "Keep Forever")])
    keeping(["keep forever"], monkeypatch)
    assert listed() == set()


def test_another_collection_is_not_protected(client, monkeypatch):
    put([film(1, "One"), film(2, "Two"), tag(1, "Keep Forever"), tag(2, "Watch Later")])
    keeping(["Keep Forever"], monkeypatch)
    assert listed() == {2}


def test_nothing_set_protects_nothing(client, monkeypatch):
    put([film(1, "One"), tag(1, "Keep Forever")])
    keeping([], monkeypatch)
    assert listed() == {1}
    assert cleanup.candidates()["in_collection"] == 0


def test_a_tag_of_another_kind_is_not_a_collection(client, monkeypatch):
    """Genres, directors and writers live in the same table, 97,000 of them.
    Matching on the value alone would protect every film by a director who
    shares a name with a collection."""
    from app.models import MediaTag

    put([film(1, "One"), MediaTag(rating_key=1, kind="genre", value="Keep Forever")])
    keeping(["Keep Forever"], monkeypatch)
    assert listed() == {1}


def test_the_settings_line_is_read_however_it_is_written(client, monkeypatch):
    from app import settings_store
    from types import SimpleNamespace

    monkeypatch.setattr(
        settings_store, "current",
        lambda: SimpleNamespace(keep_collections="Keep Forever\nWatch Later, Christmas; Classics"),
    )
    assert cleanup.kept_collections() == ["keep forever", "watch later", "christmas", "classics"]


def test_an_empty_setting_is_no_collections_rather_than_one_blank(client, monkeypatch):
    """A blank name would match a collection whose name is empty, and worse,
    an `in ([])` of one empty string is a query that can match."""
    from app import settings_store
    from types import SimpleNamespace

    monkeypatch.setattr(settings_store, "current", lambda: SimpleNamespace(keep_collections="  \n , ; \n"))
    assert cleanup.kept_collections() == []

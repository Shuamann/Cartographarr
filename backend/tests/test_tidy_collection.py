from __future__ import annotations

import json

from app.db import session_scope
from tests.test_auth import claim

STYLED = [{"codec": "ass", "language": "eng", "location": "embedded"}]
SURROUND = [{"codec": "eac3", "channels": 6, "language": "eng"}]


def film(db, rating_key, title, subs=None):
    from app.models import MediaItem

    db.add(MediaItem(
        rating_key=rating_key, media_type="movie", title=title, full_title=title,
        file_path=f"/movies/{rating_key}.mkv", file_container="mkv", file_size=5_000_000_000,
        section_id=1, audio_tracks=json.dumps(SURROUND),
        subtitle_tracks=json.dumps(STYLED if subs is None else subs),
    ))


def episode(db, rating_key, show, season, title, subs=None):
    from app.models import MediaItem

    db.add(MediaItem(
        rating_key=rating_key, media_type="episode", title=title, full_title=title,
        parent_rating_key=season, grandparent_rating_key=show,
        file_path=f"/tv/{rating_key}.mkv", file_container="mkv", file_size=2_000_000_000,
        section_id=2, audio_tracks=json.dumps(SURROUND),
        subtitle_tracks=json.dumps(STYLED if subs is None else subs),
    ))


def collect(db, name, *keys):
    from app.models import MediaTag

    for key in keys:
        db.add(MediaTag(rating_key=key, kind="collection", value=name))


def ready(monkeypatch):
    """A container that can see its files."""
    from app.services import mediafix

    monkeypatch.setattr(mediafix, "tools", lambda: {"ready": True})
    monkeypatch.setattr(mediafix, "local_path", lambda path: path)


def test_a_collection_on_a_show_reaches_that_shows_episodes(client, monkeypatch):
    """Plex files a collection against the show, not against each episode."""
    claim(client)
    with session_scope() as db:
        episode(db, 11, show=10, season=100, title="Pilot")
        episode(db, 12, show=10, season=100, title="Second")
        collect(db, "Saturday Mornings", 10)
    ready(monkeypatch)

    answer = client.post("/api/library/tidy/many",
                         json={"collection": "Saturday Mornings", "dry_run": True}).json()
    assert answer["queued"] == 2, answer
    assert {f["rating_key"] for f in answer["files"]} == {11, 12}


def test_a_seasons_own_tag_also_reaches_its_episodes(client, monkeypatch):
    claim(client)
    with session_scope() as db:
        episode(db, 11, show=10, season=100, title="Pilot")
        episode(db, 21, show=20, season=200, title="Elsewhere")
        collect(db, "One Season Only", 100)
    ready(monkeypatch)

    answer = client.post("/api/library/tidy/many",
                         json={"collection": "One Season Only", "dry_run": True}).json()
    assert {f["rating_key"] for f in answer["files"]} == {11}


def test_a_collection_over_the_cap_is_refused_by_name_rather_than_cut_down(client, monkeypatch):
    """The cap exists because this rewrites whole films."""
    from app.models import MediaJob
    from app.routers.library import MANY_CAP

    claim(client)
    with session_scope() as db:
        for key in range(1, MANY_CAP + 2):
            film(db, key, f"Film {key:04d}")
        collect(db, "Everything", *range(1, MANY_CAP + 2))
    ready(monkeypatch)

    answer = client.post("/api/library/tidy/many", json={"collection": "Everything", "dry_run": True})
    assert answer.status_code == 400
    detail = answer.json()["detail"]
    assert "Everything" in detail and str(MANY_CAP) in detail and f"{MANY_CAP + 1:,}" in detail

    with session_scope() as db:
        assert db.query(MediaJob).count() == 0, "a refusal queued work anyway"


def test_a_collection_at_the_cap_is_still_done(client, monkeypatch):
    """The refusal is for more than the cap, not for the cap itself."""
    from app.routers.library import MANY_CAP

    claim(client)
    with session_scope() as db:
        for key in range(1, MANY_CAP + 1):
            film(db, key, f"Film {key:04d}")
        collect(db, "Exactly Enough", *range(1, MANY_CAP + 1))
    ready(monkeypatch)

    answer = client.post("/api/library/tidy/many", json={"collection": "Exactly Enough", "dry_run": True})
    assert answer.status_code == 200
    assert answer.json()["queued"] == MANY_CAP


def test_each_file_in_the_collection_still_gets_its_own_steps(client, monkeypatch):
    """What makes a collection a sensible thing to hand this at all."""
    claim(client)
    with session_scope() as db:
        film(db, 1, "Styled", STYLED)
        film(db, 2, "Repeated", [{"codec": "subrip", "language": "eng", "location": "embedded"}] * 4)
        collect(db, "Mixed Bag", 1, 2)
    ready(monkeypatch)

    answer = client.post("/api/library/tidy/many", json={"collection": "Mixed Bag", "dry_run": True}).json()
    steps = {f["title"]: f["steps"] for f in answer["files"]}
    assert "styled_subtitles" in steps["Styled"] and "subtitle_clutter" not in steps["Styled"]
    assert "subtitle_clutter" in steps["Repeated"] and "styled_subtitles" not in steps["Repeated"]


def test_the_dry_run_answers_first_and_totals_the_whole_lot(client, monkeypatch):
    from app.models import MediaJob

    claim(client)
    with session_scope() as db:
        film(db, 1, "One")
        film(db, 2, "Two")
        collect(db, "A Pair", 1, 2)
    ready(monkeypatch)

    answer = client.post("/api/library/tidy/many", json={"collection": "A Pair", "dry_run": True}).json()
    assert answer["queued"] == 2 and answer["dry_run"] is True
    assert answer["collection"] == "A Pair"
    assert "size_change" in answer and "size_unknown" in answer
    with session_scope() as db:
        assert db.query(MediaJob).count() == 0, "a dry run queued work"


def test_it_really_queues_one_job_each(client, monkeypatch):
    from app.models import MediaJob

    claim(client)
    with session_scope() as db:
        film(db, 1, "One")
        film(db, 2, "Two")
        collect(db, "A Pair", 1, 2)
    ready(monkeypatch)

    answer = client.post("/api/library/tidy/many", json={"collection": "A Pair"}).json()
    assert answer["queued"] == 2
    with session_scope() as db:
        assert {j.rating_key for j in db.query(MediaJob).all()} == {1, 2}


def test_a_name_nobody_has_is_said_so(client, monkeypatch):
    """Rather than answering zero files, which reads as a collection that happens to be tidy."""
    claim(client)
    ready(monkeypatch)

    answer = client.post("/api/library/tidy/many", json={"collection": "Not A Collection"})
    assert answer.status_code == 404
    assert "Not A Collection" in answer.json()["detail"]


def test_the_name_is_matched_ignoring_case(client, monkeypatch):
    claim(client)
    with session_scope() as db:
        film(db, 1, "One")
        collect(db, "James Bond Collection", 1)
    ready(monkeypatch)

    answer = client.post("/api/library/tidy/many",
                         json={"collection": "james bond collection", "dry_run": True}).json()
    assert answer["queued"] == 1


def test_naming_a_collection_wins_over_the_list_kind(client, monkeypatch):
    """`kind` has a default, so an unasked question cannot be told from a deliberate one."""
    from app.services import cleanup

    claim(client)
    with session_scope() as db:
        film(db, 1, "In the collection")
        film(db, 2, "On the list")
        collect(db, "Just This One", 1)
    ready(monkeypatch)
    monkeypatch.setattr(cleanup, "attention", lambda *a, **k: {"items": [{"rating_key": 2, "title": "On the list"}]})

    answer = client.post("/api/library/tidy/many",
                         json={"collection": "Just This One", "kind": "messy", "dry_run": True}).json()
    assert [f["rating_key"] for f in answer["files"]] == [1]

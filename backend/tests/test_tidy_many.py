import json

from tests.test_auth import claim


def a_file(db, rating_key, subs, title="A Film"):
    from app.models import MediaItem

    db.add(MediaItem(
        rating_key=rating_key, media_type="movie", title=title, full_title=title,
        file_path=f"/media/{rating_key}.mkv", file_container="mkv", file_size=5_000_000_000,
        section_id=1, audio_tracks=json.dumps([{"codec": "eac3", "channels": 6, "language": "eng"}]),
        subtitle_tracks=json.dumps(subs),
    ))


def ready(monkeypatch, rows):
    """A container that can see its files, and a list that holds these."""
    from app.services import cleanup, mediafix

    monkeypatch.setattr(mediafix, "tools", lambda: {"ready": True})
    monkeypatch.setattr(mediafix, "local_path", lambda path: path)
    monkeypatch.setattr(cleanup, "attention", lambda kind, days, threshold, limit=200: {"items": rows})


def test_a_dry_run_queues_nothing_and_says_what_it_would_do(client, monkeypatch):
    from app.db import session_scope
    from app.models import MediaJob

    claim(client)
    with session_scope() as db:
        a_file(db, 1, [{"codec": "ass", "language": "eng", "location": "embedded"}], "Styled")
    ready(monkeypatch, [{"rating_key": 1, "title": "Styled"}])

    answer = client.post("/api/library/tidy/many", json={"kind": "messy", "dry_run": True}).json()
    assert answer["queued"] == 1 and answer["dry_run"] is True
    assert "styled_subtitles" in answer["files"][0]["steps"]
    with session_scope() as db:
        assert db.query(MediaJob).count() == 0, "nothing was queued"


def test_each_file_gets_its_own_steps(client, monkeypatch):
    from app.db import session_scope

    claim(client)
    with session_scope() as db:
        a_file(db, 1, [{"codec": "ass", "language": "eng", "location": "embedded"}], "Styled")
        a_file(db, 2, [{"codec": "subrip", "language": "eng", "location": "embedded"}] * 4, "Repeated")
    ready(monkeypatch, [{"rating_key": 1, "title": "Styled"}, {"rating_key": 2, "title": "Repeated"}])

    answer = client.post("/api/library/tidy/many", json={"kind": "messy", "dry_run": True}).json()
    steps = {f["title"]: f["steps"] for f in answer["files"]}
    assert "styled_subtitles" in steps["Styled"] and "subtitle_clutter" not in steps["Styled"]
    assert "subtitle_clutter" in steps["Repeated"] and "styled_subtitles" not in steps["Repeated"]


def test_a_file_with_nothing_worth_doing_is_named_rather_than_counted_in(client, monkeypatch):
    from app.db import session_scope

    claim(client)
    with session_scope() as db:
        # Already has an AAC stereo track beside the surround, so even the
        # add-a-track steps have nothing to offer.
        from app.models import MediaItem

        db.add(MediaItem(
            rating_key=1, media_type="movie", title="Already tidy", full_title="Already tidy",
            file_path="/media/1.mkv", file_container="mkv", file_size=5_000_000_000, section_id=1,
            audio_tracks=json.dumps([
                {"codec": "eac3", "channels": 6, "language": "eng"},
                {"codec": "aac", "channels": 2, "language": "eng"},
            ]),
            subtitle_tracks=json.dumps([{"codec": "subrip", "language": "eng", "location": "embedded"}]),
        ))
    ready(monkeypatch, [{"rating_key": 1, "title": "Already tidy"}])

    answer = client.post("/api/library/tidy/many", json={"kind": "messy", "dry_run": True}).json()
    assert answer["queued"] == 0 and answer["skipped"] == 1
    assert answer["not_done"][0]["why"] == "nothing to do to it"


def test_one_job_each_rather_than_one_job_for_the_lot(client, monkeypatch):
    from app.db import session_scope
    from app.models import MediaJob

    claim(client)
    with session_scope() as db:
        a_file(db, 1, [{"codec": "ass", "language": "eng", "location": "embedded"}], "One")
        a_file(db, 2, [{"codec": "ass", "language": "eng", "location": "embedded"}], "Two")
    ready(monkeypatch, [{"rating_key": 1, "title": "One"}, {"rating_key": 2, "title": "Two"}])

    answer = client.post("/api/library/tidy/many", json={"kind": "messy"}).json()
    assert answer["queued"] == 2
    with session_scope() as db:
        jobs = db.query(MediaJob).all()
        assert len(jobs) == 2
        assert {j.rating_key for j in jobs} == {1, 2}


def test_a_file_the_container_cannot_reach_is_reported_and_the_rest_carry_on(client, monkeypatch):
    from app.db import session_scope
    from app.services import cleanup, mediafix

    claim(client)
    with session_scope() as db:
        a_file(db, 1, [{"codec": "ass", "language": "eng", "location": "embedded"}], "Reachable")
        a_file(db, 2, [{"codec": "ass", "language": "eng", "location": "embedded"}], "Elsewhere")
    monkeypatch.setattr(mediafix, "tools", lambda: {"ready": True})
    monkeypatch.setattr(mediafix, "local_path", lambda path: path if path.endswith("1.mkv") else None)
    monkeypatch.setattr(cleanup, "attention", lambda *a, **k: {
        "items": [{"rating_key": 1, "title": "Reachable"}, {"rating_key": 2, "title": "Elsewhere"}]
    })

    answer = client.post("/api/library/tidy/many", json={"kind": "messy"}).json()
    assert answer["queued"] == 1 and answer["skipped"] == 1
    assert "cannot see" in answer["not_done"][0]["why"]


def test_only_the_lists_this_makes_sense_for(client):
    claim(client)
    assert client.post("/api/library/tidy/many", json={"kind": "room"}).status_code == 400


def test_it_is_capped(client, monkeypatch):
    """This rewrites whole films."""
    from app.services import cleanup, mediafix

    claim(client)
    asked = {}
    monkeypatch.setattr(mediafix, "tools", lambda: {"ready": True})

    def listing(kind, days, threshold, limit=200):
        asked["limit"] = limit
        return {"items": []}

    monkeypatch.setattr(cleanup, "attention", listing)
    client.post("/api/library/tidy/many", json={"kind": "messy", "limit": 9999, "dry_run": True})
    assert asked["limit"] == 200

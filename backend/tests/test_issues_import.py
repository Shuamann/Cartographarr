import asyncio

from tests.test_auth import claim
from tests.test_issues import fake_seerr, issue, seed_library


def names(monkeypatch, known=None):
    """What Seerr would call a film or show, by TMDB id."""
    from app.services import issues as service

    asked = []

    async def media_name(media):
        asked.append(media.get("tmdbId"))
        return (known or {}).get(media.get("tmdbId"))

    monkeypatch.setattr(service, "media_name", media_name)
    return asked


def film(seerr_id, rating_key=None, tmdb=None, imdb=None, message="Wrong audio"):
    raw = issue(seerr_id, kind=2, rating_key=rating_key, media_type="movie", season=0, episode=0, message=message)
    raw["media"] = {"mediaType": "movie", "tmdbId": tmdb, "imdbId": imdb,
                    **({"ratingKey": str(rating_key)} if rating_key else {})}
    return raw


def stored(seerr_id):
    from app.db import session_scope
    from app.models import Issue

    with session_scope() as db:
        found = db.query(Issue).filter(Issue.seerr_id == seerr_id).one()
        db.expunge(found)
        return found


def test_the_answer_says_what_was_new_and_what_was_already_here(client, monkeypatch):
    from app.services import issues as service

    claim(client)
    seed_library()
    names(monkeypatch)
    fake_seerr(monkeypatch, [issue(11)])
    asyncio.run(service.sync())

    fake_seerr(monkeypatch, [issue(11), issue(12, message="Picture freezes")])
    result = asyncio.run(service.import_all())
    assert (result["read"], result["new"], result["already_here"], result["unmatched"]) == (2, 1, 1, 0)
    assert result["matched_by"] == {"rating_key": 2}

    # Running it again brings nothing in twice: Seerr's own id says it is here.
    again = asyncio.run(service.import_all())
    assert (again["new"], again["already_here"]) == (0, 2)
    assert len(client.get("/api/issues?status=all").json()["items"]) == 2


def test_a_film_plex_renumbered_is_found_by_its_ids(client, monkeypatch):
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import issues as service

    claim(client)
    names(monkeypatch)
    with session_scope() as db:
        db.add(MediaItem(rating_key=40, title="Annabelle", full_title="Annabelle", media_type="movie", tmdb_id="250546"))
        db.add(MediaItem(rating_key=41, title="Paul", full_title="Paul", media_type="movie", imdb_id="tt1092026"))
    fake_seerr(monkeypatch, [film(20, rating_key=9999, tmdb=250546), film(21, rating_key=9998, imdb="tt1092026")])
    result = asyncio.run(service.import_all())
    assert result["matched_by"] == {"tmdb": 1, "imdb": 1} and result["unmatched"] == 0
    assert (stored(20).rating_key, stored(20).title) == (40, "Annabelle")
    assert stored(21).rating_key == 41


def test_a_show_is_found_by_its_own_id_and_then_by_its_name(client, monkeypatch):
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import issues as service

    claim(client)
    seed_library()  # The Office (US) S08E23 under show 500
    with session_scope() as db:
        db.add(MediaItem(rating_key=600, title="Severance", media_type="show", tvdb_id="371980"))
        db.add(MediaItem(rating_key=601, title="Good News", full_title="Severance - Good News", media_type="episode",
                         grandparent_rating_key=600, grandparent_title="Severance", parent_media_index=1, media_index=1))
    names(monkeypatch, {2316: "The Office (US)"})
    by_id = issue(30, rating_key=7777, season=1, episode=1)
    by_id["media"] = {"mediaType": "tv", "tmdbId": 95396, "tvdbId": 371980, "ratingKey": "7777"}
    by_name = issue(31, rating_key=8888)  # S08E23, show renumbered, no show row
    by_name["media"]["ratingKey"] = "8888"
    fake_seerr(monkeypatch, [by_id, by_name])

    result = asyncio.run(service.import_all())
    assert result["matched_by"] == {"tvdb": 1, "title": 1}
    assert (stored(30).rating_key, stored(30).show_rating_key) == (601, 600)
    assert (stored(31).rating_key, stored(31).show_rating_key) == (880, 500)


def test_a_name_that_fits_two_shows_is_not_a_match(client, monkeypatch):
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import issues as service

    claim(client)
    with session_scope() as db:
        for key, show in ((700, 70), (701, 71)):
            db.add(MediaItem(rating_key=key, title="Pilot", full_title="Shogun - Pilot", media_type="episode",
                             grandparent_rating_key=show, grandparent_title="Shogun", parent_media_index=1, media_index=1))
    names(monkeypatch, {126308: "Shogun"})
    raw = issue(40, rating_key=None, season=1, episode=1)
    raw["media"] = {"mediaType": "tv", "tmdbId": 126308}
    fake_seerr(monkeypatch, [raw])
    result = asyncio.run(service.import_all())
    assert result["unmatched"] == 1 and stored(40).rating_key is None


def test_a_report_with_no_file_is_kept_and_named(client, monkeypatch):
    """Somebody telling you something is wrong."""
    from app.services import issues as service

    claim(client)
    names(monkeypatch, {603: "The Matrix"})
    fake_seerr(monkeypatch, [film(50, rating_key=5555, tmdb=603, message="Cam copy")])
    result = asyncio.run(service.import_all())
    assert (result["new"], result["unmatched"], result["unmatched_titles"]) == (1, 1, ["The Matrix"])
    kept = stored(50)
    assert kept.title == "The Matrix" and kept.message == "Cam copy" and kept.rating_key == 5555


def test_comments_come_across_with_who_said_them_and_when(client, monkeypatch):
    import json

    from app.services import issues as service

    claim(client)
    seed_library()
    names(monkeypatch)
    raw = issue(60)
    raw["comments"].append({"message": "Replaced it", "user": {"displayName": "Keeper", "plexId": 1},
                            "createdAt": "2026-09-17T09:30:00.000Z"})
    fake_seerr(monkeypatch, [raw])
    asyncio.run(service.import_all())
    notes = json.loads(stored(60).comments)
    assert [(n["author"], n["message"], n["created_at"][:16]) for n in notes] == [
        ("Watcher", "Audio is out of sync", "2026-09-16T10:00"),
        ("Keeper", "Replaced it", "2026-09-17T09:30"),
    ]


def test_seerr_answering_with_nothing_loses_nothing(client, monkeypatch):
    """A Seerr reinstalled at the same address answers with an empty list."""
    from app.services import issues as service

    claim(client)
    seed_library()
    names(monkeypatch)
    fake_seerr(monkeypatch, [issue(11), issue(12)])
    asyncio.run(service.sync())

    fake_seerr(monkeypatch, [])
    assert asyncio.run(service.sync())["no_longer_in_seerr"] == 2
    items = client.get("/api/issues?status=all").json()["items"]
    assert len(items) == 2 and all(i["seerr_gone"] for i in items)

    posted = []

    async def post(path, body=None):
        posted.append(path)

    monkeypatch.setattr(service, "_post", post)
    monkeypatch.setattr(type(service.seerr), "configured", lambda self: True)
    answer = client.post(f"/api/issues/{items[0]['id']}/comment", json={"message": "Still broken"}).json()
    assert posted == [] and "no longer has" in answer["warning"]

    # Seerr listing it again brings the mark off.
    fake_seerr(monkeypatch, [issue(11), issue(12)])
    asyncio.run(service.sync())
    assert not any(i["seerr_gone"] for i in client.get("/api/issues?status=all").json()["items"])


def test_every_report_is_read_not_the_first_five_hundred(client, monkeypatch):
    from app.services import issues as service

    claim(client)
    everything = [{"id": n} for n in range(1, 651)]

    async def get(path, params=None):
        start = params["skip"]
        return {"results": everything[start : start + params["take"]], "pageInfo": {"results": len(everything)}}

    monkeypatch.setattr(service, "_get", get)
    assert len(asyncio.run(service.fetch())) == 650


def test_the_button_answers_where_it_was_pressed(client, monkeypatch):
    from app.services import issues as service

    claim(client)
    seed_library()
    names(monkeypatch)
    assert client.post("/api/seerr/issues/import").json() == {
        "asked": False, "reason": "Seerr is not set up, so there is nothing to bring in"}

    monkeypatch.setattr(type(service.seerr), "configured", lambda self: True)
    fake_seerr(monkeypatch, [issue(11)])
    answer = client.post("/api/seerr/issues/import").json()
    assert answer["asked"] is True and answer["new"] == 1 and answer["read"] == 1


def test_only_an_admin_brings_reports_in(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "all")
    assert client.post("/api/seerr/issues/import").status_code == 403

from __future__ import annotations

import asyncio

import pytest

from app.services import moves

ARRAY = "/array/media/movies"
ARRAY_TOO = "/array/media/kidsmovies"
NAS = "/nas/media/movies"

SMALL = 4_000_000_000
ROOM = 300_000_000_000
LOTS = 60_000_000_000_000


class Service:
    """A stand in shaped like the real one, with nothing happening by default."""

    label = "Radarr"
    path = "movie"
    base_url = "http://radarr.invalid"
    headers: dict[str, str] = {}

    def __init__(self):
        self.roots = [
            {"id": 1, "path": ARRAY, "accessible": True, "freeSpace": ROOM},
            {"id": 2, "path": ARRAY_TOO, "accessible": True, "freeSpace": ROOM},
            {"id": 3, "path": NAS, "accessible": True, "freeSpace": LOTS},
        ]
        self.queue: list[dict] = []


def movie(**kw):
    return {"id": 7, "title": "A Film", "hasFile": True, "sizeOnDisk": SMALL,
            "rootFolderPath": ARRAY, "path": ARRAY + "/A Film (2019)", **kw}


@pytest.fixture
def service(monkeypatch):
    svc = Service()

    async def get_json(url, headers=None, params=None, **kw):
        if url.endswith("/rootfolder"):
            return svc.roots
        if url.endswith("/queue"):
            return {"records": svc.queue}
        return None

    monkeypatch.setattr("app.integrations.base.get_json", get_json)
    # Nothing playing and nothing being done to it, unless a test says so.
    monkeypatch.setattr(moves, "_busy_here", lambda key: [])

    async def nobody(key):
        return []

    monkeypatch.setattr(moves, "_being_watched", nobody)
    return svc


def plan(service, to=NAS, item=None, key=1):
    return asyncio.run(moves.plan(service, key, item or movie(), to))


def test_a_move_to_another_disk_is_allowed(service):
    answer = plan(service)
    assert answer["can_move"] is True
    assert answer["blockers"] == [] and answer["warnings"] == []
    assert answer["bytes"] == SMALL


def test_a_title_being_watched_is_not_moved(service, monkeypatch):
    """Moving the files out from under a stream breaks it."""
    async def watching(key):
        return ["it is being watched right now by somebody"]

    monkeypatch.setattr(moves, "_being_watched", watching)
    answer = plan(service)
    assert answer["can_move"] is False
    assert any("watched" in b for b in answer["blockers"])


def test_not_knowing_what_is_playing_stops_it_too(service, monkeypatch):
    async def cannot(key):
        return ["this app cannot see what is playing right now (no server)"]

    monkeypatch.setattr(moves, "_being_watched", cannot)
    assert plan(service)["can_move"] is False


def test_a_download_in_the_queue_stops_it(service):
    """Moving the folder while the service is importing into it is a race nobody wins."""
    service.queue = [{"movieId": 7, "status": "completed", "trackedDownloadState": "importBlocked"}]
    answer = plan(service)
    assert answer["can_move"] is False
    assert "Radarr has a download for it that it will not import by itself" in answer["blockers"]


def test_a_download_for_a_different_title_does_not_stop_it(service):
    """Keyed on the title's own id."""
    service.queue = [{"movieId": 999, "status": "downloading", "trackedDownloadState": "downloading"}]
    assert plan(service)["can_move"] is True


def test_the_queue_is_described_as_a_person_would(service):
    service.queue = [{"movieId": 7, "status": "completed", "trackedDownloadState": "downloading"}]
    assert "Radarr is downloading something for it" in plan(service)["blockers"]


def test_this_app_tidying_it_stops_it(service, monkeypatch):
    """Tidying rewrites the file where it stands."""
    monkeypatch.setattr(moves, "_busy_here", lambda key: ["this app is tidying it, which rewrites the file"])
    assert plan(service)["can_move"] is False


def test_a_title_with_no_file_has_nothing_to_move(service):
    answer = plan(service, item=movie(hasFile=False, sizeOnDisk=0))
    assert answer["can_move"] is False
    assert any("nothing to move" in b for b in answer["blockers"])


def test_moving_it_where_it_already_is_is_refused(service):
    assert plan(service, to=ARRAY)["can_move"] is False


def test_a_destination_the_service_cannot_reach_is_refused(service):
    service.roots[2]["accessible"] = False
    assert plan(service, to=NAS)["can_move"] is False


def test_a_destination_with_less_room_than_the_files_is_refused(service):
    answer = plan(service, item=movie(sizeOnDisk=ROOM * 2))
    assert plan(service, to=ARRAY_TOO, item=movie(sizeOnDisk=ROOM * 2))["can_move"] is False
    assert answer["can_move"] is True, "the big disk still has room for it"


def test_an_unknown_destination_is_refused(service):
    assert plan(service, to="/somewhere/else")["can_move"] is False


def test_moving_within_one_disk_warns_rather_than_refuses(service):
    answer = plan(service, to=ARRAY_TOO)
    assert answer["can_move"] is True
    assert any("one disk" in w for w in answer["warnings"])


def test_every_reason_is_given_at_once(service, monkeypatch):
    service.queue = [{"movieId": 7, "status": "completed", "trackedDownloadState": "importing"}]
    monkeypatch.setattr(moves, "_busy_here", lambda key: ["this app is tidying it"])
    assert len(plan(service, item=movie(hasFile=False))["blockers"]) >= 3


def test_the_move_checks_again_before_asking(service, monkeypatch):
    asked: list = []

    async def watching(key):
        return ["it is being watched right now by somebody"]

    monkeypatch.setattr(moves, "_being_watched", watching)
    monkeypatch.setattr(moves, "_tell_plex", lambda key, old: asked.append(("plex", old)))
    with pytest.raises(ValueError, match="watched"):
        asyncio.run(moves.move(service, 1, movie(), NAS))
    assert asked == [], "nothing should have been asked of anybody"


def test_a_show_measures_itself_where_the_service_keeps_it():
    """A film carries sizeOnDisk at the top; a series keeps it under statistics."""
    series = {"statistics": {"sizeOnDisk": 50_000_000_000, "episodeFileCount": 40}}
    assert moves.size_of(series) == 50_000_000_000
    assert moves.size_of({"sizeOnDisk": 4_000_000_000}) == 4_000_000_000
    assert moves.size_of({}) == 0


def test_a_show_says_it_has_files_the_way_a_series_does():
    assert moves.has_files({"statistics": {"episodeFileCount": 40}}) is True
    assert moves.has_files({"statistics": {"episodeFileCount": 0, "sizeOnDisk": 0}}) is False
    assert moves.has_files({"hasFile": True}) is True
    assert moves.has_files({"hasFile": False}) is False


def test_a_show_can_be_seen_to_land():
    landed = {"rootFolderPath": "/nas/tv", "path": "/nas/tv/A Show",
              "statistics": {"episodeFileCount": 40, "sizeOnDisk": 5}}
    assert moves.has_landed(landed, "/nas/tv") is True
    still_away = {**landed, "rootFolderPath": "/array/tv", "path": "/array/tv/A Show"}
    assert moves.has_landed(still_away, "/nas/tv") is False


def test_a_series_is_known_from_a_film():
    assert moves.is_a_show({"statistics": {"sizeOnDisk": 1}}) is True
    assert moves.is_a_show({"sizeOnDisk": 1, "movieFile": {"path": "/a"}}) is False


def test_the_new_folder_is_sent_and_not_only_the_new_root(service, monkeypatch):
    sent = {}

    class Reply:
        @staticmethod
        def raise_for_status():
            return None

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def put(self, url, headers=None, params=None, json=None):
            sent.update({"params": params, "body": json})
            return Reply()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: Client())
    monkeypatch.setattr(moves, "_tell_plex", lambda key, old: {"old": True, "new": True})
    asyncio.run(moves.move(service, 1, movie(path=ARRAY + "/A Film (2019)"), NAS))

    assert sent["params"] == {"moveFiles": "true"}
    assert sent["body"]["rootFolderPath"] == NAS
    assert sent["body"]["path"] == NAS + "/A Film (2019)", "the folder has to move with it"


def test_the_folder_name_is_kept(service, monkeypatch):
    """Only the disk changes."""
    sent = {}

    class Reply:
        @staticmethod
        def raise_for_status():
            return None

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def put(self, url, headers=None, params=None, json=None):
            sent.update({"body": json})
            return Reply()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: Client())
    monkeypatch.setattr(moves, "_tell_plex", lambda key, old: {})
    odd = movie(path=ARRAY + "/A Film (2019) [Remux-1080p]")
    asyncio.run(moves.move(service, 1, odd, NAS))
    assert sent["body"]["path"] == NAS + "/A Film (2019) [Remux-1080p]"


def test_plex_is_not_told_while_the_files_are_still_copying(service, monkeypatch):
    """A 22 GB copy takes minutes."""
    told = []

    class Reply:
        @staticmethod
        def raise_for_status():
            return None

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def put(self, url, headers=None, params=None, json=None):
            return Reply()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: Client())
    monkeypatch.setattr(moves, "settle", lambda key, old: told.append(key))
    monkeypatch.setattr(moves, "_tell_plex", lambda key, old: told.append(("early", key)))
    asyncio.run(moves.move(service, 1, movie(), NAS))
    assert told == [], "asking is not arriving"


def test_the_row_is_read_back_rather_than_guessed(client, monkeypatch):
    from app.db import session_scope
    from app.models import MediaItem

    from datetime import UTC, datetime

    with session_scope() as db:
        db.add(MediaItem(rating_key=1, media_type="movie", title="A Film",
                         file_path="/old/movies/A Film/A.mkv", file_size=1, section_id=1,
                         # Set, so clearing it is something a test can see.
                         file_checked_at=datetime.now(UTC)))

    monkeypatch.setattr("app.plex.library.details",
                        lambda keys: [{"rating_key": 1, "file_path": "/new/movies/A Film/A.mkv",
                                       "file_size": 99}])
    assert moves._reread(1, "/old/movies") is True
    with session_scope() as db:
        item = db.get(MediaItem, 1)
        assert item.file_path == "/new/movies/A Film/A.mkv"
        assert item.file_size == 99
        assert item.file_checked_at is None


def test_plex_still_saying_the_old_folder_is_not_an_answer(client, monkeypatch):
    """Its scan has not finished."""
    from app.db import session_scope
    from app.models import MediaItem

    with session_scope() as db:
        db.add(MediaItem(rating_key=1, media_type="movie", title="A Film",
                         file_path="/old/movies/A Film/A.mkv", file_size=1, section_id=1))
    monkeypatch.setattr("app.plex.library.details",
                        lambda keys: [{"rating_key": 1, "file_path": "/old/movies/A Film/A.mkv"}])
    assert moves._reread(1, "/old/movies") is False


def test_a_renumbered_item_stops_being_in_the_library(client, monkeypatch):
    from datetime import UTC, datetime

    from app.db import session_scope
    from app.models import MediaItem
    from app.services.library_scan import in_library
    from sqlalchemy import func, select

    from app.models import SyncState
    from app.services.library_scan import SCAN_KEY

    with session_scope() as db:
        # Before any scan every row counts as present, which is the right
        # answer for a fresh install and the wrong one for this test.
        db.add(SyncState(key=SCAN_KEY, value=datetime(2026, 1, 1).isoformat()))
        db.add(MediaItem(rating_key=1, media_type="movie", title="A Film",
                         file_path="/old/movies/A Film/A.mkv", file_size=1, section_id=1,
                         library_seen_at=datetime(2026, 6, 1), file_checked_at=datetime.now(UTC)))

    # Plex no longer has that number, which is what it does after a move.
    monkeypatch.setattr("app.plex.library.details", lambda keys: [{"rating_key": 1}])
    monkeypatch.setattr("app.plex.maintenance.section_of", lambda key: None)
    monkeypatch.setattr(moves, "SETTLE_SECONDS", 0)
    monkeypatch.setattr(moves, "TRIES_AFTER_LANDING", 2)

    out = moves.settle(1, "/old/movies")
    assert out["renumbered"] is True
    with session_scope() as db:
        still_here = db.execute(
            select(func.count()).select_from(MediaItem).where(MediaItem.rating_key == 1, in_library())
        ).scalar()
    assert still_here == 0, "the old number is not in the library any more"


def test_already_there_is_an_answer_and_not_a_delay(service):
    answer = plan(service, to=ARRAY)
    assert answer["can_move"] is False
    assert "it is already there" in answer["settled"]


def test_a_root_the_service_does_not_have_is_an_answer(service):
    answer = plan(service, to="/somewhere/else")
    assert answer["settled"], "no amount of waiting makes a root folder appear"


def test_a_destination_it_cannot_reach_is_an_answer(service):
    service.roots[2]["accessible"] = False
    assert plan(service, to=NAS)["settled"]


def test_nothing_to_move_is_an_answer(service):
    assert plan(service, item=movie(hasFile=False, sizeOnDisk=0))["settled"]


def test_somebody_watching_it_is_a_delay(service, monkeypatch):
    """It ends on its own, so the job keeps its place."""
    async def watching(key):
        return ["it is being watched right now by somebody"]

    monkeypatch.setattr(moves, "_being_watched", watching)
    answer = plan(service)
    assert answer["can_move"] is False
    assert answer["settled"] == [], "waiting is the right thing to do with this one"


def test_a_download_going_for_it_is_a_delay(service):
    service.queue = [{"movieId": 7, "status": "completed", "trackedDownloadState": "downloading"}]
    assert plan(service)["settled"] == []


def test_every_reason_is_still_listed_whichever_kind_it_is(service):
    """Somebody reading the row wants all of them, not the ones that happen to be delays."""
    answer = plan(service, to=ARRAY, item=movie(hasFile=False))
    assert len(answer["blockers"]) >= 2
    assert set(answer["settled"]) <= set(answer["blockers"])

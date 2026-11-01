from __future__ import annotations

from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from app.db import session_scope
from app.plex import rematch, server
from tests.test_auth import claim

# Two filmed productions of one play in one year, which is the case this
# exists for and the case where guessing picks the wrong one.
WINDSOR = {
    "guid": "plex://movie/windsor", "name": "Hamlet", "year": "2024", "type": "movie",
    "summary": "A filmed stage production at Theatre Royal Windsor.", "lifespanEnded": "0",
}
DELACORTE = {
    "guid": "plex://movie/delacorte", "name": "Hamlet", "year": "2024", "type": "movie",
    "summary": "Filmed at the Delacorte Theater for the Public Theater.", "lifespanEnded": "0",
}
# Measured: year and summary are absent from about a fifth of candidates.
BARE = {"guid": "plex://movie/bare", "name": "Hamlet", "type": "movie", "lifespanEnded": "0"}


def matches_xml(candidates):
    root = ET.Element("MediaContainer", {"size": str(len(candidates))})
    for row in candidates:
        ET.SubElement(root, "SearchResult", {k: v for k, v in row.items()})
    return root


class Item:
    """One Plex item, as much of it as this code touches."""

    def __init__(self, rating_key, guid, title=None, year=None, ids=(), kind="movie"):
        self.ratingKey = rating_key
        self.guid = guid
        self.title = title
        self.year = year
        self.thumb = f"/library/metadata/{rating_key}/thumb"
        self.type = kind
        self.guids = [SimpleNamespace(id=value) for value in ids]

    def section(self):
        return SimpleNamespace(agent="tv.plex.agents.movie")

    def matches(self):
        return [SimpleNamespace(**{k: v for k, v in row.items()}) for row in self.server.candidates]

    def fixMatch(self, searchResult=None, auto=False, agent=None):
        self.server.applied.append((self.ratingKey, searchResult.guid, searchResult.name))
        self.server.take(self)


class Plex:
    """A server that answers about one item and records what it was asked."""

    def __init__(self, item, candidates, after_ids=("imdb://tt1", "tmdb://2", "tvdb://3")):
        self.item = item
        item.server = self
        self.candidates = candidates
        self.after_ids = after_ids
        self.asked: list[str] = []
        self.applied: list[tuple[int, str, str]] = []
        self.fetched = 0

    def take(self, item):
        item.guid = self.applied[-1][1]
        item.title = self.applied[-1][2]
        item.guids = [SimpleNamespace(id=value) for value in self.after_ids]

    def fetchItem(self, key):
        self.fetched += 1
        if int(key) != int(self.item.ratingKey):
            raise AssertionError(f"asked Plex for {key}, which is not the item being matched")
        return self.item

    def query(self, path):
        self.asked.append(path)
        return matches_xml(self.candidates)


def a_film(key=1, guid="plex://movie/windsor", title="Hamlet", year=2024,
           ids=("imdb://tt9", "tmdb://111", "tvdb://222")):
    with session_scope() as db:
        from app.models import MediaItem

        db.add(MediaItem(
            rating_key=key, title=title, full_title=title, media_type="movie", section_id=1, year=year,
            file_path="/movies/Hamlet (2024)/Hamlet.mkv",
            imdb_id="tt9", tmdb_id="111", tvdb_id="222",
        ))
    return Item(key, guid, title, year, ids)


def install(monkeypatch, plex):
    monkeypatch.setattr(server, "server", lambda fresh=False: plex)
    return plex


# ---- reading the candidates -------------------------------------------------


def test_the_list_is_asked_for_manually_or_plex_answers_with_the_match_it_made(client, monkeypatch):
    item = a_film()
    plex = install(monkeypatch, Plex(item, [WINDSOR, DELACORTE, BARE]))
    answer = rematch.candidates(1)
    assert plex.asked == ["/library/metadata/1/matches?manual=1"]
    assert len(answer["candidates"]) == 3


def test_a_candidate_keeps_what_plex_said_and_a_missing_year_is_not_invented(client, monkeypatch):
    """The year arrives as a string and is absent from a fifth of them."""
    item = a_film()
    install(monkeypatch, Plex(item, [WINDSOR, BARE]))
    windsor, bare = rematch.candidates(1)["candidates"]
    assert windsor["year"] == 2024 and isinstance(windsor["year"], int)
    assert windsor["summary"].endswith("Theatre Royal Windsor.")
    assert bare["year"] is None and bare["summary"] is None
    assert bare["name"] == "Hamlet"


def test_which_one_is_current_is_known_by_its_guid_and_not_by_its_place(client, monkeypatch):
    item = a_film(guid="plex://movie/delacorte")
    install(monkeypatch, Plex(item, [WINDSOR, DELACORTE]))
    answer = rematch.candidates(1)
    assert [row["current"] for row in answer["candidates"]] == [False, True]
    assert answer["current_guid"] == "plex://movie/delacorte"


def test_the_agent_is_the_librarys_because_a_candidate_has_none(client, monkeypatch):
    """plexapi's SearchResult offers an agent and a score."""
    item = a_film()
    install(monkeypatch, Plex(item, [WINDSOR]))
    answer = rematch.candidates(1)
    assert answer["agent"] == "tv.plex.agents.movie"
    assert "agent" not in answer["candidates"][0]


def test_nothing_found_is_an_empty_list_rather_than_a_failure(client, monkeypatch):
    """An agent that matched nothing is an answer."""
    item = a_film()
    install(monkeypatch, Plex(item, []))
    answer = rematch.candidates(1)
    assert answer["candidates"] == []
    assert answer["current_guid"] == "plex://movie/windsor"


def test_an_episode_is_offered_its_shows_match(client, monkeypatch):
    from app.models import MediaItem

    with session_scope() as db:
        db.add(MediaItem(rating_key=50, title="A Show", media_type="show", section_id=2, year=2005,
                         tvdb_id="7777"))
        db.add(MediaItem(rating_key=51, title="An Episode", media_type="episode", section_id=2,
                         grandparent_rating_key=50, grandparent_title="A Show"))
    show = Item(50, "plex://show/one", "A Show", 2005, ("tvdb://7777",), kind="show")
    install(monkeypatch, Plex(show, [WINDSOR]))
    answer = rematch.candidates(51)
    assert answer["rating_key"] == 50
    assert answer["asked_about"] == 51 and answer["instead_of"] == "episode"
    assert answer["title"] == "A Show"


def test_an_item_this_app_has_never_scanned_says_so(client, monkeypatch):
    install(monkeypatch, Plex(a_film(), [WINDSOR]))
    with pytest.raises(LookupError):
        rematch.candidates(9999)


# ---- applying one ----------------------------------------------------------


def test_a_guid_plex_did_not_offer_is_refused_and_nothing_is_written(client, monkeypatch):
    """The guid has to be one from this item's own list."""
    item = a_film()
    plex = install(monkeypatch, Plex(item, [WINDSOR, DELACORTE]))
    with pytest.raises(LookupError):
        rematch.apply(1, "plex://movie/something-else")
    assert plex.applied == []
    assert item.guid == "plex://movie/windsor"


def test_the_name_plex_is_given_is_plexs_own(client, monkeypatch):
    item = a_film()
    plex = install(monkeypatch, Plex(item, [WINDSOR, DELACORTE]))
    rematch.apply(1, "plex://movie/delacorte")
    assert plex.applied == [(1, "plex://movie/delacorte", "Hamlet")]


def test_an_id_the_new_match_does_not_have_is_cleared_rather_than_left(client, monkeypatch):
    """The reason the row is written here at all."""
    from app.models import MediaItem

    item = a_film()
    install(monkeypatch, Plex(item, [WINDSOR, DELACORTE], after_ids=("imdb://tt4242",)))
    done = rematch.apply(1, "plex://movie/delacorte")
    with session_scope() as db:
        row = db.get(MediaItem, 1)
        assert row.imdb_id == "tt4242"
        assert row.tmdb_id is None, "the old match's TMDB id survived"
        assert row.tvdb_id is None, "the old match's TVDB id survived"
    assert done["changed"]["tmdb_id"] == {"was": "111", "now": None}


def test_the_file_is_read_again_because_its_metadata_is_the_old_matchs(client, monkeypatch):
    from datetime import UTC, datetime

    from app.models import MediaItem

    item = a_film()
    with session_scope() as db:
        db.get(MediaItem, 1).file_checked_at = datetime.now(UTC).replace(tzinfo=None)
    install(monkeypatch, Plex(item, [WINDSOR, DELACORTE]))
    rematch.apply(1, "plex://movie/delacorte")
    with session_scope() as db:
        assert db.get(MediaItem, 1).file_checked_at is None


def test_the_episodes_under_a_re_matched_show_lose_their_ids_too(client, monkeypatch):
    """A show re-matched changes every episode's guids with it."""
    from datetime import UTC, datetime

    from app.models import MediaItem

    when = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as db:
        db.add(MediaItem(rating_key=50, title="A Show", media_type="show", section_id=2, tvdb_id="7777"))
        for key in (51, 52):
            db.add(MediaItem(rating_key=key, title=f"Episode {key}", media_type="episode", section_id=2,
                             grandparent_rating_key=50, tvdb_id="7777", tmdb_id="888",
                             file_checked_at=when))
    show = Item(50, "plex://show/one", "A Show", 2005, ("tvdb://7777",), kind="show")
    install(monkeypatch, Plex(show, [WINDSOR, DELACORTE], after_ids=("tvdb://9999",)))
    done = rematch.apply(51, "plex://movie/delacorte")
    assert done["episodes_cleared"] == 2
    with session_scope() as db:
        assert db.get(MediaItem, 50).tvdb_id == "9999"
        for key in (51, 52):
            episode = db.get(MediaItem, key)
            assert (episode.tvdb_id, episode.tmdb_id) == (None, None)
            assert episode.file_checked_at is None


def test_ids_that_have_not_arrived_are_reported_rather_than_assumed(client, monkeypatch):
    item = a_film()
    monkeypatch.setattr(rematch, "SETTLE_WAITS", (0, 0))
    install(monkeypatch, Plex(item, [WINDSOR, DELACORTE], after_ids=()))
    done = rematch.apply(1, "plex://movie/delacorte")
    assert done["ids_arrived"] is False
    assert done["ids"] == {"imdb_id": None, "tmdb_id": None, "tvdb_id": None}


# ---- through the endpoints -------------------------------------------------


def test_the_candidates_are_admin_only_and_read_nothing_into_plex(client, monkeypatch):
    claim(client)
    item = a_film()
    plex = install(monkeypatch, Plex(item, [WINDSOR, DELACORTE]))
    answer = client.get("/api/library/file/1/match").json()
    assert [row["name"] for row in answer["candidates"]] == ["Hamlet", "Hamlet"]
    assert plex.applied == []


def test_applying_one_is_written_to_the_log_naming_what_it_became(client, monkeypatch):
    """The other Plex writes are in the log and this one changes what a title is."""
    from app.models import AuditLog

    claim(client)
    item = a_film()
    install(monkeypatch, Plex(item, [WINDSOR, DELACORTE]))
    answer = client.post("/api/library/file/1/match", json={"guid": "plex://movie/delacorte"})
    assert answer.status_code == 200, answer.text
    with session_scope() as db:
        entry = db.query(AuditLog).filter(AuditLog.action == "library.match").one()
        assert "Hamlet" in entry.summary
        assert "delacorte" in (entry.payload or "")


def test_a_choice_plex_has_moved_on_from_comes_back_as_a_conflict(client, monkeypatch):
    """Not a 500."""
    claim(client)
    item = a_film()
    install(monkeypatch, Plex(item, [WINDSOR]))
    answer = client.post("/api/library/file/1/match", json={"guid": "plex://movie/delacorte"})
    assert answer.status_code == 409
    assert "read again" in answer.json()["detail"]

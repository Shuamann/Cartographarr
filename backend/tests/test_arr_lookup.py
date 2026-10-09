"""Finding a title in Radarr or Sonarr, and saying so when it is not there.

"Not in Radarr" about a film plainly sitting in Radarr. The lookup asked
/api/v3/movie?tmdbId= and nothing else, so the message was true and useless.

Found on a real library: Plex had matched a Hamlet (2024) to a filmed stage
production at Theatre Royal Windsor, 117 minutes, while Radarr held the Public
Theater one from the Delacorte, 154 minutes, under a different id. Two
different films of the same play in the same year is exactly the case nothing
here could tell apart, and the flat denial gave nobody a thread to pull.

Each test below was watched failing against the mistake it names.
"""

from __future__ import annotations

import asyncio

import pytest

from app.integrations import arr

WINDSOR = "1205709"
"""What Plex matched the file to."""

DELACORTE_IMDB = "tt20598076"


@pytest.fixture
def radarr(monkeypatch):
    """A Radarr holding one film, answering only the ids it was told about."""
    asked: list[dict] = []
    holds: dict[tuple[str, str], dict] = {}

    async def get_json(url, headers=None, params=None):
        asked.append(dict(params or {}))
        for param, value in (params or {}).items():
            found = holds.get((param, str(value)))
            if found:
                return [found]
        return []

    monkeypatch.setattr("app.integrations.arr.get_json", get_json)
    monkeypatch.setattr(type(arr.radarr), "base_url", property(lambda self: "http://radarr.invalid"))
    monkeypatch.setattr(type(arr.radarr), "api_key", property(lambda self: "k"))
    return asked, holds


def test_a_film_is_found_by_the_id_plex_matched_it_to(radarr):
    asked, holds = radarr
    holds[("tmdbId", WINDSOR)] = {"id": 7, "title": "Hamlet"}
    assert asyncio.run(arr.radarr.find(WINDSOR))["id"] == 7
    assert asked == [{"tmdbId": WINDSOR}], "the second id costs a request and should not be spent when the first works"


def test_imdb_is_tried_when_the_other_id_finds_nothing(radarr):
    """The two disagree more often than either is simply absent, and either
    agreeing is enough to find the film."""
    asked, holds = radarr
    holds[("imdbId", DELACORTE_IMDB)] = {"id": 7, "title": "Hamlet"}
    assert asyncio.run(arr.radarr.find(WINDSOR, DELACORTE_IMDB))["id"] == 7
    assert asked == [{"tmdbId": WINDSOR}, {"imdbId": DELACORTE_IMDB}]


def test_nothing_is_found_when_neither_id_is_there(radarr):
    asked, _ = radarr
    assert asyncio.run(arr.radarr.find(WINDSOR, DELACORTE_IMDB)) is None
    assert len(asked) == 2


def test_no_second_id_means_no_second_request(radarr):
    asked, _ = radarr
    assert asyncio.run(arr.radarr.find(WINDSOR)) is None
    assert asked == [{"tmdbId": WINDSOR}]


def test_the_message_names_what_it_looked_for():
    """The whole point. Seeing that the id belongs to a different film is a
    glance; working out why the app is wrong about a film sitting in front of
    you is an evening."""
    said = str(arr.radarr._missing(WINDSOR, DELACORTE_IMDB))
    assert WINDSOR in said and DELACORTE_IMDB in said
    assert "TMDB id" in said and "IMDb id" in said


def test_the_message_does_not_claim_the_film_is_absent():
    """It is usually there. What is absent is anything under that id, and the
    difference is the whole of the answer."""
    said = str(arr.radarr._missing(WINDSOR, DELACORTE_IMDB)).lower()
    assert "not in radarr" not in said
    assert "another id" in said or "different title" in said


def test_a_service_with_one_id_names_only_that_one():
    """Sonarr's series endpoint filters on tvdbId alone, so naming an IMDb id
    it never looked for would send somebody checking the wrong thing."""
    said = str(arr.sonarr._missing("369973", "tt20598076"))
    assert "TVDB id 369973" in said
    assert "tt20598076" not in said


def test_sonarr_never_spends_a_second_request(monkeypatch):
    asked: list[dict] = []

    async def get_json(url, headers=None, params=None):
        asked.append(dict(params or {}))
        return []

    monkeypatch.setattr("app.integrations.arr.get_json", get_json)
    monkeypatch.setattr(type(arr.sonarr), "base_url", property(lambda self: "http://sonarr.invalid"))
    monkeypatch.setattr(type(arr.sonarr), "api_key", property(lambda self: "k"))
    assert asyncio.run(arr.sonarr.find("369973", "tt20598076")) is None
    assert asked == [{"tvdbId": "369973"}]


def test_searching_says_which_id_it_could_not_find(radarr):
    """The message has to reach the person, not stop at the lookup."""
    with pytest.raises(LookupError) as raised:
        asyncio.run(arr.radarr.search(WINDSOR, alt_id=DELACORTE_IMDB))
    assert WINDSOR in str(raised.value)


def test_locating_for_a_replacement_says_the_same(radarr):
    with pytest.raises(LookupError) as raised:
        asyncio.run(arr.radarr.locate(WINDSOR, None, None, DELACORTE_IMDB))
    assert WINDSOR in str(raised.value)

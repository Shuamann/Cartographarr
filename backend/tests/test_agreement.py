"""Do the two sources actually say the same thing?

Counting is not enough. A total agreeing says nothing about whether the right
value reached the right column, which is how the transcode decision nearly
went wrong: both sources reported the same stream, one called it a copy and
the other a transcode, and every rule anybody has written matches on that
word.
"""

import asyncio

from tests.test_auth import claim


def test_a_field_both_sources_agree_on_is_not_reported():
    from app.services import agreement

    differ, here, there = {}, {}, {}
    agreement._compare(("codec",), {"codec": "hevc"}, {"codec": "hevc"}, differ, here, there)
    assert (differ, here, there) == ({}, {}, {})


def test_a_number_and_the_same_number_written_out_are_the_same_thing():
    """One source answers in numbers and the other in strings for the same
    fact. Reporting that as a disagreement would bury the real ones."""
    from app.services import agreement

    differ, here, there = {}, {}, {}
    agreement._compare(("channels",), {"channels": 6}, {"channels": "6"}, differ, here, there)
    agreement._compare(("codec",), {"codec": "EAC3"}, {"codec": "eac3"}, differ, here, there)
    assert differ == {}


def test_the_disagreement_that_nearly_shipped_would_be_caught():
    """The real case: a stream whose video was copied and whose audio was
    being converted. Tautulli called the session a transcode; reading the
    video decision alone called it a copy."""
    from app.services import agreement

    differ, here, there = {}, {}, {}
    agreement._compare(
        ("transcode_decision",),
        {"transcode_decision": "copy"}, {"transcode_decision": "transcode"},
        differ, here, there,
    )
    assert differ == {"transcode_decision": [{"plex": "copy", "tautulli": "transcode"}]}


def test_a_field_one_source_leaves_empty_is_named_not_counted_as_a_difference():
    """Empty and wrong are different problems. A field Plex does not fill is
    something to go and fetch; a field with the wrong value in it is something
    that is actively lying."""
    from app.services import agreement

    differ, here, there = {}, {}, {}
    agreement._compare(("imdb_id",), {"imdb_id": None}, {"imdb_id": "tt1"}, differ, here, there)
    agreement._compare(("file_path",), {"file_path": "/f.mkv"}, {"file_path": None}, differ, here, there)
    assert differ == {}
    assert here == {"imdb_id": 1} and there == {"file_path": 1}


def test_with_nothing_playing_it_says_so_rather_than_reporting_agreement(client, monkeypatch):
    """Nothing to compare is not the same answer as everything matches, and
    the second one would be believed."""
    from app.plex import activity as plex_activity
    from app.services import agreement

    claim(client)
    monkeypatch.setattr(plex_activity, "read", lambda: {"sessions": []})

    class NoStreams:
        async def call(self, command, **params):
            return {"sessions": []}

    answer = asyncio.run(agreement.streams(NoStreams()))
    assert answer["asked"] is False and "nothing is playing" in answer["reason"]


def test_a_stream_only_one_source_can_see_is_named(client, monkeypatch):
    """The most useful finding of all: one source knowing about a stream the
    other does not means the switch would lose it."""
    from app.plex import activity as plex_activity
    from app.services import agreement

    claim(client)
    monkeypatch.setattr(plex_activity, "read", lambda: {"sessions": [
        {"session_key": "1", "transcode_decision": "transcode"},
        {"session_key": "2", "transcode_decision": "direct play"},
    ]})

    class OneStream:
        async def call(self, command, **params):
            return {"sessions": [{"session_key": "1", "transcode_decision": "transcode"}]}

    answer = asyncio.run(agreement.streams(OneStream()))
    assert answer["asked"] is True and answer["only_plex"] == ["2"] and answer["only_tautulli"] == []


def test_it_needs_both_sources_before_it_will_compare_them(client):
    claim(client)
    answer = client.get("/api/handover/agreement").json()
    assert answer["asked"] is False and "Plex" in answer["reason"]

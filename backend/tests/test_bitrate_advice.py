from datetime import UTC, datetime, timedelta

from tests.test_auth import claim


def seed(clean: list[int], stalled: list[int], days_ago: int = 1):
    from app.db import session_scope
    from app.models import StreamSession

    when = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_ago)
    with session_scope() as db:
        for n, bitrate in enumerate(clean):
            db.add(StreamSession(session_key=f"c{n}", user_id=7, location="wan", file_bitrate=bitrate,
                                 buffer_count=0, started_at=when, last_seen_at=when))
        for n, bitrate in enumerate(stalled):
            db.add(StreamSession(session_key=f"s{n}", user_id=7, location="wan", file_bitrate=bitrate,
                                 buffer_count=3, started_at=when, last_seen_at=when))


def test_the_number_comes_from_streams_that_worked(client):
    claim(client)
    # Thirty clean streams up to 8 Mbps, ten that stalled at twice that.
    seed(clean=[4000] * 27 + [8000] * 3, stalled=[16000] * 10)
    answer = client.get("/api/library/bitrate-advice").json()
    assert answer["clean_streams"] == 30 and answer["stalled_streams"] == 10
    assert answer["clean_high"] == 8.0 and answer["stalled_high"] == 16.0
    assert answer["suggestion"] == 8.0
    assert "8.0 Mbps or under" in answer["why"]


def test_it_rounds_to_something_a_person_would_type(client):
    claim(client)
    seed(clean=[4000] * 27 + [8430] * 3, stalled=[16000] * 10)
    answer = client.get("/api/library/bitrate-advice").json()
    # 8.4 is a precision two hundred streams do not earn.
    assert answer["clean_high"] == 8.4 and answer["suggestion"] == 8.5


def test_nothing_is_offered_without_enough_watching(client):
    claim(client)
    seed(clean=[5000] * 10, stalled=[15000] * 2)
    answer = client.get("/api/library/bitrate-advice").json()
    assert answer["suggestion"] is None
    assert "Not enough remote watching" in answer["why"]


def test_nothing_is_offered_when_the_bitrate_is_not_the_problem(client):
    claim(client)
    # The streams that stalled are no bigger than the ones that did not, so
    # whatever is wrong out there, it is not the size of the files.
    seed(clean=[9000] * 30, stalled=[5000] * 10)
    answer = client.get("/api/library/bitrate-advice").json()
    assert answer["suggestion"] is None
    assert "not what is going wrong" in answer["why"]


def test_local_streams_have_no_say_in_it(client):
    from app.db import session_scope
    from app.models import StreamSession

    claim(client)
    seed(clean=[4000] * 27 + [8000] * 3, stalled=[16000] * 10)
    when = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as db:
        for n in range(40):
            # Enormous files watched on the sofa, which say nothing about
            # what fits down the line out of the house.
            db.add(StreamSession(session_key=f"l{n}", user_id=7, location="lan", file_bitrate=80000,
                                 buffer_count=0, started_at=when, last_seen_at=when))
    answer = client.get("/api/library/bitrate-advice").json()
    assert answer["clean_streams"] == 30 and answer["suggestion"] == 8.0


def test_viewers_cannot_ask(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "all")
    assert client.get("/api/library/bitrate-advice").status_code == 403

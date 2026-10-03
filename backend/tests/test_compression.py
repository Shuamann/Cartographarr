"""Responses are compressed on the way out.

JSON takes it better than almost anything, being mostly repeated key names:
this server's largest response is 420 KB uncompressed and 24 KB gzipped. The
front end is served from the same app, so the bundle gains too.
"""

from tests.test_auth import claim


def test_a_big_response_comes_back_compressed(client):
    claim(client)
    answer = client.get("/api/settings", headers={"Accept-Encoding": "gzip"})
    assert answer.status_code == 200
    assert answer.headers.get("content-encoding") == "gzip"


def test_a_client_that_cannot_take_it_still_gets_the_answer(client):
    claim(client)
    answer = client.get("/api/settings", headers={"Accept-Encoding": "identity"})
    assert answer.status_code == 200
    assert "content-encoding" not in answer.headers
    assert answer.json()


def test_a_small_response_is_left_alone(client):
    """Below a kilobyte the header costs more than the saving."""
    answer = client.get("/health", headers={"Accept-Encoding": "gzip"})
    assert answer.status_code == 200
    assert answer.headers.get("content-encoding") != "gzip"

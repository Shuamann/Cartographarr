"""Credentials never reach a page, the Log or the container log.

Tautulli takes its key in the query string, so its errors carry it. This was
found returning the key to any signed-in viewer when a poster failed to load.
"""

import asyncio
import logging

import httpx

from app.redact import RedactingFilter, redact


def test_query_keys_and_basic_auth_are_hidden():
    url = "https://stats.example.com/api/v2?rating_key=1&apikey=abc123def&cmd=get_metadata"
    assert "abc123def" not in redact(url) and "rating_key=1" in redact(url) and "cmd=get_metadata" in redact(url)
    assert "tok" not in redact("http://plex:32400/library?X-Plex-Token=tok")
    assert redact("mailtos://me:hunter2@smtp.example.com") == "mailtos://***@smtp.example.com"
    assert redact("nothing secret here") == "nothing secret here"


def test_tautulli_http_errors_do_not_carry_the_key():
    from app.config import Settings
    from app.tautulli.client import TautulliClient, TautulliError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, request=request)

    settings = Settings(tautulli_url="https://stats.example.com", tautulli_api_key="supersecretkey123")
    client = TautulliClient(settings, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        asyncio.run(client.call("get_metadata", rating_key=5))
    except TautulliError as exc:
        assert "supersecretkey123" not in str(exc) and "400" in str(exc)
    else:
        raise AssertionError("expected a TautulliError")


def test_log_records_are_cleaned():
    record = logging.LogRecord("x", logging.WARNING, __file__, 1, "failed %s", ("http://h/api?apikey=zzz999",), None)
    RedactingFilter().filter(record)
    assert "zzz999" not in record.getMessage()


def test_artwork_failure_does_not_return_the_key(client, monkeypatch):
    from app.db import session_scope
    from app.models import MediaItem
    from tests.test_auth import claim

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=77, title="Film", media_type="movie", thumb="/library/metadata/77/thumb"))
    async def refuse(self, url, params=None, **kwargs):
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(400, request=request)

    # A real 400 from Tautulli, whose error text includes the full request URL.
    monkeypatch.setattr(httpx.AsyncClient, "get", refuse)
    res = client.get("/api/media/77/image")
    assert res.status_code == 502
    # The test environment's key is "test".
    assert "apikey=test" not in res.text and "apikey=***" in res.text

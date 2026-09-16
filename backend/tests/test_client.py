import asyncio

import httpx
import pytest
import respx

from app.config import Settings
from app.tautulli.client import TautulliClient, TautulliError

SETTINGS = Settings(tautulli_url="http://tautulli:8181", tautulli_api_key="k")
API = "http://tautulli:8181/api/v2"


def call(client: TautulliClient, cmd: str, **params):
    async def go():
        try:
            return await client.call(cmd, **params)
        finally:
            await client.aclose()

    return asyncio.run(go())


@respx.mock
def test_unwraps_response_envelope():
    respx.get(API).respond(json={"response": {"result": "success", "data": {"data": [{"a": 1}]}}})
    assert call(TautulliClient(SETTINGS), "get_history") == {"data": [{"a": 1}]}


@respx.mock
def test_error_in_body_raises_despite_http_200():
    # The reason this client checks the envelope and not the status code.
    respx.get(API).respond(200, json={"response": {"result": "error", "message": "bad key"}})
    with pytest.raises(TautulliError, match="bad key"):
        call(TautulliClient(SETTINGS), "get_history")


@respx.mock
def test_drops_none_params_and_sends_auth():
    route = respx.get(API).respond(json={"response": {"result": "success", "data": {}}})
    call(TautulliClient(SETTINGS), "get_history", user_id=None, length=5)
    sent = httpx.URL(str(route.calls.last.request.url)).params
    assert "user_id" not in sent
    assert sent["length"] == "5"
    assert sent["apikey"] == "k"


def test_missing_config_is_refused_at_construction():
    with pytest.raises(RuntimeError, match="TAUTULLI_API_KEY"):
        TautulliClient(Settings(tautulli_url="http://x", tautulli_api_key=""))

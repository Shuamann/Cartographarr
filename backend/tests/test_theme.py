"""The four colours a person may set, and what is refused.

They end up inside a style the browser applies, so the shape is checked here
rather than trusted from the page that sent it.
"""

import json

import pytest
from pydantic import ValidationError

from app.config import Settings
from tests.test_auth import claim


def theme(value):
    return Settings(theme_colors=value).theme_colors


def test_a_scheme_is_kept_and_tidied():
    kept = json.loads(theme('{"dark": {"bg": "#0B0B0D", "ink": "fff"}}'))
    assert kept == {"dark": {"bg": "#0b0b0d", "ink": "#ffffff"}}


def test_empty_parts_and_empty_themes_fall_away():
    assert theme('{"dark": {"bg": ""}}') == ""
    assert theme("{}") == ""
    assert theme("") == ""


@pytest.mark.parametrize("bad", [
    "not json",
    "[]",
    '{"sepia": {"bg": "#000000"}}',        # only dark and light exist
    '{"dark": {"glow": "#000000"}}',       # only the four parts
    '{"dark": {"bg": "red"}}',             # hex only
    '{"dark": {"bg": "javascript:alert(1)"}}',
    '{"dark": "#000000"}',
])
def test_anything_else_is_refused(bad):
    with pytest.raises(ValidationError):
        theme(bad)


def test_the_scheme_is_served_before_anyone_signs_in(client):
    claim(client)
    scheme = '{"dark": {"bg": "#101012", "surface": "#18181b", "bar": "#141416", "ink": "#ededef"}}'
    assert client.put("/api/settings", json={"theme_colors": scheme}).status_code == 200
    # No cookie needed: the sign-in page is the app's face too.
    client.cookies.clear()
    assert json.loads(client.get("/api/branding").json()["theme"]) == json.loads(scheme)


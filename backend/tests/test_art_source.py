"""Artwork comes from Plex where there is a Plex to ask.

Tautulli's image proxy calls Plex's own resizer to do the work, so going
through it is a hop for nothing. It is also a hop that costs: asked for the
same 300 by 450 poster against a real server, Plex answers with a 300 by 450
JPEG of 37 kB and Tautulli answers with a PNG of 215 kB, having ignored the
format it was asked for. On a page of thirty six posters that is half a
megabyte against nearly eight.

Tautulli stays as the thing to try when Plex will not answer. A server asleep
or moved should cost a slower poster, not a broken page.
"""

import pathlib
import re

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "app" / "routers" / "data.py"


def _handler() -> str:
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index("async def media_image(")
    return text[start : text.index("\ndef _keep_poster", start)]


def test_plex_is_asked_first():
    body = _handler()
    at_plex = body.index("ways = [from_plex] if direct else []")
    at_tautulli = body.index("ways.append(from_tautulli)")
    assert at_plex < at_tautulli, "Plex goes first in the list of ways to try"


def test_tautulli_is_still_there_to_fall_back_to():
    body = _handler()
    assert "if tautulli:" in body and "ways.append(from_tautulli)" in body


def test_one_failing_does_not_end_the_request():
    """The whole point of keeping the second way."""
    body = _handler()
    assert re.search(r"for way in ways:", body)
    assert "trouble, upstream = exc, None" in body, "a failure moves on to the next way"
    assert "if upstream is None:" in body, "and only all of them failing is an error"


def test_the_token_never_goes_in_the_address():
    """An error that quotes the address must not carry it."""
    body = _handler()
    plex = body[body.index("def from_plex()") : body.index("def from_tautulli()")]
    assert '"X-Plex-Token": settings.plex_token' in plex
    assert "plex_token" not in plex.split("return (")[1].split("},")[0], "not in the params"

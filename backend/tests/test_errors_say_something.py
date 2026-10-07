"""An error that says nothing is worse than no error at all.

A red box with nothing in it tells somebody the app knows something went
wrong and will not say what, which is the one state worse than staying quiet.

It happened because the client read `detail` only when it was a string.
FastAPI returns a validation failure as a list, so the fallback was reached,
and the fallback was `res.statusText`, which is empty on HTTP/2: every install
behind a reverse proxy. Verified against the real server: a 422 comes back
with detail as a list.
"""

import pathlib
import re

API = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "api.ts"


def _error_path() -> str:
    source = API.read_text(encoding="utf-8")
    start = source.index("if (!res.ok)")
    return source[start : source.index("return res.json()", start)]


def test_a_validation_failure_is_read_rather_than_skipped():
    """It arrives as a list of what each field objected to. Naming the field
    beats naming nothing."""
    block = _error_path()
    assert "Array.isArray(body?.detail)" in block


def test_there_is_always_something_left_to_say():
    """statusText is empty on HTTP/2, so it cannot be the last resort."""
    block = _error_path()
    assert re.search(r"if \(!message\.trim\(\)\)", block), "a blank message has to be replaced"
    assert "res.status}" in block, "and the last thing said should at least carry the status"


def test_the_message_is_never_only_the_status_text():
    """The exact shape of the fault: statusText assigned as the starting value
    and nothing checking it afterwards."""
    block = _error_path()
    first = block.index("let message")
    assert "res.statusText" not in block[first : block.index("\n", first)], (
        "statusText must not be the starting value, it is empty on HTTP/2"
    )

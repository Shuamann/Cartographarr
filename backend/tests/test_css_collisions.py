"""House style: one stylesheet, so a class name may only be defined once.

Three bugs in one session came from the same mistake. A generic class name was
reused for an unrelated component, and because the stylesheet is a single file
the later rule silently won:

- `.row` was a flex utility, then used on a <tr>, which turned table rows into
  flexboxes and stopped the columns lining up
- `.summary` was a map stat strip, then an episode synopsis, which changed the
  strip from flex to flow-root and stacked the tiles into a column

Neither produced an error. Both produced a layout that looked vaguely wrong.
Defining the same simple selector twice is now a failing test rather than a
thing to notice in a screenshot.
"""

import pathlib
import re
from collections import Counter

CSS = pathlib.Path(__file__).resolve().parents[2] / "frontend/src/theme/app.css"

# Only rules whose whole selector is one bare class. `.pill` and `.pill.warn`
# are a deliberate pair, `.btn:hover` refines `.btn`, and a shared
# `.req, .opt { }` block followed by specifics for each is normal. None of
# those are the mistake being hunted.
SIMPLE_CLASS = re.compile(r"^\.([a-zA-Z][\w-]*)$")
COMMENTS = re.compile(r"/\*.*?\*/", re.DOTALL)


def selectors(css: str):
    """Yield the selector text of every top level rule."""
    for chunk in COMMENTS.sub("", css).split("}"):
        if "{" in chunk:
            yield chunk.rsplit("{", 1)[0].strip()


def test_no_class_is_defined_twice():
    if not CSS.exists():  # backend-only checkouts
        return

    names = [
        match.group(1)
        for selector in selectors(CSS.read_text(encoding="utf-8"))
        if (match := SIMPLE_CLASS.match(selector))
    ]
    repeated = {name: count for name, count in Counter(names).items() if count > 1}

    assert not repeated, (
        "These class names are defined more than once, so the later rule wins "
        "and quietly changes the earlier component: "
        + ", ".join(f"{name} ({count}x)" for name, count in sorted(repeated.items()))
    )


def duplicates(css: str) -> dict[str, int]:
    names = [
        match.group(1)
        for selector in selectors(css)
        if (match := SIMPLE_CLASS.match(selector))
    ]
    return {name: count for name, count in Counter(names).items() if count > 1}


def test_the_check_catches_the_bugs_it_was_written_for():
    # The two that actually happened.
    assert duplicates(".row { display: flex } .row { cursor: pointer }") == {"row": 2}
    assert duplicates(".summary { display: flex } .summary { display: block }") == {"summary": 2}


def test_the_check_leaves_normal_css_alone():
    assert duplicates(".pill { color: red } .pill.warn { color: blue }") == {}
    assert duplicates(".btn { color: red } .btn:hover { color: blue }") == {}
    assert duplicates(".req,\n.opt { margin: 0 }\n.opt { color: grey }") == {}
    assert duplicates(".a .b { color: red } .b { color: blue }") == {}
    assert duplicates("/* .row { } */ .row { color: red }") == {}

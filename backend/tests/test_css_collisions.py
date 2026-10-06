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


def without_media(css: str) -> str:
    """Drop @media blocks. Restyling a class for a narrow screen is the one
    legitimate reason to name it twice, and it cannot leak into another
    component the way a second top level rule does."""
    out, i = [], 0
    while (start := css.find("@media", i)) != -1:
        out.append(css[i:start])
        depth, j = 0, css.index("{", start)
        while True:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        i = j + 1
    out.append(css[i:])
    return "".join(out)


def selectors(css: str):
    """Yield the selector text of every top level rule."""
    for chunk in without_media(COMMENTS.sub("", css)).split("}"):
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
    assert duplicates(".card { gap: 8px } @media (max-width: 600px) { .card { gap: 4px } }") == {}


def test_media_blocks_do_not_hide_a_real_duplicate():
    css = ".card { gap: 8px } @media (max-width: 600px) { .x { color: red } } .card { gap: 2px }"
    assert duplicates(css) == {"card": 2}


def test_the_popup_card_does_not_lay_itself_out_by_the_window():
    """A media query asks how wide the window is, not how wide the card is.

    The stream card in the map's popup is 460px whatever the screen is. Two
    rules keyed to the viewport, a second column of facts and a value that may
    not wrap, both applied inside it on any normal monitor, and put a sideways
    scrollbar across the bottom of the popup.
    """
    css = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "theme" / "app.css").read_text(
        encoding="utf-8"
    )
    compact = css[css.index(".stream-detail.compact .spec {") :][:400]
    assert "grid-template-columns: minmax(0, 1fr);" in compact, "one column in a popup"
    assert ".stream-detail.compact .spec-pair dd" in compact and "white-space: normal" in compact, (
        "a fact in a popup has to be allowed to wrap"
    )
    flyout = css[css.index(".flyout {") :][:400]
    assert "overflow: hidden auto;" in flyout, (
        "overflow-y on its own leaves overflow-x computing to auto, which is the scrollbar"
    )


def test_a_tile_title_gives_up_the_episode_name_and_never_the_numbers():
    """What survives a clip has to be what identifies the thing.

    This was the wrong way round once. The show name gave way first, leaving
    "Y... - S02 - E04", which keeps the two numbers and loses the one word
    that makes them mean anything.
    """
    css = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "theme" / "app.css").read_text(
        encoding="utf-8"
    )
    show = css[css.index(".card-title-show {") :][:400]
    assert "flex: 0 0 auto;" in show, "the show name does not shrink"
    name = css[css.index(".card-title-name {") :][:300]
    assert "flex: 1 1 0;" in name, "the episode's name takes what is left, and gives way first"

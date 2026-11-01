import pathlib
import re
from collections import Counter

CSS = pathlib.Path(__file__).resolve().parents[2] / "frontend/src/theme/app.css"

# Only rules whose whole selector is one bare class. `.pill` and `.pill.warn`
SIMPLE_CLASS = re.compile(r"^\.([a-zA-Z][\w-]*)$")
COMMENTS = re.compile(r"/\*.*?\*/", re.DOTALL)


def without_media(css: str) -> str:
    """Drop @media blocks."""
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
    """A media query asks how wide the window is, not how wide the card is."""
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
    """What survives a clip has to be what identifies the thing."""
    css = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "theme" / "app.css").read_text(
        encoding="utf-8"
    )
    show = css[css.index(".card-title-show {") :][:400]
    assert "flex: 0 0 auto;" in show, "the show name does not shrink"
    name = css[css.index(".card-title-name {") :][:300]
    assert "flex: 1 1 0;" in name, "the episode's name takes what is left, and gives way first"


def test_the_narrow_facts_rule_does_not_reach_a_phone():
    """A media query with only an upper bound beats everything below it."""
    css = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "theme" / "app.css").read_text(
        encoding="utf-8"
    )
    for query in re.finditer(r"@media ([^{]+)\{", css):
        block = css[query.end() : css.find("\n}", query.end())]
        if re.search(r"^\s+\.spec \{", block, re.M) and "max-width" in query.group(1):
            assert "min-width" in query.group(1), (
                "the middling rule needs a floor as well as a ceiling: " + query.group(1).strip()
            )


def test_every_control_uses_the_one_control_height():
    css = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "theme" / "app.css").read_text(
        encoding="utf-8"
    )
    for name in (".legend-tab {", ".view-body .maplibregl-ctrl-group button {"):
        at = css.index(name)
        assert "var(--control-h)" in css[at : css.index("\n}", at)], name + " needs the control height token"


def test_a_text_box_stands_as_tall_as_the_buttons_beside_it():
    if not CSS.exists():  # backend-only checkouts
        return
    css = COMMENTS.sub("", CSS.read_text(encoding="utf-8"))
    rule = re.search(r"(^|\n)(input:not\(\[type=\"checkbox\"\]\)[^{]*,\s*select:not\(\[multiple\]\))\s*\{([^}]*)\}", css)
    assert rule, "the rule giving every text box the control height is gone"
    body = rule.group(3)
    assert re.search(r"(^|;|\s)height:\s*var\(--control-h\)", body), "a text box needs height: var(--control-h)"
    assert re.search(r"padding-top:\s*0", body) and re.search(r"padding-bottom:\s*0", body), (
        "vertical padding on a fixed height box only squeezes the text"
    )


def test_the_facts_grid_cannot_push_a_card_sideways():
    """The same trap the popup card was fixed for, in the same shape."""
    css = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "theme" / "app.css").read_text(
        encoding="utf-8"
    )
    for columns in re.finditer(r"\.spec \{[^}]*?grid-template-columns:([^;]+);", css, re.DOTALL):
        track = columns.group(1).strip()
        assert "repeat(" not in track or "minmax(0," in track.replace(" ", ""), (
            "a repeated track needs a floor of zero or it cannot give way: " + track
        )
    # The rule that holds a fact to one line, wherever it is written. There
    held = [
        body
        for body in re.findall(r"\.spec-pair dd \{([^}]*)\}", css)
        if "white-space: nowrap" in body
    ]
    assert held, "the rule holding a fact to one line is gone"
    for body in held:
        assert "text-overflow: ellipsis" in body and "overflow: hidden" in body, (
            "a value held to one line has to be cut when it will not fit, not carried outside the card"
        )


def test_a_table_scrolls_itself_on_a_phone():
    """A table cannot be narrower than its columns' own minimum."""
    css = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "theme" / "app.css").read_text(
        encoding="utf-8"
    )
    for query in re.finditer(r"@media ([^{]+)\{", css):
        block = css[query.end() : css.find("\n}", query.end())]
        if re.search(r"^\s+\.table \{", block, re.M) and "max-width" in query.group(1):
            rule = block[block.index(".table {") :]
            assert "display: block" in rule and "overflow-x: auto" in rule, (
                "a table needs both to scroll itself: " + rule[:120]
            )
            return
    raise AssertionError("the narrow-screen rule letting a table scroll itself is gone")

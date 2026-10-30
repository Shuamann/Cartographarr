"""Every destination on the front page has an icon.

The icons are keyed on the tab rather than on its label, because the label has
changed once already: what the code calls Endpoints has been shown as People.
A page added to the front page without an entry in that map would fall back to
the dashboard mark, so six entries would read as five and a repeat, and
nothing would fail.
"""

import pathlib
import re

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
HOME = FRONTEND / "routes" / "Home.tsx"
ICONS = FRONTEND / "components" / "TabIcon.tsx"


def destinations(source: str) -> set[str]:
    """Every tab the front page offers, for an admin and for a viewer."""
    inside = source[source.index("function destinations(") : source.index("export default function")]
    return set(re.findall(r'\{\s*tab:\s*"([A-Za-z]+)"', inside))


def mapped(source: str) -> set[str]:
    """Every tab the icon map names."""
    inside = source[source.index("const FOR_TAB") : source.index("export function iconForTab")]
    return set(re.findall(r'^\s{2}([A-Za-z]+):\s*"', inside, re.M))


def test_every_destination_has_an_icon():
    if not HOME.exists():  # backend-only checkouts
        return
    offered = destinations(HOME.read_text(encoding="utf-8"))
    # A pattern that finds nothing passes whatever the page says.
    assert len(offered) >= 6, f"found only {len(offered)} destinations; the pattern has drifted"
    missing = sorted(offered - mapped(ICONS.read_text(encoding="utf-8")))
    assert not missing, (
        "These would fall back to the dashboard mark rather than getting their own: " + ", ".join(missing)
    )


def test_issues_is_the_warning_one():
    """It is the one thing on that page somebody has to notice without reading
    it, so it is a triangle in the warning colour rather than a line drawing
    of the page it opens."""
    if not ICONS.exists():
        return
    source = ICONS.read_text(encoding="utf-8")
    assert re.search(r'Issues:\s*"issues"', source), "Issues has stopped pointing at its own mark"
    assert 'name === "issues"' in source, "nothing marks it out as the warning one any more"


def test_the_warning_colour_is_a_token_that_exists():
    """`--bg-2` was invented once and defined nowhere, and the thing that
    asked for it simply had no colour. A warning that does not show is worse
    than one drawn in the wrong shade."""
    css = (FRONTEND / "theme" / "app.css").read_text(encoding="utf-8")
    tokens = (FRONTEND / "theme" / "tokens.css").read_text(encoding="utf-8")
    assert ".tab-icon-warn" in css, "the warning icon has lost its rule"
    used = set(re.findall(r"var\((--[a-z0-9-]+)\)", css[css.index(".tab-icon-warn") :][:400]))
    for token in used:
        assert f"{token}:" in tokens, f"{token} is asked for and defined nowhere"


def test_the_icons_are_one_set():
    """Six marks at six weights read as six borrowed logos rather than a set,
    which is the whole reason these are drawn here instead of taken from
    somewhere."""
    if not ICONS.exists():
        return
    source = ICONS.read_text(encoding="utf-8")
    assert source.count('strokeWidth="1.75"') == 1, "one weight, set in one place"
    assert 'viewBox="0 0 24 24"' in source
    # Nothing filled: a filled shape beside stroked ones is the odd one out.
    assert 'fill="none"' in source

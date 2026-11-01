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
    if not ICONS.exists():
        return
    source = ICONS.read_text(encoding="utf-8")
    assert re.search(r'Issues:\s*"issues"', source), "Issues has stopped pointing at its own mark"
    assert 'name === "issues"' in source, "nothing marks it out as the warning one any more"


def test_the_warning_colour_is_a_token_that_exists():
    css = (FRONTEND / "theme" / "app.css").read_text(encoding="utf-8")
    tokens = (FRONTEND / "theme" / "tokens.css").read_text(encoding="utf-8")
    assert ".tab-icon-warn" in css, "the warning icon has lost its rule"
    used = set(re.findall(r"var\((--[a-z0-9-]+)\)", css[css.index(".tab-icon-warn") :][:400]))
    for token in used:
        assert f"{token}:" in tokens, f"{token} is asked for and defined nowhere"


def test_the_icons_are_one_set():
    if not ICONS.exists():
        return
    source = ICONS.read_text(encoding="utf-8")
    assert source.count('strokeWidth="1.75"') == 1, "one weight, set in one place"
    assert 'viewBox="0 0 24 24"' in source
    # Nothing filled: a filled shape beside stroked ones is the odd one out.
    assert 'fill="none"' in source

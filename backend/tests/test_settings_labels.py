import pathlib
import re

SETTINGS = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "routes" / "Settings.tsx"

DRAWN_THEMSELVES = {
    # These two are listed in their section so the page knows they belong to
    "accent_color",
    "theme_colors",
}


def listed_keys(source: str) -> list[str]:
    """Every key named in a section of the Settings page."""
    keys: list[str] = []
    for block in re.findall(r"keys:\s*\[([^\]]*)\]", source):
        keys += re.findall(r'"([a-z0-9_]+)"', block)
    return keys


def labelled(source: str) -> set[str]:
    """Every key the label map names."""
    return set(re.findall(r'^\s{2}([a-z0-9_]+):\s*"', source, re.M))


def test_every_setting_on_the_page_has_a_name():
    if not SETTINGS.exists():  # backend-only checkouts
        return
    source = SETTINGS.read_text(encoding="utf-8")
    keys = listed_keys(source)
    # A pattern that finds nothing passes whatever the page says.
    assert len(keys) >= 60, f"found only {len(keys)} settings on the page; the pattern has drifted from the code"
    known = labelled(source) | DRAWN_THEMSELVES
    missing = sorted({key for key in keys if key not in known})
    assert not missing, (
        "These settings would be drawn under their own key rather than a name: " + ", ".join(missing)
    )


def test_the_check_would_catch_one_that_was_forgotten():
    source = '''
      {
        title: "Something",
        keys: ["one_thing", "another_thing"],
      },
const NAMES: Record<string, string> = {
  one_thing: "The one thing",
};
'''
    assert listed_keys(source) == ["one_thing", "another_thing"]
    assert labelled(source) == {"one_thing"}


def test_the_check_does_not_mistake_a_nested_object_for_a_label():
    source = '  server_alert_minutes: { unit: "minutes", min: 0, max: 1440, step: 1 },'
    assert labelled(source) == set()

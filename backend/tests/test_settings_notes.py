import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SETTINGS = ROOT / "frontend" / "src" / "routes" / "Settings.tsx"


def test_a_section_note_is_only_ever_drawn_by_head():
    text = SETTINGS.read_text(encoding="utf-8")
    body = text[text.index("function Head(") :]
    end = body.index("\n}\n")
    outside = body[end:]
    offenders = [
        line.strip()
        for line in outside.splitlines()
        # A note put straight into a paragraph, rather than handed to Head.
        if re.search(r"<p[^>]*>\{\s*(section\.note|current\.blurb)\s*\}", line)
    ]
    assert not offenders, "Hand the note to Head so it folds away:\n" + "\n".join(offenders)


def test_head_folds_the_note_and_remembers():
    head = SETTINGS.read_text(encoding="utf-8")
    head = head[head.index("function Head(") :]
    head = head[: head.index("\n}\n")]
    assert "explain-toggle" in head, "the icon that opens it"
    assert "aria-expanded" in head, "a toggle says whether it is open"
    assert "localStorage" in head, "reading one note should not mean reopening it every visit"
    assert "note && open &&" in head, "closed until asked for"


def test_head_is_keyed_by_its_heading():
    """React keeps one instance per position, not per heading."""
    text = SETTINGS.read_text(encoding="utf-8")
    for call in re.findall(r"<Head\b[^>]*", text, re.S):
        # A heading written out in full always renders in its own place. One
        # computed from a variable is a single slot showing different headings.
        if re.search(r"what=\{", call):
            assert "key=" in call, "a Head whose heading varies needs a key:\n" + call[:200]

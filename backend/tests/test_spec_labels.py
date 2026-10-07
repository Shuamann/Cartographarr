"""A label beside a fact is one word.

The label column in a .spec grid is nine characters wide, so a fact can sit on
one line beside it. A single word too long for it simply runs on; two words
break at the space, and the label stands two lines tall beside a one line
value. The Issues card was written with "Watching on" and "That play", both
broke, and "Your plays" was written the same way again while fixing them. A
label that needs two words wants rewording, not a wider column.
"""

import pathlib
import re

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"

# The helpers that draw one cell of a .spec grid, by file. Three of these are
# now one shared component under a local name, so the check is that the name is
# bound in the file at all rather than that the file declares a function: three
# copies of the same five lines could not be fixed in one place, which is how
# the layout drifted apart in the first place.
CELLS = {
    "routes/Issues.tsx": "Pair",
    "components/StreamDetail.tsx": "Spec",
    "routes/People.tsx": "Stat",
    "routes/Library.tsx": "Fact",
    "components/Fact.tsx": "Fact",
}

# Files whose rows about titles carry facts written as { label, value }, the
# same label column in a row's own grid.
FACTS = ["routes/People.tsx", "routes/Map.tsx"]


def test_a_spec_label_is_one_word():
    if not FRONTEND.exists():  # backend-only checkouts
        return
    offenders = []
    seen = 0
    for rel, name in CELLS.items():
        source = (FRONTEND / rel).read_text(encoding="utf-8")
        assert f"function {name}(" in source or f"const {name} = " in source or f"import {name} " in source, (
            f"{rel} no longer draws its cells with {name}"
        )
        # The label, written either as a string or as an expression choosing
        # between strings, such as one for an admin and one for a viewer.
        for label in re.findall(rf"<{name}\b[^>]*?\blabel=(\"[^\"]*\"|\{{[^}}]*\}})", source):
            seen += 1
            for word in re.findall(r"\"([^\"]*)\"", label):
                if " " in word.strip():
                    offenders.append(f"{rel}: {word}")
    # A pattern that finds nothing passes whatever the labels say.
    assert seen >= 35, f"found only {seen} spec labels; the pattern has drifted from the code"
    assert not offenders, "Reword these to one word, or they break over two lines:\n" + "\n".join(offenders)


def test_a_row_fact_label_is_one_word():
    if not FRONTEND.exists():
        return
    offenders = []
    seen = 0
    for rel in FACTS:
        source = (FRONTEND / rel).read_text(encoding="utf-8")
        assert "<TitleRow" in source, f"{rel} no longer draws its titles with TitleRow"
        labels = re.findall(r"\{\s*label:\s*\"([^\"]*)\",\s*value:", source)
        # The extra facts a profile is given, written as [label, value].
        labels += re.findall(r"extra=\{\[\[\"([^\"]*)\"", source)
        seen += len(labels)
        offenders += [f"{rel}: {label}" for label in labels if " " in label.strip()]
    # A pattern that finds nothing passes whatever the labels say.
    assert seen >= 8, f"found only {seen} fact labels; the pattern has drifted from the code"
    assert not offenders, "Reword these to one word, or they break over two lines:\n" + "\n".join(offenders)

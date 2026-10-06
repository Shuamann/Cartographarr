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

# The helpers that draw one cell of a .spec grid, by file.
CELLS = {"routes/Issues.tsx": "Pair", "components/StreamDetail.tsx": "Spec"}


def test_a_spec_label_is_one_word():
    if not FRONTEND.exists():  # backend-only checkouts
        return
    offenders = []
    for rel, name in CELLS.items():
        source = (FRONTEND / rel).read_text(encoding="utf-8")
        assert f"function {name}(" in source, f"{rel} no longer draws its cells with {name}"
        # The label, written either as a string or as an expression choosing
        # between strings, such as one for an admin and one for a viewer.
        for label in re.findall(rf"<{name}\b[^>]*?\blabel=(\"[^\"]*\"|\{{[^}}]*\}})", source):
            for word in re.findall(r"\"([^\"]*)\"", label):
                if " " in word.strip():
                    offenders.append(f"{rel}: {word}")
    assert not offenders, "Reword these to one word, or they break over two lines:\n" + "\n".join(offenders)

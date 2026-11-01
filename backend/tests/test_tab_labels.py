import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


def test_a_tab_is_never_rendered_by_its_id():
    offenders = []
    for path in sorted(FRONTEND.rglob("*.tsx")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # A JSX expression whose whole content is the loop variable a list
            # of tabs is mapped over.
            if re.search(r">\{\s*(tab|t)\s*\}<", line):
                offenders.append(f"{path.relative_to(FRONTEND).as_posix()}:{number}: {line.strip()}")
    assert not offenders, (
        "Render a tab with tabLabel(), or a renamed tab keeps its old name here:\n" + "\n".join(offenders)
    )


def test_the_label_is_defined_once_and_used():
    tabs = (FRONTEND / "lib" / "tabs.ts").read_text(encoding="utf-8")
    assert "export function tabLabel" in tabs
    assert '"Endpoints"' in tabs, "the People tab reads as Endpoints"
    for rel in ("App.tsx", "routes/Home.tsx"):
        assert "tabLabel(" in (FRONTEND / rel).read_text(encoding="utf-8"), rel

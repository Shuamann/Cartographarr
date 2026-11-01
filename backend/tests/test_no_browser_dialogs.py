import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"

# Bare calls as well as window-qualified ones, since both reach the same thing.
NATIVE = re.compile(r"(?<![\w.$])(?:window\s*\.\s*)?(confirm|prompt|alert)\s*\(")

# The one file allowed to name them, because it explains what it replaced.
ALLOWED = {"components/Ask.tsx"}


def test_nothing_calls_the_browsers_dialogs():
    offenders = []
    for path in sorted(FRONTEND.rglob("*.ts*")):
        relative = path.relative_to(FRONTEND).as_posix()
        if relative in ALLOWED:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # A comment may say the word; only a call counts.
            without_comment = line.split("//")[0]
            if NATIVE.search(without_comment):
                offenders.append(f"{relative}:{number}: {line.strip()}")

    assert not offenders, (
        "The browser's own dialogs are not this app's. Use askConfirm, askText or tell "
        "from components/Ask.tsx:\n" + "\n".join(offenders)
    )

"""House style: the app asks its own questions, never the browser's.

window.confirm, window.prompt and window.alert are the browser's dialogs, not
this app's. They arrive in the wrong typeface in the wrong place, say
"127.0.0.1:6277 says" above the question, cannot show a poster or a file size
or put a warning in red, and on some browsers carry a "don't let this page ask
again" tickbox that silently turns every later question into a no. There is a
dialog in components/Ask.tsx that does all of it properly, so this exists to
stop one creeping back in.

Cheaper to enforce than to re-audit, the same way the em dash rule is.
"""

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

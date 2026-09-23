"""Check both halves of the app for known vulnerabilities.

Run before a release, or whenever a dependency moves:

    python scripts/audit.py

It asks pip-audit about the Python packages and npm about the JavaScript ones,
and exits non-zero if either finds something, so it can be wired into anything
that cares. Both need the internet; neither sends anything about this server.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(label: str, command: list[str], cwd: Path) -> int:
    found = shutil.which(command[0])
    if found is None:
        print(f"{label}: {command[0]} is not installed, skipping")
        return 0
    print(f"\n== {label} ==", flush=True)
    if found.lower().endswith((".cmd", ".bat")):
        # Windows cannot start a .cmd without a shell, and npm is one there.
        return subprocess.call(subprocess.list2cmdline([found, *command[1:]]), cwd=cwd, shell=True)
    return subprocess.call([found, *command[1:]], cwd=cwd)


def main() -> int:
    failures = 0
    failures += run("Python packages", [sys.executable, "-m", "pip_audit", "--progress-spinner", "off"], ROOT / "backend")
    failures += run("JavaScript packages", ["npm", "audit", "--omit=dev"], ROOT / "frontend")
    if failures:
        print("\nSomething needs attention above.")
    else:
        print("\nNothing known against either side.")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())

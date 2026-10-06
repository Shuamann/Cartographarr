"""Which version this is, which commit it was built from, and its changelog.

The version is bumped with every release and must match pyproject.toml and
the newest heading in CHANGELOG.md (a test holds them together). The commit
comes from the GIT_COMMIT build argument, or from the checkout when running
from source. Without either, update checks compare version numbers only.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

VERSION = "0.86.0"

_HERE = Path(__file__).resolve()
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_HEADING = re.compile(r"^##\s+v?(\d+\.\d+\.\d+)(?:\s+-\s+(\d{4}-\d{2}-\d{2}))?\s*$")


def parse_version(text: str | None) -> tuple[int, ...] | None:
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", (text or "").strip())
    return tuple(int(x) for x in match.groups()) if match else None


def _from_checkout() -> str | None:
    for root in (_HERE.parents[1], _HERE.parents[2]):
        git = root / ".git"
        head = git / "HEAD"
        if not head.is_file():
            continue
        try:
            ref = head.read_text(encoding="utf-8").strip()
            if not ref.startswith("ref: "):
                return ref
            name = ref[5:]
            loose = git / name
            if loose.is_file():
                return loose.read_text(encoding="utf-8").strip()
            packed = git / "packed-refs"
            if packed.is_file():
                for line in packed.read_text(encoding="utf-8").splitlines():
                    if line.endswith(f" {name}"):
                        return line.split(" ", 1)[0]
        except OSError:
            return None
    return None


@lru_cache
def commit() -> str | None:
    value = (os.environ.get("GIT_COMMIT") or "").strip().lower() or (_from_checkout() or "").lower()
    return value if _SHA.match(value) else None


def parse_changelog(text: str) -> list[dict[str, Any]]:
    """Versions, newest first, each with its sections of bullet points."""
    versions: list[dict[str, Any]] = []
    section: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        heading = _HEADING.match(line)
        if heading:
            versions.append({"version": heading.group(1), "date": heading.group(2), "sections": []})
            section = None
            continue
        if not versions:
            continue
        if line.startswith("### "):
            section = {"title": line[4:].strip(), "items": []}
            versions[-1]["sections"].append(section)
        elif line.lstrip().startswith("- "):
            if section is None:
                section = {"title": "Changes", "items": []}
                versions[-1]["sections"].append(section)
            section["items"].append(line.lstrip()[2:].strip())
        elif line.startswith("  ") and section and section["items"]:
            section["items"][-1] += " " + line.strip()
    return versions


@lru_cache
def changelog() -> list[dict[str, Any]]:
    # /srv/CHANGELOG.md in the image, the repository root from source.
    for root in (_HERE.parents[1], _HERE.parents[2]):
        path = root / "CHANGELOG.md"
        if path.is_file():
            return parse_changelog(path.read_text(encoding="utf-8"))
    return []

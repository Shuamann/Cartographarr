import ipaddress
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOOK_IN = ("backend", "frontend/src", "unraid", ".github")
KEEP = {".py", ".ts", ".tsx", ".md", ".css", ".yml", ".yaml", ".xml", ".json", ".toml", ".html"}
SKIP = {"node_modules", ".venv", "dist", "__pycache__", ".git", "data", "htmlcov"}

ADDRESS = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")

# An address written in source stands on its own, in quotes or alone. SVG path
EDGE = set("\"' \t,()[]{}=:;")

# Placeholders so obviously invented that nobody reads them as a real address.
MADE_UP = {"1.1.1.1", "2.2.2.2", "1.2.3.4", "5.6.7.8", "8.8.8.8", "203.0.0.0"}
DOCUMENTATION = ("203.0.113.", "198.51.100.", "192.0.2.")


def sources():
    for where in LOOK_IN:
        base = ROOT / where
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.suffix not in KEEP or any(part in SKIP for part in path.parts):
                continue
            if path.name.startswith("package-lock"):
                continue
            yield path


def addresses_in(line: str):
    for match in ADDRESS.finditer(line):
        before = line[match.start() - 1] if match.start() else " "
        after = line[match.end()] if match.end() < len(line) else " "
        if before in EDGE and after in EDGE:
            yield match.group()


def test_no_routable_address_is_written_down():
    found: dict[str, list[str]] = {}
    for path in sources():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_no, line in enumerate(text.splitlines(), 1):
            for candidate in addresses_in(line):
                try:
                    address = ipaddress.ip_address(candidate)
                except ValueError:
                    continue  # four numbers that are not an address
                if address.is_private or address.is_loopback or address.is_reserved:
                    continue  # Python counts the documentation ranges as private
                if address.is_multicast or address.is_unspecified:
                    continue
                if candidate in MADE_UP or candidate.startswith(DOCUMENTATION):
                    continue
                found.setdefault(candidate, []).append(f"{path.relative_to(ROOT)}:{line_no}")

    assert not found, "Real addresses do not belong in here. Use 203.0.113.x: " + "; ".join(
        f"{ip} at {', '.join(where)}" for ip, where in sorted(found.items())
    )


def test_the_check_would_notice_one():
    """A scan that matches nothing passes whatever the source says."""
    # Built from a number, so no address is written in this file either.
    real = ipaddress.ip_address(1234567890)
    routable = str(real)
    assert list(addresses_in(f'address="{routable}"')) == [routable]
    assert not (real.is_private or real.is_loopback or real.is_reserved)
    assert routable not in MADE_UP and not routable.startswith(DOCUMENTATION)
    # A documentation address is one Python calls private, which is the line
    # above doing most of the work.
    assert ipaddress.ip_address("203.0.113.75").is_private


def test_path_data_is_not_an_address():
    assert list(addresses_in('  imdb: "M22.3781 0H1.6218C.7411.0583.0587.7437.0018 1.5953l-.001 20.783",')) == []


def test_it_reads_the_files_it_claims_to():
    """Pointed at the wrong folder it would scan nothing and pass for ever."""
    scanned = {path.suffix for path in sources()}
    assert {".py", ".tsx"} <= scanned
    assert sum(1 for _ in sources()) > 100

import pathlib

EM_DASH = chr(0x2014)  # written as a codepoint so this file never contains one
ROOT = pathlib.Path(__file__).resolve().parents[2]

SUFFIXES = {".py", ".ts", ".tsx", ".css", ".md", ".yml", ".yaml", ".toml", ".html"}
NAMES = {"Dockerfile", ".env.example"}
SKIP_DIRS = {"node_modules", ".venv", ".git", "dist", "build", "__pycache__", "data"}


def source_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or SKIP_DIRS & set(path.parts):
            continue
        if path.suffix in SUFFIXES or path.name in NAMES:
            yield path


def test_no_em_dashes_anywhere():
    offenders = []
    for path in source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if EM_DASH in line:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}")

    assert not offenders, "Em dashes found. Use a comma, colon or period:\n" + "\n".join(offenders)

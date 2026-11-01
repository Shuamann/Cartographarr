from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import _Ui


def serve(tmp_path: Path) -> TestClient:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
    (tmp_path / "assets" / "Map-abc123.js").write_text("export default 1;", encoding="utf-8")
    app = FastAPI()
    app.mount("/", _Ui(directory=str(tmp_path), html=True), name="ui")
    return TestClient(app)


def test_the_entry_is_never_cached(tmp_path):
    client = serve(tmp_path)
    # The app routes by query string, so these two are the front door.
    for path in ("/", "/index.html"):
        assert "no-cache" in client.get(path).headers["cache-control"], path


def test_hashed_assets_are_kept_for_a_year(tmp_path):
    headers = serve(tmp_path).get("/assets/Map-abc123.js").headers
    assert "immutable" in headers["cache-control"] and "max-age=31536000" in headers["cache-control"]

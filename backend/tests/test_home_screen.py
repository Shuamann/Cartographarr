"""On a phone's home screen the app opens as an app, under its own mark.

Without a manifest, Add to Home Screen saves a bookmark with the browser's bars
still round it. Read before anybody signs in, because the phone asks for it
from the sign-in page.
"""

import io
import pathlib

from PIL import Image

from tests.test_auth import claim

INDEX = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "index.html"


def test_the_manifest_is_there_before_signing_in(client):
    answer = client.get("/api/branding/manifest.webmanifest")
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("application/manifest+json")
    body = answer.json()
    assert body["display"] == "standalone" and body["start_url"] == "/"
    assert {i["sizes"] for i in body["icons"]} == {"192x192", "512x512"}


def test_the_manifest_carries_the_name_it_is_given(client):
    claim(client)
    assert client.put("/api/settings", json={"app_name": "Harbour Watch"}).status_code == 200
    assert client.get("/api/branding/manifest.webmanifest").json()["name"] == "Harbour Watch"


def test_each_icon_is_a_square_png_of_its_size(client):
    for size in (180, 192, 512):
        answer = client.get(f"/api/branding/home-icon/{size}")
        assert answer.status_code == 200 and answer.headers["content-type"] == "image/png"
        with Image.open(io.BytesIO(answer.content)) as icon:
            assert icon.size == (size, size)
    assert client.get("/api/branding/home-icon/64").status_code == 404


def test_an_uploaded_icon_is_the_one_on_the_home_screen(client):
    claim(client)
    before = client.get("/api/branding/home-icon/192").content
    mark = io.BytesIO()
    Image.new("RGB", (64, 64), (250, 120, 0)).save(mark, "PNG")
    uploaded = client.put("/api/branding/icon", files={"file": ("icon.png", mark.getvalue(), "image/png")})
    assert uploaded.status_code == 200
    after = client.get("/api/branding/home-icon/192").content
    assert after != before
    with Image.open(io.BytesIO(after)) as icon:
        # The middle is the uploaded orange, not the pin's accent.
        assert icon.convert("RGB").getpixel((96, 96)) == (250, 120, 0)


def test_the_page_points_a_phone_at_them():
    if not INDEX.exists():
        return
    page = INDEX.read_text(encoding="utf-8")
    assert '<link rel="manifest" href="/api/branding/manifest.webmanifest"' in page
    assert '<link rel="apple-touch-icon" href="/api/branding/home-icon/180"' in page

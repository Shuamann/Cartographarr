import struct
import zlib


def png(width: int = 8, height: int = 8) -> bytes:
    """A real, if tiny, PNG. Uploads are checked, so a fake will not do."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"".join(b"\x00" + b"\x22\xd3\xee" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def sign_in(client):
    client.post("/api/auth/claim", json={"username": "admin", "password": "a-long-password"})


def upload(client, kind="logo", content_type="image/png", body=None):
    return client.put(
        f"/api/branding/{kind}",
        files={"file": ("mark.png", body if body is not None else png(), content_type)},
    )


def test_listing_is_readable_without_signing_in(client):
    response = client.get("/api/branding")
    assert response.status_code == 200
    assert response.json()["images"] == {"icon": False, "login_logo": False, "logo": False}


def test_a_stranger_cannot_change_the_branding(client):
    sign_in(client)
    client.post("/api/auth/logout")
    assert upload(client).status_code == 401


def test_admin_can_upload_and_anyone_can_read_it(client):
    sign_in(client)
    assert upload(client).status_code == 200
    assert client.get("/api/branding").json()["images"]["logo"] is True

    # The sign-in page fetches this before there is a session.
    client.post("/api/auth/logout")
    fetched = client.get("/api/branding/logo")
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == "image/png"
    assert fetched.content == png()


def test_only_images_are_accepted(client):
    sign_in(client)
    assert upload(client, content_type="text/plain", body=b"hello").status_code == 400
    assert upload(client, content_type="application/x-sh", body=b"#!/bin/sh").status_code == 400


def test_empty_upload_is_refused(client):
    sign_in(client)
    assert upload(client, body=b"").status_code == 400


def test_unknown_mark_is_refused(client):
    sign_in(client)
    assert upload(client, kind="wallpaper").status_code == 404
    assert client.get("/api/branding/wallpaper").status_code == 404


def test_uploading_twice_replaces_rather_than_accumulates(client):
    sign_in(client)
    upload(client)
    upload(client, body=png(16, 16))
    assert client.get("/api/branding/logo").content == png(16, 16)


def test_removing_a_mark(client):
    sign_in(client)
    upload(client)
    assert client.delete("/api/branding/logo").json()["removed"] is True
    assert client.get("/api/branding/logo").status_code == 404


def test_a_viewer_cannot_change_branding(client):
    sign_in(client)
    client.post(
        "/api/auth/users",
        json={"username": "watcher", "password": "another-long-pass", "role": "viewer"},
    )
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "watcher", "password": "another-long-pass"})

    assert upload(client).status_code == 403
    assert client.get("/api/branding").status_code == 200  # still readable

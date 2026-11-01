"""One colour for the whole app, and nothing else gets into the page."""

from tests.test_auth import claim


def test_a_colour_is_saved_and_read_before_signing_in(client):
    claim(client)
    assert client.put("/api/settings", json={"accent_color": "e5a00d"}).status_code == 200
    # The sign-in page needs it too, so it comes with the branding.
    assert client.get("/api/branding").json()["accent"] == "#e5a00d"

    client.put("/api/settings", json={"accent_color": "#ABC"})
    assert client.get("/api/branding").json()["accent"] == "#aabbcc"

    client.put("/api/settings", json={"accent_color": ""})
    assert client.get("/api/branding").json()["accent"] is None


def test_only_a_colour_gets_through(client):
    """This ends up inside a style the browser applies, so nothing else is worth allowing."""
    claim(client)
    for bad in ("red", "#12345", "javascript:alert(1)", "#22d3ee; background: url(x)"):
        answer = client.put("/api/settings", json={"accent_color": bad})
        assert answer.status_code == 400, bad
    assert client.get("/api/branding").json()["accent"] is None

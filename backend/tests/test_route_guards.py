"""Every route refuses someone who is not signed in, and admin routes refuse
viewers. Enumerated from the app, so a new route is checked without anyone
remembering to add it here."""

import re

from tests.test_auth import claim
from tests.test_privacy import PASSWORD

PUBLIC = {
    ("GET", "/health"),
    ("GET", "/api/auth/state"),
    ("POST", "/api/auth/claim"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    # Signing in with Plex happens before anyone is signed in; off (404) unless switched on.
    ("POST", "/api/auth/plex/start"),
    ("POST", "/api/auth/plex/finish"),
    ("GET", "/api/branding"),
    ("GET", "/api/branding/{kind}"),
    # Trending TMDB art for the sign-in page; nothing about this server.
    ("GET", "/api/auth/backdrops"),
    # Token guarded, off (404) without a token.
    ("GET", "/metrics"),
    ("GET", "/api/summary"),
}


def _routes(app):
    """From the OpenAPI schema, which lists every route in every included
    router. app.routes does not: newer FastAPI groups included routers."""
    for path, methods in app.openapi()["paths"].items():
        for method in methods:
            if method.upper() not in ("HEAD", "OPTIONS"):
                yield method.upper(), path


def _concrete(path):
    return re.sub(r"\{[^}]+\}", "1", path)


def test_nothing_answers_without_signing_in(client):
    import app.main

    claim(client)
    client.post("/api/auth/logout")
    open_routes = []
    checked = list(_routes(app.main.app))
    assert len(checked) > 80, len(checked)
    for method, path in checked:
        if (method, path) in PUBLIC:
            continue
        res = client.request(method, _concrete(path), json={})
        if res.status_code not in (401, 403):
            open_routes.append((method, path, res.status_code))
    assert open_routes == []


def test_viewers_cannot_reach_admin_routes(client):
    import app.main

    claim(client)
    client.post("/api/auth/users", json={"username": "viewer9", "password": PASSWORD, "role": "viewer"})
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "viewer9", "password": PASSWORD})
    admin_prefixes = ("/api/settings", "/api/actions", "/api/rules", "/api/bans", "/api/sharing", "/api/library", "/api/log",
                      "/api/access-review", "/api/auth/users", "/api/sync", "/api/setup/test")
    leaks = []
    tried = 0
    for method, path in _routes(app.main.app):
        if not path.startswith(admin_prefixes):
            continue
        tried += 1
        if method == "GET" and path in ("/api/bans",):
            # Readable by viewers only while privacy is off; covered in test_privacy.
            continue
        res = client.request(method, _concrete(path), json={})
        if res.status_code not in (401, 403):
            leaks.append((method, path, res.status_code))
    assert tried > 30, tried
    assert leaks == []


def test_api_docs_are_not_public(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_cross_site_writes_are_refused(client):
    claim(client)
    res = client.post("/api/bans", json={"machine_id": "x"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert res.status_code == 403
    assert client.get("/api/bans").json() == []
    # The app's own page, and tools that send no such header, still work.
    assert client.post("/api/bans", json={"machine_id": "x"}, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert client.request("DELETE", "/api/bans/x").status_code == 200
    # Reading is unaffected.
    assert client.get("/api/bans", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200



def test_security_headers(client):
    res = client.get("/health")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert res.headers["Referrer-Policy"] == "same-origin"


def test_branding_uploads_are_checked_and_sandboxed(client):
    claim(client)
    fake = client.put("/api/branding/logo", files={"file": ("logo.png", b"<html><script>alert(1)</script>", "image/png")})
    assert fake.status_code == 400
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert client.put("/api/branding/logo", files={"file": ("logo.svg", svg, "image/svg+xml")}).status_code == 200
    served = client.get("/api/branding/logo")
    assert "sandbox" in served.headers["Content-Security-Policy"]
    client.delete("/api/branding/logo")



def test_framing_can_be_allowed_in_settings(client):
    claim(client)
    assert client.get("/health").headers.get("X-Frame-Options") == "SAMEORIGIN"
    client.put("/api/settings", json={"allow_framing": True})
    assert "X-Frame-Options" not in client.get("/health").headers

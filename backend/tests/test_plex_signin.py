"""Sign in with Plex, with plex.tv faked.

Who gets in is the part that matters: a linked account, a matching one, a
new viewer only when allowed and only for someone the server is shared with,
never an admin by default, and nothing without the browser that started it.
"""

from tests.test_auth import claim

PASSWORD = "a-long-enough-password"


def fake_plex(monkeypatch, account, claimed=True):
    from app.auth import plex_signin

    calls = []

    async def request(method, path, token=None, params=None):
        calls.append((method, path, token))
        if method == "POST" and path == "/pins":
            return {"id": 42, "code": "abcd"}
        if path == "/pins/42":
            return {"id": 42, "authToken": "plex-token-xyz" if claimed else None}
        if path == "/user":
            assert token == "plex-token-xyz"
            return account
        raise AssertionError(path)

    monkeypatch.setattr(plex_signin, "plex_request", request)
    return calls


def enable(client, new_viewers=False):
    claim(client)
    client.put("/api/settings", json={"plex_signin_enabled": True, "plex_signin_new_viewers": new_viewers})
    client.post("/api/auth/logout")


def start(client):
    return client.post("/api/auth/plex/start", json={"origin": "http://testserver"}, headers={"Origin": "http://testserver"})


def test_off_by_default(client):
    claim(client)
    assert client.get("/api/auth/state").json()["plex_signin"] is False
    assert client.post("/api/auth/plex/start", json={"origin": "http://testserver"}).status_code == 404


def test_a_linked_account_signs_in_and_the_token_is_not_kept(client, monkeypatch):
    from app.db import session_scope
    from app.models import AppUser

    enable(client)
    calls = fake_plex(monkeypatch, {"id": 777, "username": "Pat", "email": "pat@example.com"})
    with session_scope() as db:
        db.add(AppUser(username="pat-viewer", role="viewer", plex_user_id=777, is_active=True))
    assert client.get("/api/auth/state").json()["plex_signin"] is True

    begun = start(client)
    assert begun.status_code == 200 and begun.json()["url"].startswith("https://app.plex.tv/auth#?")
    assert "forwardUrl=http%3A%2F%2Ftestserver%2F%3Fplex_login%3D1" in begun.json()["url"]
    done = client.post("/api/auth/plex/finish")
    assert done.status_code == 200 and done.json()["user"]["username"] == "pat-viewer"
    assert client.get("/api/auth/state").json()["authenticated"] is True
    # Used once to read the account; nothing about it is stored.
    with session_scope() as db:
        assert "plex-token-xyz" not in str([r.__dict__ for r in db.query(AppUser).all()])
    assert [c[1] for c in calls] == ["/pins", "/pins/42", "/user"]
    # The same state cannot be used again.
    assert client.post("/api/auth/plex/finish").status_code == 400


def test_email_matches_viewers_only_and_usernames_never(client, monkeypatch):
    from app.db import session_scope
    from app.models import AppUser

    enable(client)
    with session_scope() as db:
        db.query(AppUser).filter(AppUser.username == "admin").update({"email": "admin@example.com"})
        db.add(AppUser(username="sam", role="viewer", email="sam@example.com", is_active=True))

    # A Plex account named "admin", or with the admin's email, is not the admin.
    fake_plex(monkeypatch, {"id": 555, "username": "admin", "email": "Admin@Example.com"})
    start(client)
    assert client.post("/api/auth/plex/finish").status_code == 403

    fake_plex(monkeypatch, {"id": 556, "username": "sammy", "email": "SAM@example.com"})
    start(client)
    assert client.post("/api/auth/plex/finish").json()["user"]["username"] == "sam"
    with session_scope() as db:
        assert db.query(AppUser).filter(AppUser.username == "sam").one().plex_user_id == 556


def test_an_admin_linked_explicitly_can_use_plex(client, monkeypatch):
    from app.db import session_scope
    from app.models import AppUser

    enable(client)
    with session_scope() as db:
        db.query(AppUser).filter(AppUser.username == "admin").update({"plex_user_id": 42424})
    fake_plex(monkeypatch, {"id": 42424, "username": "owner", "email": "owner@example.com"})
    start(client)
    assert client.post("/api/auth/plex/finish").json()["user"]["role"] == "admin"


def test_strangers_are_refused_and_new_viewers_only_when_allowed(client, monkeypatch):
    from app.db import session_scope
    from app.models import AppUser, User

    enable(client)
    fake_plex(monkeypatch, {"id": 900, "username": "friend", "email": "friend@example.com"})
    with session_scope() as db:
        db.add(User(user_id=900, username="friend"))
    start(client)
    refused = client.post("/api/auth/plex/finish")
    assert refused.status_code == 403 and "no Cartographarr account" in refused.json()["detail"]

    claim(client)  # already claimed; signs admin back in is not needed, use login
    client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    client.put("/api/settings", json={"plex_signin_new_viewers": True})
    client.post("/api/auth/logout")
    start(client)
    created = client.post("/api/auth/plex/finish").json()["user"]
    assert created["username"] == "friend" and created["role"] == "viewer"
    # Anonymised for them even though the server-wide setting shows everything.
    assert created["privacy"] == "anonymised"
    assert client.get("/api/auth/state").json()["privacy"]["mode"] == "anonymised"

    # Someone Tautulli does not list as having access still gets nothing.
    client.post("/api/auth/logout")
    fake_plex(monkeypatch, {"id": 901, "username": "outsider", "email": "o@example.com"})
    start(client)
    assert client.post("/api/auth/plex/finish").status_code == 403
    with session_scope() as db:
        assert db.query(AppUser).filter(AppUser.username == "outsider").count() == 0


def test_finishing_before_plex_confirms_or_from_another_browser(client, monkeypatch):
    enable(client)
    fake_plex(monkeypatch, {"id": 1, "username": "x"}, claimed=False)
    start(client)
    assert client.post("/api/auth/plex/finish").status_code == 409
    client.cookies.clear()
    assert client.post("/api/auth/plex/finish").status_code == 400


def test_the_return_address_must_be_this_app(client, monkeypatch):
    enable(client)
    fake_plex(monkeypatch, {"id": 1})
    evil = client.post("/api/auth/plex/start", json={"origin": "https://evil.example"}, headers={"Origin": "http://testserver"})
    assert evil.status_code == 400
    assert client.post("/api/auth/plex/start", json={"origin": "javascript:alert(1)"}).status_code == 400
    assert client.post("/api/auth/plex/start", json={"origin": "http://testserver/path?x=1"}).status_code == 400

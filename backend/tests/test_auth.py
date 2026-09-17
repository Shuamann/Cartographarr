"""Auth.

The cases that matter are the refusals: unauthenticated requests, a viewer
reaching for admin actions, and a spoofed proxy header from an untrusted
address. Getting those wrong exposes every user's IP and viewing history.
"""

def claim(client, username="admin", password="a-long-enough-password"):
    return client.post(
        "/api/auth/claim", json={"username": username, "password": password}
    )


def test_fresh_install_wants_a_claim(client):
    state = client.get("/api/auth/state").json()
    assert state["needs_claim"] is True
    assert state["authenticated"] is False


def test_reads_are_refused_before_signing_in(client):
    assert client.get("/api/history").status_code == 401
    assert client.get("/api/map/points").status_code == 401
    assert client.get("/api/dashboard").status_code == 401


def test_claim_creates_an_admin_and_signs_in(client):
    assert claim(client).status_code == 200
    state = client.get("/api/auth/state").json()
    assert state["needs_claim"] is False
    assert state["authenticated"] is True
    assert state["user"]["role"] == "admin"
    assert client.get("/api/history").status_code == 200


def test_claim_closes_once_taken(client):
    claim(client)
    second = claim(client, username="intruder")
    assert second.status_code == 409


def test_short_passwords_are_refused(client):
    assert claim(client, password="short").status_code == 400


def test_login_is_vague_about_why_it_failed(client):
    claim(client)
    client.post("/api/auth/logout")
    wrong_user = client.post("/api/auth/login", json={"username": "nobody", "password": "x" * 12})
    wrong_pass = client.post("/api/auth/login", json={"username": "admin", "password": "x" * 12})
    assert wrong_user.status_code == wrong_pass.status_code == 401
    assert wrong_user.json()["detail"] == wrong_pass.json()["detail"]


def test_logout_ends_the_session(client):
    claim(client)
    assert client.get("/api/history").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/history").status_code == 401


def test_viewer_cannot_reach_admin_actions(client):
    claim(client)
    client.post(
        "/api/auth/users",
        json={"username": "watcher", "password": "another-long-password", "role": "viewer"},
    )
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login", json={"username": "watcher", "password": "another-long-password"}
    )

    assert client.get("/api/history").status_code == 200  # viewers can read
    assert client.get("/api/settings").status_code == 403
    assert client.post("/api/rules", json={"name": "x", "match_player": "y"}).status_code == 403
    assert client.post("/api/activity/1/terminate", json={"message": "no"}).status_code == 403
    assert client.get("/api/auth/users").status_code == 403


def test_proxy_header_is_ignored_while_proxy_auth_is_off(client):
    claim(client)
    client.post("/api/auth/logout")
    # Default config trusts nothing, so the header must not authenticate.
    response = client.get("/api/history", headers={"X-Forwarded-User": "admin"})
    assert response.status_code == 401


def test_proxy_header_is_ignored_from_an_untrusted_address(client, monkeypatch):
    claim(client)
    client.post("/api/auth/logout")

    from app import settings_store

    settings = settings_store.current().model_copy(
        update={"auth_proxy_enabled": True, "trusted_proxy_ips": ["10.9.9.9"]}
    )
    monkeypatch.setattr(settings_store, "_cache", (settings, frozenset()))

    # TestClient presents as 127.0.0.1, which is not in the trusted list.
    response = client.get("/api/history", headers={"X-Forwarded-User": "admin"})
    assert response.status_code == 401


def test_proxy_header_works_from_a_trusted_address(client, monkeypatch):
    claim(client)
    client.post("/api/auth/logout")

    from app import settings_store

    settings = settings_store.current().model_copy(
        update={"auth_proxy_enabled": True, "trusted_proxy_ips": ["127.0.0.0/8"]}
    )
    monkeypatch.setattr(settings_store, "_cache", (settings, frozenset()))

    response = client.get("/api/history", headers={"X-Forwarded-User": "someone-new"})
    assert response.status_code == 200
    # Provisioned at the default role, which is viewer, not admin.
    assert client.get("/api/settings", headers={"X-Forwarded-User": "someone-new"}).status_code == 403


def test_last_admin_cannot_be_demoted(client):
    claim(client)
    me = client.get("/api/auth/me").json()
    response = client.put(f"/api/auth/users/{me['id']}", json={"role": "viewer"})
    assert response.status_code == 400
    assert "admin" in response.json()["detail"].lower()



def test_repeated_failed_sign_ins_are_locked_out(client):
    from app.auth.security import login_throttle

    login_throttle._failures.clear()
    claim(client)
    client.post("/api/auth/logout")
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong-password-x"}).status_code == 401
    locked = client.post("/api/auth/login", json={"username": "admin", "password": "a-long-enough-password"})
    assert locked.status_code == 429 and "Retry-After" in locked.headers
    # Another username from the same address is not locked by those five.
    assert client.post("/api/auth/login", json={"username": "someone", "password": "whatever-it-is"}).status_code == 401
    login_throttle._failures.clear()
    assert client.post("/api/auth/login", json={"username": "admin", "password": "a-long-enough-password"}).status_code == 200


def test_the_throttle_window_moves_on():
    from app.auth.security import LoginThrottle

    t = LoginThrottle()
    for i in range(5):
        t.failed("pat", "10.0.0.1", 1000.0 + i)
    assert t.blocked("pat", "10.0.0.1", 1010.0) > 0
    assert t.blocked("pat", "10.0.0.1", 1000.0 + 15 * 60 + 5) == 0
    for i in range(30):
        t.failed(f"user{i}", "10.0.0.9", 2000.0)
    assert t.blocked("fresh", "10.0.0.9", 2001.0) > 0

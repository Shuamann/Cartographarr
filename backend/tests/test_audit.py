import json

from tests.test_auth import claim


def test_changing_a_secret_logs_that_it_changed_not_the_value(client):
    claim(client)
    secret = "super-secret-radarr-key-123"
    response = client.put(
        "/api/settings", json={"radarr_url": "http://radarr.invalid:7878", "radarr_api_key": secret}
    )
    assert response.status_code == 200

    log = client.get("/api/log?kind=changes").json()
    entry = next(e for e in log if e["action"] == "settings.save")

    assert secret not in json.dumps(log)
    detail = json.loads(entry["payload"])
    assert detail["radarr_api_key"] == {"changed": True}
    assert detail["radarr_url"]["after"] == "http://radarr.invalid:7878"
    assert entry["actor"] == "admin"


def test_failed_sign_in_is_logged_without_the_password(client):
    claim(client)
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "admin", "password": "wrong-password-typed"})
    client.post("/api/auth/login", json={"username": "admin", "password": "a-long-enough-password"})

    log = client.get("/api/log?kind=changes").json()
    actions = [e["action"] for e in log]
    assert "auth.failed" in actions
    assert "auth.login" in actions
    assert "wrong-password-typed" not in json.dumps(log)


def test_viewers_cannot_read_the_log(client):
    claim(client)
    client.post(
        "/api/auth/users",
        json={"username": "viewer", "password": "a-long-enough-password", "role": "viewer"},
    )
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "viewer", "password": "a-long-enough-password"})
    assert client.get("/api/log").status_code == 403


def test_restore_in_tautulli_refuses_what_it_cannot_do(client):
    from app.db import session_scope
    from app.models import User

    claim(client)
    with session_scope() as db:
        db.add(User(user_id=1, username="present", deleted_in_tautulli=False))
        db.add(User(user_id=2, username=None, deleted_in_tautulli=True))

    assert client.post("/api/users/999/restore-in-tautulli").status_code == 404
    # Not marked deleted, so there is nothing to restore.
    assert client.post("/api/users/1/restore-in-tautulli").status_code == 409
    # Tautulli has no record of them at all, so there is no name to restore with.
    assert client.post("/api/users/2/restore-in-tautulli").status_code == 409


def test_users_list_keeps_accounts_tautulli_forgot(client):
    from app.db import session_scope
    from app.models import History, User

    claim(client)
    with session_scope() as db:
        db.add(User(user_id=2, username=None, deleted_in_tautulli=True))
        db.add(History(row_id=1, user_id=2, started=1700000000))
    users = client.get("/api/users").json()
    forgotten = next(u for u in users if u["user_id"] == 2)
    assert forgotten["plays"] == 1
    assert forgotten["last_seen"] == 1700000000

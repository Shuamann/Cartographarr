"""The audit log.

What matters is what it refuses to keep: a secret typed into Settings must
never end up readable in the log, which admins can browse and which outlives
the setting itself.
"""

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

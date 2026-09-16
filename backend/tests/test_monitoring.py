"""Metrics and the dashboard summary: off without a token, refused with a
wrong one, and never carrying anything that names a person."""

from tests.test_auth import claim


def test_off_until_a_token_is_set_and_then_required(client):
    claim(client)
    assert client.get("/metrics").status_code == 404
    assert client.get("/api/summary").status_code == 404

    client.put("/api/settings", json={"metrics_token": "scrape-me-please"})
    client.post("/api/auth/logout")

    assert client.get("/metrics").status_code == 401
    assert client.get("/api/summary?token=nope").status_code == 401

    text = client.get("/metrics", headers={"Authorization": "Bearer scrape-me-please"})
    assert text.status_code == 200
    assert "cartographarr_plays_total" in text.text and "cartographarr_streams " in text.text

    summary = client.get("/api/summary?token=scrape-me-please").json()
    assert {"streams", "plays", "users", "devices_unreviewed", "signals_open"} <= set(summary)


def test_nothing_identifying_leaks(client):
    from app.db import session_scope
    from app.models import History, User

    claim(client)
    with session_scope() as db:
        db.add(User(user_id=1, username="secret-person", email="secret@example.com"))
        db.add(History(row_id=1, user_id=1, ip_address="203.0.113.99", full_title="Secret Film", started=1))
    client.put("/api/settings", json={"metrics_token": "scrape-me-please"})
    body = client.get("/metrics?token=scrape-me-please").text + client.get("/api/summary?token=scrape-me-please").text
    for needle in ("secret-person", "secret@example.com", "203.0.113.99", "Secret Film"):
        assert needle not in body

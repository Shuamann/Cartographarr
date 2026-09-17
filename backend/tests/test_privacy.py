"""Viewer privacy.

A viewer in a private mode must not be able to reach other people's details
through any endpoint, including by passing another user's id straight to
the API. Admins always see everything.
"""

from tests.test_auth import claim

PASSWORD = "a-long-enough-password"


def seed():
    from app.db import session_scope
    from app.models import Device, History, IpLocation, TravelFlag, User

    with session_scope() as db:
        db.add(User(user_id=7, username="viewer7", email="seven@example.com"))
        db.add(User(user_id=8, username="someone8", email="eight@example.com"))
        db.add(IpLocation(ip="203.0.113.7", city="Springfield", lat=39.8, lon=-89.6))
        db.add(IpLocation(ip="203.0.113.8", city="Shelbyville", lat=39.4, lon=-88.8))
        db.add(History(row_id=1, user_id=7, machine_id="dev-7", ip_address="203.0.113.7", started=1000, full_title="Mine"))
        db.add(History(row_id=2, user_id=8, machine_id="dev-8", ip_address="203.0.113.8", started=2000, full_title="Theirs"))
        db.add(History(row_id=3, user_id=8, machine_id="dev-8", ip_address="203.0.113.7", started=3000, full_title="Theirs too"))
        db.add(Device(machine_id="dev-7", user_id=7, player="My TV", play_count=1))
        db.add(Device(machine_id="dev-8", user_id=8, player="Their TV", play_count=2))
        db.add(TravelFlag(user_id=8, from_history_id=2, to_history_id=3, status="new"))


def as_viewer(client, mode, username="viewer7"):
    claim(client)
    seed()
    assert client.put("/api/settings", json={"viewer_privacy": mode}).status_code == 200
    client.post("/api/auth/users", json={"username": username, "password": PASSWORD, "role": "viewer"})
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": username, "password": PASSWORD})


def test_own_mode_shows_only_the_viewer(client):
    as_viewer(client, "own")
    assert [u["user_id"] for u in client.get("/api/users").json()] == [7]
    assert client.get("/api/users/8").status_code == 403
    assert client.get("/api/history").json()["total"] == 1
    # Asking for someone else by id still returns only your own.
    assert client.get("/api/history?user_id=8").json()["total"] == 1
    assert [d["machine_id"] for d in client.get("/api/devices").json()] == ["dev-7"]
    assert client.get("/api/devices/dev-8").status_code == 403
    assert client.get("/api/addresses/203.0.113.8").status_code == 403
    assert client.get("/api/history/2").status_code == 403
    assert client.get("/api/travel-flags").json() == []
    for admin_only in ("/api/rules", "/api/bans", "/api/enforcement-log", "/api/rules/fields", "/api/signal-ignores"):
        assert client.get(admin_only).status_code == 403, admin_only
    detail = client.get("/api/location?lat=39.8&lon=-89.6").json()
    assert detail["plays"] == 1 and [u["user_id"] for u in detail["users"]] == [7]
    assert client.get("/api/auth/state").json()["privacy"] == {"mode": "own", "plex_user_id": 7, "linked": True}


def test_anonymised_mode_keeps_totals_but_hides_other_people(client):
    as_viewer(client, "anonymised")
    page = client.get("/api/history").json()
    assert page["total"] == 3
    theirs = [r for r in page["items"] if r.get("anonymised")]
    assert len(theirs) == 2
    assert all(r["user_id"] is None and r["full_title"] is None and r["ip_address"] is None and r["machine_id"] is None for r in theirs)
    mine = [r for r in page["items"] if not r.get("anonymised")]
    assert mine[0]["full_title"] == "Mine"
    # Filtering by someone else would single them out, so it is not allowed to.
    assert client.get("/api/history?user_id=8").json()["total"] == 1
    assert [u["user_id"] for u in client.get("/api/users").json()] == [7]
    detail = client.get("/api/location?lat=39.8&lon=-89.6").json()
    assert detail["plays"] == 2
    assert [u["user_id"] for u in detail["users"]] == [7]
    assert detail["other_viewers_plays"] == 1
    assert [a["ip_address"] for a in detail["addresses"]] == ["203.0.113.7"]


def test_an_unlinked_viewer_sees_no_personal_data(client):
    as_viewer(client, "own", username="stranger")
    assert client.get("/api/users").json() == []
    assert client.get("/api/history").json()["total"] == 0
    assert client.get("/api/auth/state").json()["privacy"]["linked"] is False


def test_admins_always_see_everything(client):
    claim(client)
    seed()
    client.put("/api/settings", json={"viewer_privacy": "own"})
    assert client.get("/api/history").json()["total"] == 3
    assert len(client.get("/api/users").json()) == 2
    assert client.get("/api/users/8").status_code == 200



def test_an_account_can_override_the_server_setting(client):
    from app.db import session_scope
    from app.models import AppUser

    as_viewer(client, "all")
    assert len(client.get("/api/history").json()["items"]) == 3
    with session_scope() as db:
        db.query(AppUser).filter(AppUser.username == "viewer7").update({"privacy": "own"})
    items = client.get("/api/history").json()["items"]
    assert [i["user_id"] for i in items] == [7]
    assert client.put("/api/auth/users/1", json={"privacy": "nonsense"}).status_code in (400, 403)

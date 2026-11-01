from tests.test_auth import claim

SHARED = """<?xml version="1.0" encoding="UTF-8"?>
<MediaContainer friendlyName="myPlex" identifier="com.plexapp.plugins.myplex" machineIdentifier="abc" size="2">
  <SharedServer id="1" username="alice" email="alice@example.com" userID="11" accessToken="x" name="Server" acceptedAt="1" invitedAt="1">
    <Section id="1" key="1" title="Movies" type="movie" shared="1"/>
    <Section id="2" key="2" title="TV Shows" type="show" shared="0"/>
  </SharedServer>
  <SharedServer id="2" username="bob" email="bob@example.com" userID="12" accessToken="y" name="Server">
    <Section id="1" key="1" title="Movies" type="movie" shared="1"/>
    <Section id="2" key="2" title="TV Shows" type="show" shared="1"/>
  </SharedServer>
</MediaContainer>"""


def test_shared_servers_are_read_in_one_document():
    from app.plex.sharing import parse_shared_servers

    shares = parse_shared_servers(SHARED)
    assert [(s["username"], s["id"], s["sections"]) for s in shares] == [
        ("alice", 11, ["Movies"]),
        ("bob", 12, ["Movies", "TV Shows"]),
    ]


def test_list_is_cached_and_changes_are_logged(client, monkeypatch):
    from app.plex import sharing

    claim(client)
    calls = {"list": 0}
    monkeypatch.setattr(sharing, "configured", lambda: True)

    def fake_list():
        calls["list"] += 1
        return [{"id": 11, "username": "alice", "email": None, "thumb": None, "home": False, "sections": ["Movies"]}]

    monkeypatch.setattr(sharing, "list_shares", fake_list)
    monkeypatch.setattr(sharing, "all_sections", lambda: ["Movies", "TV Shows"])
    monkeypatch.setattr(sharing, "set_sections", lambda u, s: {"username": u, "sections": s})
    monkeypatch.setattr(sharing, "unshare", lambda u: {"username": u, "removed": True})

    first = client.get("/api/sharing").json()
    assert first["users"][0]["username"] == "alice" and first["sections"] == ["Movies", "TV Shows"]
    client.get("/api/sharing")
    assert calls["list"] == 1  # the second read came from the cache

    # This crashed before: a route named audit hid the audit module.
    res = client.put("/api/sharing/alice/sections", json={"sections": ["Movies", "TV Shows"]})
    assert res.status_code == 200, res.text
    assert client.request("DELETE", "/api/sharing/alice", json={"confirm": "alice"}).status_code == 200
    actions = [e["action"] for e in client.get("/api/log?kind=changes").json()]
    assert "sharing.sections" in actions and "sharing.unshare" in actions
    assert client.get("/api/sharing/audit").status_code == 200


def test_a_slow_plex_is_an_error_not_a_hang(client, monkeypatch):
    import asyncio

    from app.plex import sharing
    from app.routers import sharing as route

    claim(client)
    monkeypatch.setattr(sharing, "configured", lambda: True)
    route._forget()

    async def never(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", never)
    res = client.get("/api/sharing?fresh=true")
    assert res.status_code == 504 and "45 seconds" in res.json()["detail"]


# ---- routes that keep coming back --------------------------------------------

_rows = iter(range(1000, 9999))


def _flag(db, user_id, a, b, when, kind="travel"):
    from app.models import TravelFlag

    row = TravelFlag(user_id=user_id, kind=kind, from_city=a, to_city=b, from_ip="1.1.1.1", to_ip="2.2.2.2",
                     from_history_id=next(_rows), to_history_id=next(_rows),
                     from_started=when, to_started=when + 600, km=700, hours=0.2, kmh=3500,
                     hosting_involved=False, status="new")
    db.add(row)
    db.flush()
    return row.id


def test_a_route_that_keeps_repeating_is_counted(client):
    """A phone on a mobile network lands in a different city every evening."""
    from datetime import UTC, datetime

    from app.db import session_scope

    claim(client)
    now = int(datetime.now(UTC).timestamp())
    with session_scope() as db:
        for n in range(4):
            _flag(db, 7, "Topeka", "Chicago", now - n * 86400)
        # The same route the other way round is the same route.
        _flag(db, 7, "Chicago", "Topeka", now - 5 * 86400)
        # A different account's identical route is counted separately.
        _flag(db, 8, "Topeka", "Chicago", now - 86400)
        # And a one off stays a one off.
        _flag(db, 7, "Topeka", "Berlin", now - 7 * 86400)

    rows = client.get("/api/travel-flags").json()
    by_route = {(r["user_id"], r["from_city"], r["to_city"]): r["times_seen"] for r in rows}
    assert by_route[(7, "Topeka", "Chicago")] == 5
    assert by_route[(7, "Chicago", "Topeka")] == 5
    assert by_route[(8, "Topeka", "Chicago")] == 1
    assert by_route[(7, "Topeka", "Berlin")] == 1

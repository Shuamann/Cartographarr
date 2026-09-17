"""Sharing, without touching a real Plex account.

Plex calls are replaced; what is tested is the part that is ours: reading
plex.tv's answer, not hanging, and writing every change to the Log.
"""

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

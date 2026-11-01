import asyncio

from tests.test_auth import claim

TOKEN = "linked-token-value"


def no_tautulli(monkeypatch):
    """The fixture supplies Tautulli through the environment, as most tests want."""
    from app import settings_store

    monkeypatch.delenv("TAUTULLI_URL", raising=False)
    monkeypatch.delenv("TAUTULLI_API_KEY", raising=False)
    settings_store.invalidate()


class FakePin:

    entered = False
    made: list = []

    def __init__(self, headers=None, **_):
        self.headers = headers
        self.token = None
        self.expired = False
        FakePin.made.append(self)

    @property
    def pin(self):
        return "AB12"

    def checkLogin(self):
        if FakePin.entered:
            self.token = TOKEN
            return True
        return False


def fake_plex(monkeypatch):
    """A Plex server that answers at the address it is given."""
    from app.plex import server as plex_server

    FakePin.entered, FakePin.made = False, []
    monkeypatch.setattr("plexapi.myplex.MyPlexPinLogin", FakePin)
    monkeypatch.setattr(
        plex_server, "reachable",
        lambda url=None: {"ok": True, "name": "Home", "version": "1.40", "machine_identifier": "abc123", "ms": 180},
    )


def link_plex(client):
    """The whole of the Plex half of setup, as the page does it."""
    started = client.post("/api/setup/plex/link")
    assert started.status_code == 200
    body = started.json()
    assert body["code"] == "AB12" and body["url"] == "https://plex.tv/link"

    # Nobody has typed it in yet.
    assert client.post(f"/api/setup/plex/link/{body['id']}").json() == {"linked": False}
    FakePin.entered = True
    done = client.post(f"/api/setup/plex/link/{body['id']}")
    assert done.json() == {"linked": True}
    # The token is kept on the server and never sent back to the page.
    assert TOKEN not in done.text

    used = client.post("/api/setup/plex/use", json={"plex_url": "http://plex.example.test:32400/"})
    assert used.status_code == 200, used.text
    return used.json()


def test_a_fresh_install_with_nothing_set_reaches_the_app_through_plex(client, monkeypatch):
    from app import main, settings_store, tasks

    no_tautulli(monkeypatch)
    fake_plex(monkeypatch)
    claim(client)

    status = client.get("/api/setup").json()
    assert status["configured"] is False and status["plex"] is False and status["tautulli"] is False

    used = link_plex(client)
    assert used["name"] == "Home" and used["kept_by_environment"] == {}

    status = client.get("/api/setup").json()
    assert status["configured"] is True and status["missing"] == [] and status["tautulli"] is False

    settings = settings_store.current()
    assert settings.plex_token == TOKEN
    assert settings.plex_url == "http://plex.example.test:32400"
    assert (settings.activity_source, settings.library_source) == ("plex", "plex")
    assert settings.plex_machine_identifier == "abc123"
    # The settings page shows that a token is set, not what it is.
    shown = {row["key"]: row["value"] for row in client.get("/api/settings").json()}
    assert shown["plex_token"] != TOKEN and TOKEN not in client.get("/api/settings").text

    # The people list and the libraries come from Plex, which is where they
    from app.plex import people as plex_people

    monkeypatch.setattr(plex_people, "read", lambda machine_identifier=None: [
        {"user_id": 7, "username": "owner", "friendly_name": "Owner", "email": "o@example.test",
         "thumb": None, "is_active": True, "is_home_user": True, "deleted_in_tautulli": False,
         "shared_libraries": "[]", "allow_sync": None},
        {"user_id": 9, "username": "guest", "friendly_name": "A Guest", "email": "g@example.test",
         "thumb": None, "is_active": True, "is_home_user": False, "deleted_in_tautulli": False,
         "shared_libraries": "[\"1\"]", "allow_sync": None},
    ])
    monkeypatch.setattr(plex_people, "libraries", lambda: [{"section_id": 1, "name": "Films", "type": "movie"}])
    assert asyncio.run(main._slow_cycle()) == {"users": 2, "libraries": 1}
    names = {u["user_id"]: u["friendly_name"] for u in client.get("/api/users").json()}
    assert names == {7: "Owner", 9: "A Guest"}
    # The history sync still runs: plays are recorded from Plex as they
    # finish, and devices and places are built from them.
    assert asyncio.run(main._cycle())["history"] == 0
    assert client.post("/api/sync/run").status_code == 200


def test_a_plex_install_scans_reads_tracks_and_watches_without_tautulli(client, monkeypatch):
    from app import main
    from app.plex import activity as plex_activity
    from app.services import enforcer, library_scan

    no_tautulli(monkeypatch)
    fake_plex(monkeypatch)
    claim(client)
    link_plex(client)

    def no_client(*_a, **_k):
        raise AssertionError("built a Tautulli client")

    monkeypatch.setattr(main, "TautulliClient", no_client)
    seen = {}

    async def scan(client_given):
        seen["scan"] = client_given
        return {"movies": 0}

    async def details(client_given):
        seen["details"] = client_given
        return {"read": 0, "left": 0}

    monkeypatch.setattr(library_scan, "scan", scan)
    monkeypatch.setattr(library_scan, "read_details", details)
    asyncio.run(main._library_scan())
    asyncio.run(main._file_details())
    assert seen == {"scan": None, "details": None}

    monkeypatch.setattr(plex_activity, "read", lambda: {"sessions": [], "stream_count": 0})
    assert "checked" in asyncio.run(enforcer.run_once())
    live = client.get("/api/activity").json()
    assert live.get("error") is None and live["sessions"] == []


def test_a_mistyped_token_is_refused_and_not_kept(client, monkeypatch):
    from app import settings_store

    no_tautulli(monkeypatch)
    claim(client)

    def refuse(token=None, **_):
        raise ValueError("(401) unauthorized")

    monkeypatch.setattr("plexapi.myplex.MyPlexAccount", refuse)
    answer = client.post("/api/setup/plex/token", json={"plex_token": "nope"})
    assert answer.status_code == 400 and settings_store.current().plex_token == ""

    monkeypatch.setattr("plexapi.myplex.MyPlexAccount", lambda token=None, **_: object())
    assert client.post("/api/setup/plex/token", json={"plex_token": " pasted "}).status_code == 200
    assert settings_store.current().plex_token == "pasted"


def test_an_old_or_unknown_code_asks_for_a_new_one(client, monkeypatch):
    no_tautulli(monkeypatch)
    fake_plex(monkeypatch)
    claim(client)
    assert client.post("/api/setup/plex/link/not-a-code").status_code == 410


def test_an_address_that_does_not_answer_is_not_kept(client, monkeypatch):
    from app import settings_store
    from app.plex import server as plex_server

    no_tautulli(monkeypatch)
    claim(client)
    monkeypatch.setattr(plex_server, "reachable", lambda url=None: {"ok": False, "error": "timed out"})
    answer = client.post("/api/setup/plex/use", json={"plex_url": "http://10.0.0.9:32400"})
    assert answer.status_code == 502 and "timed out" in answer.json()["detail"]
    assert settings_store.current().plex_url == "" and client.get("/api/setup").json()["configured"] is False


def test_setup_is_only_for_an_admin(client, monkeypatch):
    from tests.test_privacy import as_viewer

    as_viewer(client, "all")
    for path in ("/api/setup/plex/link", "/api/setup/plex/use", "/api/setup/plex/token"):
        assert client.post(path, json={"plex_url": "x", "plex_token": "x"}).status_code == 403, path


def test_tautulli_from_the_environment_is_configured_and_stays_locked(client, monkeypatch):
    from app import settings_store

    fake_plex(monkeypatch)
    claim(client)
    status = client.get("/api/setup").json()
    assert status["configured"] is True and status["tautulli"] is True
    assert {"tautulli_url", "tautulli_api_key"} <= set(status["locked"])

    link_plex(client)
    settings = settings_store.current()
    assert settings.tautulli_url == "http://tautulli.invalid:8181" and settings.activity_source == "plex"


def test_half_of_tautulli_locked_still_lets_plex_finish_setup(client, monkeypatch):
    """The environment set Tautulli's address and not its key."""
    from app import settings_store

    monkeypatch.delenv("TAUTULLI_API_KEY", raising=False)
    settings_store.invalidate()
    fake_plex(monkeypatch)
    claim(client)
    status = client.get("/api/setup").json()
    assert status["configured"] is False and "tautulli_url" in status["locked"]

    link_plex(client)
    assert client.get("/api/setup").json()["configured"] is True


def test_a_plex_source_left_half_finished_does_not_send_a_working_install_back_to_setup(client, monkeypatch):
    from app import settings_store

    no_tautulli(monkeypatch)
    claim(client)
    settings_store.save({"tautulli_url": "http://tautulli.example.test", "tautulli_api_key": "k", "activity_source": "plex"})
    status = client.get("/api/setup").json()
    assert status["configured"] is True and status["missing"] == []


def test_an_install_already_on_plex_stays_out_of_setup(client, monkeypatch):
    from app import settings_store

    no_tautulli(monkeypatch)
    claim(client)
    settings_store.save({"plex_token": "t", "plex_url": "http://plex.example.test:32400",
                         "activity_source": "plex", "library_source": "plex"})
    assert client.get("/api/setup").json()["configured"] is True


def test_a_plex_install_stops_streams_through_plex(client, monkeypatch):
    """A ban that cannot stop anything is worse than no ban."""
    from app.actions import registry
    from app.plex import control
    from app.services import capabilities

    no_tautulli(monkeypatch)
    fake_plex(monkeypatch)
    claim(client)
    link_plex(client)

    monkeypatch.setattr(control, "describe", lambda: {"plex_pass": True, "server_name": "Home",
                                                      "server_version": "1.40", "machine_identifier": "abc123"})
    probed = asyncio.run(capabilities.refresh())
    assert probed["plex_pass"] is True and probed["error"] is None

    stopped = []
    monkeypatch.setattr(control, "stop", lambda key, sid, message: stopped.append((key, sid, message)))
    action = registry.get("terminate")
    assert asyncio.run(action.execute({"session_key": "42", "session_id": "s1"}, {"message": "No"})) == "terminated"
    assert stopped == [("42", "s1", "No")]


def test_a_plex_install_gets_its_artwork_from_plex(client, monkeypatch):
    import httpx

    from app.routers import data

    no_tautulli(monkeypatch)
    fake_plex(monkeypatch)
    claim(client)
    link_plex(client)

    asked = []

    class Upstream:
        content = b"jpeg"
        headers = {"content-type": "image/jpeg"}

        def raise_for_status(self):
            return None

    async def get(url, params=None, headers=None):
        asked.append((url, params, headers))
        return Upstream()

    fake = httpx.AsyncClient()
    monkeypatch.setattr(fake, "get", get)
    monkeypatch.setattr(data, "_image_client", lambda settings: fake)
    answer = client.get("/api/media/4101/image?width=92&height=138")
    assert answer.status_code == 200 and answer.content == b"jpeg"
    url, params, headers = asked[0]
    assert url == "http://plex.example.test:32400/photo/:/transcode"
    assert params["url"] == "/library/metadata/4101/thumb" and TOKEN not in str(params)
    assert headers["X-Plex-Token"] == TOKEN

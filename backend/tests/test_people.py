"""User and device profiles.

The user profile shipped referring to a history column that does not exist,
so every click on a user failed and nothing on the page said so.
"""

from tests.test_auth import claim


def seed():
    from app.db import session_scope
    from app.models import Device, History, IpLocation, MediaItem, TravelFlag, User

    with session_scope() as db:
        db.add(User(user_id=7, username="viewer7", deleted_in_tautulli=False))
        db.add(User(user_id=8, username="viewer8", deleted_in_tautulli=False))
        db.add(MediaItem(rating_key=100, title="A Show", media_type="show"))
        db.add(IpLocation(ip="203.0.113.9", city="Springfield", country="US", is_hosting=False))
        for row, user in ((1, 7), (2, 7), (3, 8)):
            db.add(
                History(
                    row_id=row, user_id=user, machine_id="dev-1", ip_address="203.0.113.9",
                    started=1700000000 + row, play_duration=600, media_type="episode",
                    rating_key=200 + row, grandparent_rating_key=100, full_title="A Show - Pilot",
                )
            )
        db.add(Device(machine_id="dev-1", user_id=7, player="Living Room", play_count=2, is_new_unreviewed=True))
        db.add(Device(machine_id="dev-1", user_id=8, player="Living Room", play_count=1, is_new_unreviewed=False))
        db.add(TravelFlag(user_id=7, from_history_id=1, to_history_id=2, kind="travel", to_started=1700000100, status="new"))


def test_user_profile_loads(client):
    claim(client)
    seed()
    response = client.get("/api/users/7")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["totals"]["plays"] == 2
    # Grouped by show and named from the cached show, not the episode.
    assert body["top_media"][0]["title"] == "A Show"
    assert body["places"][0]["city"] == "Springfield"


def test_device_profile_lists_every_account_on_it(client):
    claim(client)
    seed()
    body = client.get("/api/devices/dev-1").json()
    assert {o["user_id"] for o in body["owners"]} == {7, 8}
    assert body["totals"]["plays"] == 3
    assert body["is_new_unreviewed"] is True


def test_activity_keeps_its_own_kind(client):
    claim(client)
    seed()
    events = client.get("/api/people/activity?user_id=7").json()
    signal = next(e for e in events if e["kind"] == "signal")
    # The flag's own kind must not overwrite the event kind.
    assert signal["signal_kind"] == "travel"


def test_episode_links_point_at_the_show(client):
    """Plex gives an episode its own TMDB id. A show link built from it opens
    some other show, or Not Found, so episodes link using the show's ids."""
    from app.db import session_scope
    from app.models import MediaItem

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=500, title="The Show", media_type="show", tmdb_id="2316"))
        db.add(
            MediaItem(
                rating_key=501, title="Pilot", media_type="episode", grandparent_rating_key=500,
                tmdb_id="170315", imdb_id="tt0000001",
            )
        )
        db.add(MediaItem(rating_key=502, title="Orphan Episode", media_type="episode", tmdb_id="999"))

    links = client.get("/api/media/501").json()["links"]
    assert links["tmdb"].endswith("/tv/2316")
    assert "The%20Show" in links["trakt"]
    # IMDb has real episode pages, so that one stays on the episode.
    assert links["imdb"].endswith("/tt0000001/")

    # No show to link to means no button, never a wrong one.
    orphan = client.get("/api/media/502").json()["links"]
    assert "tmdb" not in orphan and "trakt" not in orphan


def test_device_users_tab_breaks_down_each_account(client):
    claim(client)
    seed()
    owners = {o["user_id"]: o for o in client.get("/api/devices/dev-1").json()["owners"]}
    assert owners[7]["play_count"] == 2 and owners[7]["seconds"] == 1200
    assert owners[8]["play_count"] == 1
    assert owners[7]["places"][0]["city"] == "Springfield"
    assert owners[7]["last_watched"]["title"] == "A Show - Pilot"


def test_address_profile_lists_accounts_and_devices_and_filters_history(client):
    claim(client)
    seed()
    body = client.get("/api/addresses/203.0.113.9").json()
    assert body["totals"]["plays"] == 3
    assert {a["user_id"] for a in body["accounts"]} == {7, 8}
    assert [d["machine_id"] for d in body["devices"]] == ["dev-1"]
    assert body["place"]["city"] == "Springfield"
    assert client.get("/api/addresses/198.51.100.1").status_code == 404
    # History narrows to one address the same way it narrows to a device.
    assert client.get("/api/history?ip_address=203.0.113.9").json()["total"] == 3


def test_buttons_use_the_remote_url_while_the_api_uses_the_local_one(client):
    from app.db import session_scope
    from app.integrations import seerr
    from app.models import MediaItem
    from app.settings_store import trial

    claim(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=700, title="A Film", media_type="movie", tmdb_id="603"))
        item = db.get(MediaItem, 700)
        db.expunge(item)
    with trial({"seerr_url": "http://192.0.2.10:5055", "seerr_public_url": "https://seerr.example.com", "seerr_api_key": "k"}):
        assert seerr.seerr.base_url == "http://192.0.2.10:5055"
        assert seerr.seerr.link_for(item) == "https://seerr.example.com/movie/603"
    with trial({"seerr_url": "http://192.0.2.10:5055", "seerr_public_url": "", "seerr_api_key": "k"}):
        assert seerr.seerr.link_for(item) == "http://192.0.2.10:5055/movie/603"


def test_location_panel_follows_the_map_filters(client):
    claim(client)
    seed()
    everyone = client.get("/api/location?city=Springfield").json()
    assert {u["user_id"] for u in everyone["users"]} == {7, 8}
    one = client.get("/api/location?city=Springfield&user_id=8").json()
    assert [u["user_id"] for u in one["users"]] == [8]
    assert one["plays"] == 1


def test_access_review(client):
    import json
    import time

    from app.db import session_scope
    from app.models import BannedDevice, History, Library, User
    from tests.test_auth import claim

    claim(client)
    now = int(time.time())
    with session_scope() as db:
        db.add(Library(section_id=1, name="Movies"))
        db.add(Library(section_id=2, name="TV"))
        db.add(User(user_id=1, username="busy", shared_libraries=json.dumps(["1", "2"]), is_active=True))
        db.add(User(user_id=2, username="gone quiet", shared_libraries=json.dumps(["1"]), is_active=True))
        db.add(User(user_id=3, username="never", is_active=True))
        db.add(User(user_id=4, username="removed", deleted_in_tautulli=True))
        # Busy watches films and has never once opened the TV library.
        db.add(History(row_id=1, user_id=1, started=now - 86400, machine_id="a", section_id=1))
        db.add(History(row_id=2, user_id=2, started=now - 200 * 86400, machine_id="b", section_id=1))
        db.add(BannedDevice(machine_id="b", user_id=2))
    data = client.get("/api/access-review").json()
    people = {p["username"]: p for p in data["people"]}
    assert data["inactive_days"] == 90
    assert [p["username"] for p in data["people"]] == ["gone quiet", "never", "busy", "removed"]
    assert people["busy"]["libraries"] == ["Movies", "TV"] and people["busy"]["status"] == "active"
    assert people["gone quiet"]["status"] == "inactive" and people["gone quiet"]["idle_days"] == 200
    assert people["gone quiet"]["banned_devices"] == 1
    assert people["never"]["libraries"] is None and people["never"]["status"] == "never"
    # Sharing a library is not the same as them using it.
    assert people["busy"]["libraries_never_opened"] == ["TV"]
    assert people["gone quiet"]["libraries_never_opened"] == []
    assert people["never"]["libraries_never_opened"] is None
    client.post("/api/auth/users", json={"username": "viewer1", "password": "a-long-enough-password", "role": "viewer"})
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "viewer1", "password": "a-long-enough-password"})
    assert client.get("/api/access-review").status_code == 403

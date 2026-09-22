"""The home page: links worked out from what is set up, who sees each one, and
anything open that needs the person looking."""

from tests.test_auth import claim
from tests.test_privacy import as_viewer


def configure(client):
    claim(client)
    client.put("/api/settings", json={
        "plex_machine_identifier": "abc123",
        "seerr_url": "http://seerr.local:5055",
        "seerr_api_key": "k",
        "radarr_url": "http://radarr.local:7878",
        "radarr_api_key": "k",
        "radarr_public_url": "https://radarr.example.test",
    })


def keys(client, path="/api/home"):
    body = client.get(path).json()
    return [link["key"] for link in (body["links"] if path == "/api/home" else body)]


def test_links_come_from_what_is_set_up_and_admins_see_more(client):
    configure(client)
    admin = client.get("/api/home").json()
    assert [link["key"] for link in admin["links"]] == ["plex", "seerr", "radarr", "tautulli"]
    plex = admin["links"][0]
    assert plex["url"] == "https://app.plex.tv/desktop/#!/server/abc123" and plex["icon"] == "plex"
    assert [link["url"] for link in admin["links"] if link["key"] == "radarr"] == ["https://radarr.example.test"]
    assert admin["role"] == "admin" and admin["open_issues"] == 0

    # Sonarr is not set up, so it is not offered.
    assert "sonarr" not in keys(client)

    as_viewer(client, "all")
    viewer = client.get("/api/home").json()
    assert [link["key"] for link in viewer["links"]] == ["plex", "seerr"]
    assert viewer["role"] == "viewer"


def test_a_link_can_be_renamed_given_to_one_role_or_hidden(client):
    configure(client)
    client.put("/api/home/links/seerr", json={"label": "Ask for a film", "roles": "viewer", "position": 0})
    links = {link["key"]: link for link in client.get("/api/home/links").json()}
    assert links["seerr"]["label"] == "Ask for a film" and links["seerr"]["roles"] == "viewer"
    # An admin no longer sees a viewers-only link.
    assert "seerr" not in keys(client)

    assert client.delete("/api/home/links/plex").status_code == 200
    assert keys(client) == ["radarr", "tautulli"]
    assert {link["key"]: link["hidden"] for link in client.get("/api/home/links").json()}["plex"] is True
    client.put("/api/home/links/plex", json={"hidden": False})
    assert "plex" in keys(client)

    assert client.put("/api/home/links/nope", json={"label": "x"}).status_code == 404
    assert client.put("/api/home/links/plex", json={"roles": "everyone"}).status_code == 400


def test_a_link_of_your_own_can_be_added_and_deleted(client):
    configure(client)
    client.post("/api/home/links", json={"label": "Wiki", "url": "https://wiki.example.test", "roles": "admin"})
    custom = [link for link in client.get("/api/home/links").json() if link["custom"]]
    assert len(custom) == 1 and custom[0]["label"] == "Wiki"
    assert custom[0]["key"] in keys(client)

    assert client.post("/api/home/links", json={"label": "", "url": "https://x.test"}).status_code == 400
    assert client.post("/api/home/links", json={"label": "Bad", "url": "javascript:alert(1)"}).status_code == 400
    assert client.delete(f"/api/home/links/{custom[0]['key']}").status_code == 200
    assert [link for link in client.get("/api/home/links").json() if link["custom"]] == []

    # An admin only link is not offered to a viewer.
    client.post("/api/home/links", json={"label": "Wiki", "url": "https://wiki.example.test", "roles": "admin"})
    as_viewer(client, "all")
    assert "Wiki" not in [link["label"] for link in client.get("/api/home").json()["links"]]


def test_open_issues_are_counted_for_whoever_is_looking(client):
    from app.db import session_scope
    from app.models import MediaItem

    configure(client)
    with session_scope() as db:
        db.add(MediaItem(rating_key=5, title="Film", full_title="Film", media_type="movie"))
    client.post("/api/issues", json={"rating_key": 5, "message": "Sound is off"})
    assert client.get("/api/home").json()["open_issues"] == 1

    as_viewer(client, "all")
    # Not theirs, so nothing is waiting on them.
    assert client.get("/api/home").json()["open_issues"] == 0


def test_viewers_cannot_change_the_links(client):
    as_viewer(client, "all")
    assert client.get("/api/home/links").status_code == 403
    assert client.post("/api/home/links", json={"label": "x", "url": "https://x.test"}).status_code == 403
    assert client.delete("/api/home/links/plex").status_code == 403

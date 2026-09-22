"""Tests run against the settings the fixture provides, never a developer's.

A .env file sits next to the code and pydantic reads it, so without this the
suite inherited whatever that machine had: real addresses, real keys, and a
three second wait per test probing a LAN Tautulli it could not reach.
"""


def test_no_real_service_leaks_in_from_a_local_env_file(client):
    from app.settings_store import current, locked_keys
    from tests.test_auth import claim

    claim(client)

    settings = current()
    assert settings.tautulli_url == "http://tautulli.invalid:8181"
    for field in ("tautulli_local_url", "plex_token", "radarr_url", "sonarr_url", "seerr_url",
                  "tmdb_api_key", "webhook_url", "uptime_kuma_push_url", "maxmind_license_key"):
        assert getattr(settings, field) in ("", None), f"{field} came from somewhere outside the test"
    assert settings.apprise_urls in ([], "", None)

    # Only what the fixture sets is locked, so a test can still save the rest.
    assert "radarr_url" not in locked_keys()
    assert client.put("/api/settings", json={"radarr_url": "http://radarr.test:7878"}).status_code == 200

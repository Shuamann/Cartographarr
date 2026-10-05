"""Shared test fixtures."""

import os

import pytest

@pytest.fixture()
def client(monkeypatch, tmp_path):
    """A fresh app against an empty database, so tests start with no accounts.

    Its own directory per test: on Windows the previous test's engine still
    holds the file open, so reusing one path fails to delete it.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TAUTULLI_URL", "http://tautulli.invalid:8181")
    monkeypatch.setenv("TAUTULLI_API_KEY", "test")

    # .env is picked up by Settings, so without this the suite would download
    # GeoIP databases with real credentials and burn the account's quota.
    monkeypatch.setenv("MAXMIND_ACCOUNT_ID", "")
    monkeypatch.setenv("MAXMIND_LICENSE_KEY", "")
    monkeypatch.setenv("GEOIP_AUTO_UPDATE", "false")
    monkeypatch.setenv("ENFORCE_ENABLED", "false")
    # No scheduler and no capability probe. Starting both, and watching the
    # probe time out against a host that does not exist, was most of what a
    # test spent its time on: about four hundred milliseconds each, across
    # five hundred tests.
    monkeypatch.setenv("RUN_BACKGROUND_JOBS", os.environ.get("TEST_BACKGROUND_JOBS", "false"))

    # Imported inside the fixture: the engine binds to DATA_DIR at import time.
    import importlib
    import app.config, app.db, app.settings_store

    importlib.reload(app.config)
    # A developer's .env sits next to the code and pydantic reads it, so tests
    # inherited whatever that machine had: a real Tautulli on the LAN, real
    # Radarr and Seerr addresses, real keys. Besides the risk of touching
    # something real, every test then waited out the local Tautulli probe
    # against a host the test run cannot reach, which was three seconds each.
    # Tests get the environment this fixture sets and nothing else.
    app.config.Settings.model_config["env_file"] = None
    importlib.reload(app.db)
    importlib.reload(app.settings_store)
    import app.models

    importlib.reload(app.models)
    app.db.init_db()

    # Reloaded in place, so routers holding a reference to the module see the
    # session factory for this test's database rather than the last one's.
    import app.audit, app.filters

    importlib.reload(app.audit)
    # Filters build their conditions from the model classes, so they must see
    # this test's reloaded models, or a filtered query names two copies of the
    # same table.
    importlib.reload(app.filters)
    import app.privacy

    importlib.reload(app.privacy)
    import app.services.reports, app.services.library

    importlib.reload(app.services.reports)
    importlib.reload(app.services.library)

    # Failed sign-ins are remembered in memory; each test starts clean.
    from app.auth.security import login_throttle

    login_throttle._failures.clear()

    import app.auth.deps, app.routers.auth, app.main
    import app.routers.admin, app.routers.branding, app.routers.data, app.routers.live
    import app.routers.sharing, app.routers.reports, app.routers.library

    importlib.reload(app.auth.deps)
    importlib.reload(app.routers.auth)
    # Every router that opens a database session, or a test reading through
    # one of them sees whichever database an earlier test left behind.
    for router in (
        app.routers.data,
        app.routers.live,
        app.routers.admin,
        app.routers.branding,
        app.routers.sharing,
        app.routers.reports,
        app.routers.library,
    ):
        importlib.reload(router)
    importlib.reload(app.main)

    from fastapi.testclient import TestClient

    # TestClient reports the client host as "testclient" unless told otherwise,
    # which is not an IP address and so is never inside a trusted CIDR.
    with TestClient(app.main.app, client=("127.0.0.1", 50000)) as c:
        yield c

    app.db.engine.dispose()


@pytest.fixture()
def scheduled_client(monkeypatch, tmp_path, request):
    """The app with its scheduler running, for the few tests about scheduling.

    Everything else takes the client fixture, which leaves the background work
    off: starting a scheduler and watching a capability probe time out against
    a host that does not exist was most of what a test spent its time on.
    """
    monkeypatch.setenv("TEST_BACKGROUND_JOBS", "true")
    yield request.getfixturevalue("client")

import xml.etree.ElementTree as ElementTree
from types import SimpleNamespace

from app.plex import bandwidth


def xml(rows, devices=()):
    bw = "".join(
        f'<StatisticsBandwidth accountID="{a}" deviceID="{d}" at="{at}" lan="{lan}" bytes="{b}" timespan="3"/>'
        for at, a, d, lan, b in rows
    )
    dev = "".join(f'<Device id="{i}" clientIdentifier="{c}" name="n"/>' for i, c in devices)
    return ElementTree.fromstring(f"<MediaContainer>{bw}{dev}</MediaContainer>")


def a_plex(rows, devices=(), owner=2863368):
    answers = {
        "/devices": xml([], devices),
        f"/statistics/bandwidth?timespan={bandwidth.DAILY}": xml(rows, ()),
    }
    return SimpleNamespace(
        query=lambda path: answers[path],
        myPlexAccount=lambda: SimpleNamespace(id=owner),
    )


def test_the_owner_is_mapped_out_of_plexs_own_numbering(monkeypatch):
    """Plex calls the owner 1 against the server."""
    monkeypatch.setattr("app.plex.server.server", lambda: a_plex([(100, 1, 7, 0, 500), (100, 999, 7, 0, 10)]))
    rows = bandwidth.read()
    assert sorted(r["user_id"] for r in rows) == [999, 2863368]


def test_the_device_is_named_by_the_identifier_the_rest_of_the_app_uses(monkeypatch):
    monkeypatch.setattr("app.plex.server.server", lambda: a_plex([(100, 9, 42, 0, 500)], [(42, "abc-device")]))
    assert bandwidth.read()[0]["machine_id"] == "abc-device"


def test_a_device_plex_has_forgotten_keeps_its_figures(monkeypatch):
    """Over four years some devices drop off the list."""
    monkeypatch.setattr("app.plex.server.server", lambda: a_plex([(100, 9, 42, 0, 500)], []))
    row = bandwidth.read()[0]
    assert row["machine_id"] is None and row["bytes"] == 500 and row["device_id"] == 42


def test_local_and_remote_are_kept_apart(monkeypatch):
    """Local traffic is free and remote traffic is the thing an upload has to carry."""
    monkeypatch.setattr("app.plex.server.server", lambda: a_plex([(100, 9, 1, 1, 800), (100, 9, 2, 0, 300)]))
    rows = {r["device_id"]: r for r in bandwidth.read()}
    assert rows[1]["lan"] is True and rows[2]["lan"] is False


def test_a_row_missing_its_who_or_its_when_is_left_out(monkeypatch):
    monkeypatch.setattr("app.plex.server.server", lambda: a_plex([(100, 9, 1, 0, 50)]))
    plex = a_plex([(100, 9, 1, 0, 50)])
    plex.query = lambda path: (
        xml([], []) if path == "/devices"
        else ElementTree.fromstring('<MediaContainer><StatisticsBandwidth at="100" bytes="5"/></MediaContainer>')
    )
    monkeypatch.setattr("app.plex.server.server", lambda: plex)
    assert bandwidth.read() == []


def test_importing_twice_writes_the_same_rows(client, monkeypatch):
    """Keyed exactly as Plex gives it."""
    import asyncio

    from app.db import session_scope
    from app.models import PlexBandwidth
    from tests.test_auth import claim

    claim(client)
    rows = [(100, 9, 1, 0, 500), (100, 9, 1, 1, 200), (186400, 9, 1, 0, 700)]
    monkeypatch.setattr("app.plex.server.server", lambda: a_plex(rows, [(1, "abc")]))

    assert asyncio.run(bandwidth.store()) == {"rows": 3, "days": 2}
    asyncio.run(bandwidth.store())
    with session_scope() as db:
        kept = db.query(PlexBandwidth).all()
        assert len(kept) == 3
        assert sum(r.bytes for r in kept) == 1400


def test_it_is_a_report_anybody_can_ask_questions_of():
    from app.services.reports import SOURCES

    source = SOURCES["upload"]
    assert {"user", "device", "location"} <= set(source.columns)
    assert {"bytes", "remote_bytes", "local_bytes"} <= {m.key for m in source.measures}
    assert source.admin_only is True

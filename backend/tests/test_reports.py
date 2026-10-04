"""Reports.

The numbers have to be right (a split must not change a row's total, and
averages must not be summed), every preset has to run, and a viewer must not
be able to use a report to see what privacy hides elsewhere.
"""

from datetime import UTC, datetime

from tests.test_auth import claim
from tests.test_privacy import as_viewer


def at(hour):
    return datetime(2026, 9, 10, hour, 0, tzinfo=UTC)


def seed():
    from app.db import session_scope
    from app.models import Device, EnforcementLog, History, IpLocation, StreamEvent, User

    with session_scope() as db:
        db.add(User(user_id=1, username="alpha", friendly_name="Alpha"))
        db.add(User(user_id=2, username="beta"))
        db.add(Device(machine_id="tv", user_id=1, player="Living Room", platform="Roku"))
        db.add(IpLocation(ip="198.51.100.1", city="Springfield", asn_org="Home ISP", is_hosting=False))
        db.add(IpLocation(ip="198.51.100.2", city="Elsewhere", asn_org="Cloud VPN", is_hosting=True))
        plays = [
            (1, 1, "tv", "198.51.100.1", "direct play", 3600, 90),
            (2, 1, "tv", "198.51.100.1", "transcode", 1800, 50),
            (3, 1, "phone", "198.51.100.2", "transcode", 600, 10),
            (4, 2, "laptop", "198.51.100.1", "direct play", 7200, 100),
        ]
        for row_id, user, machine, ip, decision, secs, pct in plays:
            db.add(History(
                row_id=row_id, user_id=user, machine_id=machine, ip_address=ip, started=1_757_500_000 + row_id,
                transcode_decision=decision, play_duration=secs, percent_complete=pct, media_type="movie",
                rating_key=100 + row_id, full_title=f"Film {row_id}",
            ))
        stalls = [(1, "tv", 20, "transcode"), (1, "tv", 40, "transcode"), (2, "laptop", 6, "direct play")]
        for i, (user, machine, secs, decision) in enumerate(stalls):
            db.add(StreamEvent(
                kind="buffering", session_key=f"s{user}", user_id=user, machine_id=machine,
                ip_address="198.51.100.1", transcode_decision=decision, started_at=at(i), ended_at=at(i), seconds=secs,
            ))
        db.add(EnforcementLog(rule_name="No VPN", user_id=1, dry_run=True, result="would terminate", acted_at=at(3)))
        db.add(EnforcementLog(rule_name="No VPN", user_id=1, dry_run=False, result="terminated", acted_at=at(4)))


def test_plays_by_user_with_a_split_keeps_row_totals(client):
    claim(client)
    seed()
    r = client.get("/api/reports/run?source=plays&measure=plays&group=user&then=transcode_decision").json()
    rows = {row["label"]: row for row in r["rows"]}
    assert rows["Alpha"]["value"] == 3 and rows["beta"]["value"] == 1
    assert rows["Alpha"]["cells"] == {"direct play": 1, "transcode": 2}
    assert r["total"] == 4
    assert {c["label"] for c in r["columns"]} == {"Direct play", "Transcode"}


def test_averages_and_distinct_counts_are_not_summed(client):
    claim(client)
    seed()
    r = client.get("/api/reports/run?source=plays&measure=devices&group=user&then=transcode_decision").json()
    alpha = next(row for row in r["rows"] if row["key"] == 1)
    # Two devices overall, though the split columns count one and two.
    assert alpha["value"] == 2
    r = client.get("/api/reports/run?source=plays&measure=completion&group=user").json()
    assert next(row for row in r["rows"] if row["key"] == 1)["value"] == 50


def test_buffering_by_device_and_network(client):
    claim(client)
    seed()
    r = client.get("/api/reports/run?source=buffering&measure=episodes&group=device").json()
    assert [(row["label"], row["value"]) for row in r["rows"]] == [("Living Room (Roku)", 2), ("laptop", 1)]
    r = client.get("/api/reports/run?source=buffering&measure=longest&group=network").json()
    assert r["rows"] == [{"key": "Home ISP", "value": 40, "label": "Home ISP"}]
    r = client.get("/api/reports/run?source=buffering&measure=minutes&group=user&user_id=2").json()
    assert r["rows"][0]["value"] == 0.1 and r["total"] == 0.1


def test_filters_a_source_cannot_apply_are_reported(client):
    claim(client)
    seed()
    r = client.get("/api/reports/run?source=buffering&measure=episodes&group=user&section_id=4&watched=true").json()
    assert set(r["ignored"]) == {"section_id", "watched"}


def test_vpn_filter_outcomes_and_time_grouping(client):
    claim(client)
    seed()
    r = client.get("/api/reports/run?source=plays&measure=plays&group=user&is_hosting=true").json()
    assert [(row["key"], row["value"]) for row in r["rows"]] == [(1, 1)]
    r = client.get("/api/reports/run?source=matches&measure=matches&group=rule&then=outcome").json()
    assert r["rows"][0]["cells"] == {"Recorded only": 1, "Stopped": 1}
    r = client.get("/api/reports/run?source=buffering&measure=episodes&group=day").json()
    assert r["group"]["time"] is True and sum(row["value"] for row in r["rows"]) == 3
    # Quiet hours are kept as zeros, so the chart does not close them up.
    r = client.get("/api/reports/run?source=buffering&measure=episodes&group=hour").json()
    assert len(r["rows"]) == 24 and sum(row["value"] for row in r["rows"]) == 3
    r = client.get("/api/reports/run?source=buffering&measure=longest&group=weekday").json()
    assert len(r["rows"]) == 7 and [row["value"] for row in r["rows"]].count(None) == 6
    r = client.get("/api/reports/run?source=buffering&measure=episodes&group=user&start=2030-01-01").json()
    assert r["rows"] == []


def test_every_preset_runs(client):
    claim(client)
    seed()
    catalog = client.get("/api/reports/catalog").json()
    assert catalog["presets"]
    for p in catalog["presets"]:
        q = f"source={p['source']}&measure={p['measure']}&group={p['group']}"
        if p.get("then"):
            q += f"&then={p['then']}"
        if p.get("filters"):
            q += "&" + p["filters"]
        res = client.get(f"/api/reports/run?{q}")
        assert res.status_code == 200, (p["id"], res.text)


def test_bad_specs_are_refused(client):
    claim(client)
    assert client.get("/api/reports/run?source=nope&measure=plays&group=user").status_code == 400
    assert client.get("/api/reports/run?source=plays&measure=episodes&group=user").status_code == 400
    assert client.get("/api/reports/run?source=plays&measure=plays&group=rule").status_code == 400
    assert client.get("/api/reports/run?source=plays&measure=plays&group=user&then=user").status_code == 400


def test_viewers_cannot_report_on_others(client):
    as_viewer(client, "anonymised")
    catalog = client.get("/api/reports/catalog").json()
    assert [s["key"] for s in catalog["sources"]] == ["plays"]
    assert client.get("/api/reports/run?source=buffering&measure=episodes&group=user").status_code == 403

    # Totals still cover the server, but naming people narrows to the viewer.
    by_type = client.get("/api/reports/run?source=plays&measure=plays&group=media_type").json()
    assert by_type["total"] == 3
    by_user = client.get("/api/reports/run?source=plays&measure=plays&group=user&user_id=8").json()
    assert [row["key"] for row in by_user["rows"]] == [7]
    by_title = client.get("/api/reports/run?source=plays&measure=plays&group=media_type&then=title").json()
    assert by_title["total"] == 1


def test_saved_reports_are_admin_managed_and_logged(client):
    claim(client)
    spec = {"name": "Stalls", "source": "buffering", "measure": "episodes", "group": "device", "then": None, "range": "30"}
    saved = client.post("/api/reports/saved", json=spec).json()
    assert saved["name"] == "Stalls" and saved["source"] == "buffering"
    assert client.post("/api/reports/saved", json={**spec, "group": "rule"}).status_code == 400
    assert client.put(f"/api/reports/saved/{saved['id']}", json={**spec, "name": "Stalls by device"}).status_code == 200
    assert [r["name"] for r in client.get("/api/reports/saved").json()] == ["Stalls by device"]
    assert client.delete(f"/api/reports/saved/{saved['id']}").status_code == 200
    actions = [e["action"] for e in client.get("/api/log?kind=changes").json()]
    assert {"report.save", "report.update", "report.delete"} <= set(actions)


def test_file_details_streams_and_server_load(client):
    from app.db import session_scope
    from app.models import BandwidthSample, MediaItem, StreamEvent, StreamSession

    claim(client)
    seed()
    with session_scope() as db:
        db.add(MediaItem(rating_key=101, title="Film 1", media_type="movie", file_bitrate=45000, video_resolution="4k"))
        db.add(MediaItem(rating_key=102, title="Film 2", media_type="movie", file_bitrate=8000, video_resolution="1080p"))
        db.add(StreamSession(user_id=1, rating_key=101, transcode_decision="transcode", primary_cause="subtitle_burn",
                             transcode_hw=True, buffer_count=2, buffer_seconds=30, started_at=at(5), platform="Roku"))
        db.add(StreamSession(user_id=2, rating_key=102, transcode_decision="direct play", started_at=at(6), platform="Roku"))
        minute = int(at(5).timestamp()) // 60 * 60
        db.add(BandwidthSample(minute=minute, wan_kbps=42000, streams=3, remote_streams=2, transcodes=1, hw_transcodes=1))
        db.add(BandwidthSample(minute=minute + 60, wan_kbps=12000, streams=1, remote_streams=1, transcodes=0, hw_transcodes=0))
        for e in db.query(StreamEvent).all():
            e.cause = "viewer"

    r = client.get("/api/reports/run?source=plays&measure=plays&group=file_bitrate_band").json()
    assert {row["label"]: row["value"] for row in r["rows"]} == {
        "40 Mbps and up": 1, "5 to 10 Mbps": 1, "File not checked yet": 2,
    }
    r = client.get("/api/reports/run?source=streams&measure=transcoded&group=transcode_cause").json()
    assert {row["label"]: row["value"] for row in r["rows"]} == {"Subtitles burned in": 1, "Not transcoded": 0}
    r = client.get("/api/reports/run?source=streams&measure=stall_minutes&group=hardware").json()
    assert {row["label"]: row["value"] for row in r["rows"]}["Hardware"] == 0.5
    r = client.get("/api/reports/run?source=server&measure=peak_upload&group=day").json()
    assert r["total"] == 42 and r["measure"]["unit"] == "mbps"
    r = client.get("/api/reports/run?source=buffering&measure=episodes&group=stall_cause").json()
    assert r["rows"][0]["label"] == "Viewer's device or connection"
    catalog = client.get("/api/reports/catalog").json()
    server = next(s for s in catalog["sources"] if s["key"] == "server")
    assert {d["group"] for d in server["dimensions"]} == {"When"}


def test_reports_can_be_charted(client):
    """A pile of reports should answer what went wrong, about what, and
    whether anyone dealt with it."""
    from datetime import UTC, datetime, timedelta

    from app.db import session_scope
    from app.models import Issue, MediaItem

    claim(client)
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as db:
        db.add(MediaItem(rating_key=5, title="Film", full_title="Film", media_type="movie"))
        for n, (kind, status) in enumerate([("audio", "open"), ("audio", "resolved"), ("subtitles", "open")]):
            db.add(Issue(source="local", issue_type=kind, status=status, message=f"m{n}", rating_key=5,
                         media_type="movie", title="Film", reporter_user_id=7, created_at=now - timedelta(days=n)))

    answer = client.get("/api/reports/run?source=issues&measure=reports&group=issue_type&range=30").json()
    counts = {row["label"]: row["value"] for row in answer["rows"]}
    assert counts == {"audio": 2, "subtitles": 1}

    still_open = client.get("/api/reports/run?source=issues&measure=open&group=issue_type&range=30").json()
    assert {row["label"]: row["value"] for row in still_open["rows"]} == {"audio": 1, "subtitles": 1}

    by_title = client.get("/api/reports/run?source=issues&measure=reports&group=title&range=30").json()
    assert [row["label"] for row in by_title["rows"]] == ["Film"]
def test_the_library_itself_can_be_reported_on(client):
    """Space, counts and what has never been played, from the files rather
    than the plays."""
    from app.db import session_scope
    from app.models import MediaItem
    from app.services import reports

    claim(client)
    seed()
    with session_scope() as db:
        # Two films in one library, one episode in another, and a row that is
        # only metadata: a show, with no file and no size.
        db.add(MediaItem(rating_key=101, title="Film 1", media_type="movie", section_id=1,
                         file_size=8_000_000_000, file_container="mkv", video_resolution="1080p", duration=3_600_000))
        db.add(MediaItem(rating_key=900, title="Film 9", media_type="movie", section_id=1,
                         file_size=2_000_000_000, file_container="mp4", video_resolution="720p", duration=1_800_000))
        db.add(MediaItem(rating_key=901, title="Show - S01E01", media_type="episode", section_id=2,
                         grandparent_rating_key=950, file_size=1_000_000_000, file_container="mkv",
                         video_resolution="1080p", duration=1_800_000))
        db.add(MediaItem(rating_key=950, title="Show", media_type="show", section_id=2))

    r = client.get("/api/reports/run?source=library&measure=size&group=library").json()
    # The show is left out: it has no file, so it is not what is on the disks.
    assert r["total"] == 11_000_000_000
    assert r["measure"]["unit"] == "bytes" and r["measure"]["additive"] is True
    assert {row["key"]: row["value"] for row in r["rows"]} == {1: 10_000_000_000, 2: 1_000_000_000}

    r = client.get("/api/reports/run?source=library&measure=items&group=played").json()
    # Only Film 1 has a play against it, from the seed.
    assert {row["label"]: row["value"] for row in r["rows"]} == {"Never played": 2, "Played at least once": 1}
    r = client.get("/api/reports/run?source=library&measure=never_played&group=container").json()
    assert {row["label"]: row["value"] for row in r["rows"]} == {"mkv": 1, "mp4": 1}

    r = client.get("/api/reports/run?source=library&measure=hours&group=media_type").json()
    assert r["total"] == 2  # an hour and two half hours

    # A snapshot has no clock, and says so rather than quietly covering
    # everything while the page shows a range.
    r = client.get("/api/reports/run?source=library&measure=items&group=library&start=2026-09-01").json()
    assert r["ignored"] == ["dates"] and r["total"] == 3
    catalog = client.get("/api/reports/catalog").json()
    library = next(s for s in catalog["sources"] if s["key"] == "library")
    assert not [d for d in library["dimensions"] if d["group"] == "When"]
    # It is the Library tab's data, and that tab is for admins. The viewer
    # test above checks the catalog offers them nothing but plays.
    assert reports.SOURCES["library"].admin_only

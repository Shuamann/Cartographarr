"""Stream records, upload samples and the likely cause of a stall.

Each of these ends up in a report someone acts on (re-encode a file, blame a
device, buy more upload), so the reasoning is tested case by case.
"""

import time
from datetime import UTC, datetime, timedelta

from app.services import streams, tracker


def live(key="1", **over):
    base = {
        "session_key": key, "user_id": 7, "machine_id": "tv", "player": "TV", "state": "playing",
        "rating_key": 100, "full_title": "Film", "media_type": "movie", "location": "wan",
        "quality_profile": "Original", "transcode_decision": "direct play", "video_decision": "direct play",
        "audio_decision": "direct play", "subtitle_decision": "", "container_decision": "direct play",
        "video_codec": "hevc", "stream_video_codec": "hevc", "audio_codec": "eac3", "stream_audio_codec": "eac3",
        "video_dynamic_range": "SDR", "stream_video_dynamic_range": "SDR", "bandwidth": "8000", "stream_bitrate": "7000",
    }
    base.update(over)
    return base


def test_causes_are_read_from_what_changed():
    assert streams.transcode_causes(live()) == []
    assert streams.transcode_causes(live(subtitle_decision="burn", video_decision="transcode")) == ["subtitle_burn"]
    assert streams.transcode_causes(live(video_decision="transcode", stream_video_codec="h264")) == ["video_codec"]
    hdr = live(video_decision="transcode", video_dynamic_range="HDR10", stream_video_dynamic_range="SDR", stream_video_codec="h264")
    assert streams.transcode_causes(hdr) == ["hdr_tonemap", "video_codec"]
    assert streams.transcode_causes(live(video_decision="transcode", quality_profile="4 Mbps 720p")) == ["quality_setting"]
    assert streams.transcode_causes(live(video_decision="transcode")) == ["video_bitrate"]
    assert streams.transcode_causes(live(audio_decision="transcode", stream_audio_codec="aac")) == ["audio_codec"]
    assert streams.transcode_causes(live(audio_decision="transcode")) == ["audio_channels"]
    assert streams.transcode_causes(live(video_decision="copy", transcode_decision="copy")) == ["container"]


def test_a_stream_keeps_its_worst_decision_and_every_cause(client):
    from app.db import session_scope
    from app.models import StreamSession

    tracker.reset()
    t0 = 1_800_000_000.0
    tracker.observe([live()], now=t0)
    tracker.observe([live(transcode_decision="transcode", video_decision="transcode", subtitle_decision="burn", bandwidth="12000")], now=t0 + 10)
    tracker.observe([live()], now=t0 + 20)  # subtitles off again
    tracker.observe([], now=t0 + 30)

    with session_scope() as db:
        rows = db.query(StreamSession).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.transcode_decision == "transcode" and row.subtitle_decision == "burn"
        assert row.primary_cause == "subtitle_burn" and row.bandwidth_max == 12000
        assert row.ended_at is not None and row.buffer_count == 0


def test_bandwidth_samples_keep_the_peak_of_each_minute(client):
    from app.db import session_scope
    from app.models import BandwidthSample

    minute = 1_800_000_000 // 60 * 60
    streams.sample({"wan_bandwidth": 20000, "lan_bandwidth": 1000}, [live(), live("2")], minute + 5)
    streams.sample({"wan_bandwidth": 35000, "lan_bandwidth": 0}, [live()], minute + 40)
    streams.sample({"wan_bandwidth": 5000, "lan_bandwidth": 0}, [live()], minute + 50)
    with session_scope() as db:
        row = db.get(BandwidthSample, minute)
        assert (row.wan_kbps, row.lan_kbps, row.streams, row.remote_streams) == (35000, 1000, 2, 2)


def test_upload_alert_fires_once_per_half_hour(client, monkeypatch):
    from app.settings_store import current

    real = current()
    monkeypatch.setattr("app.settings_store.current", lambda: real.model_copy(update={"upload_capacity_mbps": 40, "upload_alert_percent": 80}))
    sent = []
    monkeypatch.setattr("app.audit.record", lambda *a, **k: sent.append(a[2]))
    streams._last_alert = 0.0
    streams._maybe_alert(33000, 3, 10_000.0)
    streams._maybe_alert(39000, 4, 10_060.0)  # still within the quiet period
    streams._maybe_alert(20000, 1, 20_000.0)  # below the level
    streams._maybe_alert(36000, 2, 12_000.0)  # past half an hour
    assert len(sent) == 2 and "82%" in sent[0]


def _stall(db, user, rating_key, start, seconds=10, machine="m", session_key=None):
    from app.models import StreamEvent

    e = StreamEvent(kind="buffering", user_id=user, machine_id=machine, rating_key=rating_key,
                    session_key=session_key,
                    started_at=start, ended_at=start + timedelta(seconds=seconds), seconds=seconds)
    db.add(e)
    db.flush()
    return e


def test_stall_causes(client):
    from app.db import session_scope
    from app.models import BandwidthSample
    from app.services.stalls import classify

    t = datetime(2026, 9, 1, 20, 0, tzinfo=UTC)
    with session_scope() as db:
        lone = _stall(db, 1, 500, t)
        assert classify(db, lone)[0] == "one_off"

        # Someone else stalls at the same moment: server side.
        _stall(db, 2, 600, t + timedelta(seconds=30))
        assert classify(db, lone)[0] == "server"

    t2 = t + timedelta(days=3)
    with session_scope() as db:
        # A different user stalled on the same title last week: the file.
        _stall(db, 3, 700, t2 - timedelta(days=5))
        mine = _stall(db, 4, 700, t2)
        assert classify(db, mine)[0] == "file"

    t3 = t + timedelta(days=6)
    with session_scope() as db:
        # One viewer stalls on three different titles, alone each time.
        for i, key in enumerate((801, 802, 803)):
            last = _stall(db, 5, key, t3 + timedelta(hours=i * 5))
        assert classify(db, last)[0] == "viewer"

    t5 = t + timedelta(days=20)
    with session_scope() as db:
        # One stream that rebuffers all evening is not a run of one-offs.
        for i in range(2):
            twice = _stall(db, 9, 950, t5 + timedelta(minutes=i * 5), session_key="sitting")
        assert classify(db, twice)[0] == "one_off"
        third = _stall(db, 9, 950, t5 + timedelta(minutes=20), session_key="sitting")
        cause, detail = classify(db, third)
        assert cause == "stream" and "3 times in a sitting" in detail
        # Another stream of the same person's is judged on its own.
        alone = _stall(db, 9, 951, t5 + timedelta(hours=6), session_key="another")
        assert classify(db, alone)[0] == "one_off"

    t4 = t + timedelta(days=9)
    with session_scope() as db:
        db.add(BandwidthSample(minute=int(t4.timestamp()) // 60 * 60, wan_kbps=47000))
        busy = _stall(db, 6, 900, t4 + timedelta(seconds=5))
        cause, detail = classify(db, busy, capacity_mbps=50, upload_percent=90)
        assert cause == "upload" and "47.0 of 50" in detail
        assert classify(db, busy, capacity_mbps=0)[0] == "one_off"


def test_upload_alert_is_sent_from_the_sweep_thread(client, monkeypatch):
    """The sweep records samples in a worker thread with no event loop; the
    notification must still go out."""
    import threading

    from app.integrations.notify import apprise_notifier
    from app.settings_store import current

    real = current()
    monkeypatch.setattr("app.settings_store.current", lambda: real.model_copy(update={"upload_capacity_mbps": 10, "upload_alert_percent": 50}))
    monkeypatch.setattr("app.audit.record", lambda *a, **k: None)
    monkeypatch.setattr(type(apprise_notifier), "configured", lambda self: True)
    sent = []

    async def fake_send(self, title, body):
        sent.append(title)
        return "ok"

    monkeypatch.setattr(type(apprise_notifier), "send", fake_send)
    streams._last_alert = 0.0
    worker = threading.Thread(target=streams._maybe_alert, args=(9000, 2, 50_000.0))
    worker.start()
    worker.join()
    assert sent == ["Upload nearly full"]


def test_upload_capacity_comes_from_plex_unless_set(client, monkeypatch):
    import asyncio

    from app.settings_store import current
    from tests.test_auth import claim

    class FakeTautulli:
        async def call(self, cmd, pref=None):
            return {"WanTotalMaxUploadRate": "40000", "WanPerStreamMaxUploadRate": "8000"}[pref]

    assert streams.upload_capacity() == (0.0, "unknown")
    assert asyncio.run(streams.read_plex_upload(FakeTautulli())) == (40000, 8000)
    assert streams.upload_capacity() == (40.0, "plex")
    real = current()
    monkeypatch.setattr("app.settings_store.current", lambda: real.model_copy(update={"upload_capacity_mbps": 25}))
    assert streams.upload_capacity() == (25.0, "settings")

    claim(client)
    info = client.get("/api/library/upload").json()
    assert info["plex_upload_mbps"] == 40 and info["plex_stream_limit_mbps"] == 8


# ---- a speed that is not a speed --------------------------------------------


def test_a_negative_transcode_speed_is_not_recorded():
    """Plex reports this as a multiple of real time, and sometimes reports
    nonsense. One session on the server this was written against is recorded at
    -302.8, which went into the minimum and stayed there, making a stream that
    was fine look like one the server could not keep up with."""
    assert streams._plausible_speed(-302.8) is None
    assert streams._plausible_speed(0.0) is None
    assert streams._plausible_speed(None) is None


def test_an_absurdly_fast_one_is_not_either():
    assert streams._plausible_speed(1000.0) is None
    assert streams._plausible_speed(streams.SPEED_CEILING + 0.1) is None


def test_a_real_speed_survives():
    assert streams._plausible_speed(0.8) == 0.8
    assert streams._plausible_speed(1.0) == 1.0
    assert streams._plausible_speed(11.66) == 11.66


# ---- an empty answer is not a no --------------------------------------------


def test_tautullis_empty_hardware_answer_is_not_a_boolean():
    """Tautulli sends these keys with an empty string when it has nothing.

    The columns are booleans, so an empty string is refused and the whole
    insert fails, which silently lost every live session on a server reading
    from Tautulli. It is also not a no: Tautulli not saying whether hardware
    was asked for is different from it saying hardware was not asked for.
    """
    assert streams._said("") is None
    assert streams._said(None) is None
    assert streams._said("0") is False
    assert streams._said("1") is True
    assert streams._said(False) is False
    assert streams._said(True) is True


def test_a_tautulli_session_builds_a_row_the_columns_accept():
    row = streams.row_for(
        {
            "session_key": "9",
            "transcode_hw_requested": "",
            "transcode_hw_decode": "",
            "transcode_hw_encode": "",
            "transcode_protocol": "",
        },
        time.time(),
    )
    for key in ("transcode_hw_requested", "transcode_hw_decode", "transcode_hw_encode"):
        assert row[key] is None, key
    assert row["transcode_protocol"] is None

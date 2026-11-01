import asyncio

from app.plex import alerts


def playing(state):
    return {"type": "playing", "PlaySessionStateNotification": [{"sessionKey": "9", "state": state}]}


def test_a_stream_nobody_has_seen_before_is_worth_waking_for():
    seen = {}
    assert alerts.worth_waking(playing("playing"), seen) is True
    assert seen == {"9": "playing"}


def test_the_same_stream_carrying_on_is_not():
    """This is the whole difficulty."""
    seen = {}
    assert alerts.worth_waking(playing("playing"), seen) is True
    for _ in range(5):
        assert alerts.worth_waking(playing("playing"), seen) is False


def test_pausing_and_resuming_each_count():
    seen = {}
    alerts.worth_waking(playing("playing"), seen)
    assert alerts.worth_waking(playing("paused"), seen) is True
    assert alerts.worth_waking(playing("paused"), seen) is False
    assert alerts.worth_waking(playing("playing"), seen) is True


def test_a_stream_that_stopped_is_forgotten():
    seen = {}
    alerts.worth_waking(playing("playing"), seen)
    assert alerts.worth_waking(playing("stopped"), seen) is True
    assert seen == {}
    assert alerts.worth_waking(playing("playing"), seen) is True


def test_anything_else_is_not_worth_waking_for():
    seen = {}
    assert alerts.worth_waking({"type": "timeline"}, seen) is False
    assert alerts.worth_waking({"type": "activity"}, seen) is False
    assert alerts.worth_waking({"type": "playing"}, seen) is False
    assert alerts.worth_waking({}, seen) is False


def test_the_address_becomes_a_socket_address_and_carries_the_token():
    from types import SimpleNamespace

    secure = alerts._url(SimpleNamespace(plex_url="https://example.plex.direct:32400/", plex_token="abc"))
    assert secure.startswith("wss://example.plex.direct:32400/:/websockets/notifications")
    assert secure.endswith("X-Plex-Token=abc")
    plain = alerts._url(SimpleNamespace(plex_url="http://192.0.2.10:32400", plex_token="abc"))
    assert plain.startswith("ws://192.0.2.10:32400/")


def test_it_waits_rather_than_spinning_when_plex_is_not_set_up(monkeypatch):
    """A server with no token must not reconnect in a loop."""
    from types import SimpleNamespace

    monkeypatch.setattr("app.settings_store.current", lambda: SimpleNamespace(plex_token=None, plex_url=None))
    waited = []

    async def no_sleep(seconds, stopping):
        waited.append(seconds)
        stopping.set()

    monkeypatch.setattr(alerts, "_sleep_or_stop", no_sleep)
    stopping = asyncio.Event()
    asyncio.run(alerts.listen(lambda: None, stopping))
    assert waited == [alerts.RETRY_SECONDS]


def test_shutdown_does_not_wait_out_the_retry():

    async def run():
        stopping = asyncio.Event()
        task = asyncio.create_task(alerts._sleep_or_stop(30, stopping))
        await asyncio.sleep(0)
        stopping.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(run())


def test_the_poll_is_still_registered_and_unchanged():
    """The whole design rests on this."""
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert '"enforce", "Check live streams"' in source
    assert "activity_poll_seconds" in source, "the poll still sets its own interval"
    # Not only that a listener runs, but what it wakes. The test above proves
    assert 'plex_alerts.listen(lambda: tasks.run("enforce"' in source, (
        "the listener must wake the enforcer, or it is a connection that does nothing"
    )


def test_an_event_actually_reaches_the_enforcer(monkeypatch):
    import json as _json
    from types import SimpleNamespace

    class FakeSocket:
        def __init__(self, messages):
            self.messages = messages

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def __aiter__(self):
            async def pump():
                for m in self.messages:
                    yield _json.dumps({"NotificationContainer": m})

            return pump()

    sent = [
        {"type": "playing", "PlaySessionStateNotification": [{"sessionKey": "1", "state": "playing"}]},
        # The same stream saying where it has got to: no second wake.
        {"type": "playing", "PlaySessionStateNotification": [{"sessionKey": "1", "state": "playing"}]},
        {"type": "timeline"},
    ]
    woken = []

    async def wake():
        woken.append(True)

    monkeypatch.setattr(
        "app.settings_store.current",
        lambda: SimpleNamespace(plex_token="t", plex_url="http://plex.example.test:32400"),
    )
    monkeypatch.setitem(
        __import__("sys").modules, "websockets",
        SimpleNamespace(connect=lambda url, **kw: FakeSocket(sent)),
    )

    async def stop_after_first_pass(seconds, stopping):
        stopping.set()

    monkeypatch.setattr(alerts, "_sleep_or_stop", stop_after_first_pass)
    monkeypatch.setattr(alerts, "QUIET_SECONDS", 0.0)

    stopping = asyncio.Event()
    asyncio.run(alerts.listen(wake, stopping))
    assert woken == [True], "one wake for the stream starting, and nothing for the ping or the timeline"

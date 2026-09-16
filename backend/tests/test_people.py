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

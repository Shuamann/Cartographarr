"""A live stream from an address history has never seen still belongs on the
map. The sync only geocodes addresses with finished plays, so the activity
endpoint looks the rest up itself."""

from tests.test_auth import claim


def test_an_unseen_address_is_located_while_the_stream_is_live(client, monkeypatch):
    from app.db import session_scope
    from app.models import IpLocation
    from app.routers import live
    from app.services import sync

    claim(client)
    asked: list[set[str]] = []

    def fake_geocode(ips):
        """What GeoResolver would do with a public address it knows."""
        asked.append(set(ips))
        with session_scope() as db:
            for ip in ips:
                db.merge(IpLocation(ip=ip, city="Kansas City", country="United States",
                                    country_code="US", lat=39.1, lon=-94.6, is_private=False))
        return len(ips)

    async def fake_call(self, command, **params):
        return {
            "stream_count": "1",
            "sessions": [{
                "session_key": "9", "user_id": "7", "ip_address": "198.51.100.42", "location": "wan",
                "state": "playing", "full_title": "Mayday", "rating_key": "41", "media_type": "movie",
            }],
        }

    monkeypatch.setattr(sync, "geocode_ips", fake_geocode)
    monkeypatch.setattr("app.tautulli.client.TautulliClient.call", fake_call)
    monkeypatch.setattr(live, "is_configured", lambda: True)

    body = client.get("/api/activity").json()
    assert asked == [{"198.51.100.42"}]
    place = body["sessions"][0]["geo"]
    assert place and place["lat"] == 39.1 and place["city"] == "Kansas City"

    # Known addresses are not looked up again.
    assert client.get("/api/activity").json()["sessions"][0]["geo"]["city"] == "Kansas City"
    assert len(asked) == 1

"""Plays and sessions are both counted: a play paused and resumed, or carried
to another device, is one play made of several sessions."""

from tests.test_auth import claim

NOW = 1789570000


def seed():
    from app.db import session_scope
    from app.models import History, IpLocation, User

    rows = [
        # One play, two sessions, two devices and two addresses.
        (1, 1, "phone", "1.2.3.4", NOW),
        (4, 1, "tv", "5.6.7.8", NOW + 900),
        # A second play, one session.
        (5, 5, "tv", "5.6.7.8", NOW + 5000),
    ]
    with session_scope() as db:
        db.add(User(user_id=7, username="watcher"))
        for ip in ("1.2.3.4", "5.6.7.8"):
            db.add(IpLocation(ip=ip, city="Denver", region="Colorado", country="United States", lat=39.7, lon=-104.9))
        for row_id, reference_id, machine, ip, started in rows:
            db.add(History(row_id=row_id, reference_id=reference_id, user_id=7, machine_id=machine, ip_address=ip,
                           started=started, stopped=started + 600, play_duration=600, media_type="episode",
                           rating_key=99, full_title="Show - Ep", location="wan", transcode_decision="direct play"))


def test_history_page_and_profiles_count_both(client):
    claim(client)
    seed()

    page = client.get("/api/history").json()
    assert page["plays"] == 2 and page["total"] == 3 and len(page["items"]) == 3

    profile = client.get("/api/users/7").json()["totals"]
    assert profile["plays"] == 2 and profile["sessions"] == 3

    summary = client.get("/api/stats/summary").json()
    assert summary["plays"] == 2 and summary["sessions"] == 3

    dashboard = client.get("/api/dashboard").json()["totals"]
    assert dashboard["plays"] == 2 and dashboard["sessions"] == 3

    top = client.get("/api/dashboard").json()["top_users"]
    assert [t["plays"] for t in top] == [2]


def test_library_counts_a_resumed_play_once(client):
    from app.db import session_scope
    from app.models import MediaItem
    from app.services.library import play_stats

    claim(client)
    seed()
    with session_scope() as db:
        db.add(MediaItem(rating_key=99, title="Ep", media_type="episode", file_bitrate=9000))
    with session_scope() as db:
        stats = play_stats(db, days=3650, keys=[99])
    assert stats[99]["plays"] == 2 and stats[99]["remote"] == 2

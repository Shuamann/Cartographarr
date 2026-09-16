"""Coercion checks. Tautulli types everything loosely, so this is where the
bugs are — the upsert itself is SQLAlchemy's problem, not ours.
"""

from app.services.sync import _bool, _int, _map_history, _split_guids


def test_int_survives_tautullis_stringly_typed_numbers():
    assert _int("1") == 1
    assert _int(1) == 1
    assert _int("") is None
    assert _int(None) is None
    assert _int("not a number") is None


def test_bool_distinguishes_false_from_unknown():
    # secure/relayed are tri-state: True, False, or "Tautulli didn't say".
    assert _bool("1") is True
    assert _bool("0") is False
    assert _bool("") is None
    assert _bool(None) is None


def test_map_history_coerces_a_real_row():
    row = {
        "row_id": "42",
        "user_id": "122693376",
        "machine_id": "abc123",
        "ip_address": "1.2.3.4",
        "started": "1740268263",
        "watched_status": "0.5",
        "secure": "1",
        "relayed": "0",
        "live": "0",
        "title": "",
    }
    out = _map_history(row)
    assert out["row_id"] == 42
    assert out["started"] == 1740268263
    assert out["watched_status"] == 0.5
    assert out["secure"] is True
    assert out["relayed"] is False
    assert out["live"] is False
    assert out["title"] is None  # empty string is absence, not a title


def test_split_guids():
    guids = ["imdb://tt32333324", "tmdb://1560520", "tvdb://373216"]
    assert _split_guids(guids) == {
        "imdb_id": "tt32333324",
        "tmdb_id": "1560520",
        "tvdb_id": "373216",
    }


def test_split_guids_tolerates_missing_and_partial():
    assert _split_guids(None) == {"imdb_id": None, "tmdb_id": None, "tvdb_id": None}
    assert _split_guids(["tmdb://99"])["tmdb_id"] == "99"
    assert _split_guids(["tmdb://99"])["imdb_id"] is None

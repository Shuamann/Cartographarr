from app.config import Settings
from app import settings_store as ss

UNSET = Settings(tautulli_url="", tautulli_api_key="")
SET = Settings(tautulli_url="http://tautulli:8181", tautulli_api_key="k")


def test_fresh_install_reports_what_is_missing(monkeypatch):
    monkeypatch.setattr(ss, "_cache", (UNSET, frozenset()))
    assert ss.is_configured() is False
    assert ss.missing_required() == ["tautulli_url", "tautulli_api_key"]


def test_configured_once_both_are_present(monkeypatch):
    monkeypatch.setattr(ss, "_cache", (SET, frozenset()))
    assert ss.is_configured() is True
    assert ss.missing_required() == []


def test_partial_config_is_not_configured(monkeypatch):
    half = Settings(tautulli_url="http://tautulli:8181", tautulli_api_key="")
    monkeypatch.setattr(ss, "_cache", (half, frozenset()))
    assert ss.is_configured() is False
    assert ss.missing_required() == ["tautulli_api_key"]


def test_env_locked_keys_are_refused_from_the_ui(monkeypatch):
    monkeypatch.setattr(ss, "_cache", (SET, frozenset({"tautulli_api_key"})))
    try:
        ss.save({"tautulli_api_key": "sneaky"})
    except ValueError as exc:
        assert "environment" in str(exc)
    else:
        raise AssertionError("env-locked setting was writable from the UI")


def test_unknown_setting_is_refused(monkeypatch):
    monkeypatch.setattr(ss, "_cache", (SET, frozenset()))
    try:
        ss.save({"not_a_real_setting": 1})
    except ValueError as exc:
        assert "Unknown" in str(exc)
    else:
        raise AssertionError("unknown setting was accepted")

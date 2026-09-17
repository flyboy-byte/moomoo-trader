"""Regression coverage for the .env newline-injection bug in the config editor.

_write_env_key() wrote form values into .env verbatim. A value like
"100\\nTRD_ENV=REAL" would inject a second, attacker-chosen KEY=VALUE line
into .env outside the _EDITABLE_KEYS allowlist — the worst case (flipping
TRD_ENV/LIVE_TRADING_ENABLED) is independently caught by
mm.config.validate_config() at runner startup, but the injection itself was
still a real bug. Fixed 2026-06-22 by rejecting embedded \\n/\\r.
"""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import web_dashboard  # noqa: E402


def _reload_with_env(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("MAX_DAILY_LOSS=50\n")
    monkeypatch.setattr(web_dashboard, "_ENV_PATH", env_path)
    return env_path


def test_write_env_key_rejects_embedded_newline(tmp_path, monkeypatch):
    env_path = _reload_with_env(tmp_path, monkeypatch)
    ok = web_dashboard._write_env_key("MAX_DAILY_LOSS", "100\nTRD_ENV=REAL")
    assert ok is False
    assert "TRD_ENV" not in env_path.read_text()


def test_write_env_key_rejects_embedded_carriage_return(tmp_path, monkeypatch):
    env_path = _reload_with_env(tmp_path, monkeypatch)
    ok = web_dashboard._write_env_key("MAX_DAILY_LOSS", "100\rLIVE_TRADING_ENABLED=true")
    assert ok is False
    assert "LIVE_TRADING_ENABLED" not in env_path.read_text()


def test_write_env_key_accepts_normal_value(tmp_path, monkeypatch):
    env_path = _reload_with_env(tmp_path, monkeypatch)
    ok = web_dashboard._write_env_key("MAX_DAILY_LOSS", "75")
    assert ok is True
    assert "MAX_DAILY_LOSS=75" in env_path.read_text()


def test_write_env_key_rejects_unlisted_key(tmp_path, monkeypatch):
    env_path = _reload_with_env(tmp_path, monkeypatch)
    ok = web_dashboard._write_env_key("DASHBOARD_PASSWORD", "newpass")
    assert ok is False
    assert "DASHBOARD_PASSWORD" not in env_path.read_text()


def test_api_stats_requires_login_when_auth_configured(monkeypatch):
    """/api/stats exposes the host's process list, memory and disk (locked 2026-09-17)."""
    monkeypatch.setattr(web_dashboard, "_auth_configured", lambda: True)
    client = web_dashboard.app.test_client()
    r = client.get("/api/stats")
    assert r.status_code == 401 and r.get_json() == {"error": "login required"}
    with client.session_transaction() as s:
        s["logged_in"] = True
    assert client.get("/api/stats").status_code == 200


def test_public_read_only_apis_stay_public(monkeypatch):
    monkeypatch.setattr(web_dashboard, "_auth_configured", lambda: True)
    client = web_dashboard.app.test_client()
    assert client.get("/api/scoreboard").status_code == 200

"""Regression coverage for the module-ref-staleness bug class.

`from .config import cfg` binds the name `cfg` to whatever Config instance
exists at import time. If something later does `mm.config.cfg = Config()`
(a full reassignment, as tests' `_reload_paper`-style helpers do, and as
mm.config itself would do on a real .env reload), any module still holding
the old binding silently keeps reading stale values forever. The fix is
`from . import config as _config` + fetching `_config.cfg.*` at call time.

Found 2026-06-18 via fork audit: mm/vwap_strategy.py, mm/health.py,
mm/logger.py, mm/notifications.py, mm/connection.py, mm/risk.py (partially)
were still on the unsafe pattern. This test simulates the exact failure mode
(reassigning mm.config.cfg to a brand-new instance, without reloading the
consumer module) and asserts the fixed modules notice the swap.
"""
import mm.config
from mm import connection, health, notifications, risk, vwap_strategy


def _swap_cfg(monkeypatch, **overrides):
    """Reassign mm.config.cfg to a new Config instance with overridden fields.

    Mirrors what a real config reload does — NOT the same as monkeypatching
    an attribute on the existing object (which every module would see fine
    regardless of import style; that's not what this bug class is about).
    """
    new_cfg = mm.config.Config()
    for k, v in overrides.items():
        object.__setattr__(new_cfg, k, v) if hasattr(type(new_cfg), "__slots__") else setattr(new_cfg, k, v)
    monkeypatch.setattr(mm.config, "cfg", new_cfg)
    return new_cfg


def test_health_check_socket_picks_up_swapped_cfg(monkeypatch):
    new_cfg = _swap_cfg(monkeypatch, host="10.10.10.10", port=99999)
    seen = {}

    def fake_create_connection(addr, timeout):
        seen["addr"] = addr
        raise OSError("not a real connection, just capturing args")

    monkeypatch.setattr(health.socket, "create_connection", fake_create_connection)
    health.check_socket()
    assert seen["addr"] == (new_cfg.host, new_cfg.port)


def test_connection_quote_context_picks_up_swapped_cfg(monkeypatch):
    new_cfg = _swap_cfg(monkeypatch, host="10.10.10.10", port=88888)
    seen = {}

    class FakeCtx:
        def close(self):
            pass

    def fake_open_quote_context(host, port):
        seen["host"], seen["port"] = host, port
        return FakeCtx()

    monkeypatch.setattr(connection, "OpenQuoteContext", fake_open_quote_context)
    with connection.quote_context():
        pass
    assert (seen["host"], seen["port"]) == (new_cfg.host, new_cfg.port)


def test_notifications_post_picks_up_swapped_cfg(monkeypatch):
    _swap_cfg(monkeypatch, discord_webhook_url="")
    calls = []
    monkeypatch.setattr(notifications.urllib.request, "urlopen",
                        lambda *a, **k: calls.append(1))
    notifications.notify("test")
    assert calls == []  # empty webhook URL on the swapped cfg → no-op

    new_cfg = _swap_cfg(monkeypatch, discord_webhook_url="https://discord.com/api/webhooks/x")
    seen = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr(notifications.urllib.request, "urlopen", fake_urlopen)
    notifications.notify("test")
    assert seen["url"] == new_cfg.discord_webhook_url


def test_risk_live_trading_blocked_picks_up_swapped_cfg(monkeypatch):
    _swap_cfg(monkeypatch, live_trading_enabled=True)
    assert risk.live_trading_blocked() is True

    _swap_cfg(monkeypatch, live_trading_enabled=False)
    assert risk.live_trading_blocked() is False


def test_risk_daily_tracker_picks_up_swapped_cfg(monkeypatch):
    _swap_cfg(monkeypatch, max_trades_per_day=1, max_daily_loss=20.0,
              max_trades_per_strategy=0)
    monkeypatch.setattr(risk.clock, "today", lambda: __import__("datetime").date(2026, 1, 1))
    tracker = risk.DailyTracker()
    assert tracker.can_open() is True
    tracker.record_trade(1.0)
    assert tracker.can_open() is False  # hit max_trades_per_day=1 on the swapped cfg


def test_vwap_strategy_picks_up_swapped_cfg(monkeypatch):
    import pandas as pd
    _swap_cfg(monkeypatch, vwap_stop_mult=2.5)
    df = pd.DataFrame({
        "time_key": pd.date_range("2026-01-02 09:30", periods=1, freq="5min"),
        "open": [100.0], "high": [100.0], "low": [100.0], "close": [100.0],
        "volume": [1000],
    })
    monkeypatch.setattr(vwap_strategy, "compute_vwap_signals", lambda d: d.assign(
        vwap_signal=vwap_strategy.VWAPSignal.NONE))
    # Doesn't need to trade — just must not blow up reading the swapped cfg's
    # vwap_stop_mult instead of a stale pre-swap binding.
    vwap_strategy.run_vwap_signals(df)

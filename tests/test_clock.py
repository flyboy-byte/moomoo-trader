"""Tests for mm/clock.py — the time seam.

Regression coverage for the 2026-06-18 bug fix: today() used to return
date.today() (local system date) instead of the ET trading-day date, despite
every caller (DailyTracker's daily-limit reset, ORB's once-per-day guard,
session-rollover detection, EOD-summary date) being keyed to the ET trading
day. See docs/strategy_graveyard.md "clock.today() Wrong Date Basis".
"""
from datetime import datetime

from mm import clock


def test_today_matches_now_et_date(monkeypatch):
    fake_et = datetime(2026, 6, 18, 23, 30, 0)  # late evening ET
    monkeypatch.setattr(clock, "now_et", lambda: fake_et)
    assert clock.today() == fake_et.date()


def test_today_does_not_use_local_system_date(monkeypatch):
    """The bug: today() used to ignore now_et() entirely. Pin now_et() to a
    date far from "real" today and confirm today() actually tracks it,
    rather than silently falling back to date.today()."""
    fake_et = datetime(2030, 1, 1, 12, 0, 0)
    monkeypatch.setattr(clock, "now_et", lambda: fake_et)
    assert clock.today() == fake_et.date()

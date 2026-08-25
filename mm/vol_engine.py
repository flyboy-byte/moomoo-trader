"""
Deterministic volatility term-structure engine — no AI, pure math.

The project's only volatility signal used to be yesterday's settled VIX close
(scripts/fetch_vix_morning.py). That's one scalar collapsing a lot of distinct
information: term structure (is short-term vol elevated relative to 30-day?),
vol-of-vol (is the options market pricing uncertainty about volatility itself?),
and cross-asset divergence (SPY/QQQ/IWM don't share one volatility regime — the
project's own per-symbol VIX overrides already prove that).

This module fetches a wider set of Cboe volatility indices via yfinance (free,
already a project dependency — see scripts/fetch_vix_morning.py) and produces a
deterministic classification. No LLM call happens here; this is the data layer
that later feeds mm.morning_regime's AI classifier as additional context.

IMPORTANT — threshold-calibration limitation (verified 2026-08-25, do not
re-derive): yfinance has full ~5-year daily history for ^VIX, ^VVIX, ^VXN, but
genuinely ZERO historical backfill for ^VIX1D, ^VIX9D, ^VIX3M, ^VIX6M, ^COR1M,
^COR3M — both yf.download(period="5y") and Ticker.history(start=...) return
only the single most recent day for those six tickers. There is no shortcut to
calibrate term-structure ratio buckets (vix1d/vix, vix/vix3m, etc.) from
history; it has to be done the same way this project handles everything else
without backtest data — accumulate forward daily snapshots and calibrate once
there's enough real data (see docs/evaluation_criteria.md's ETA-aware gate
sizing discipline). Until then, this module returns those ratios as raw
numbers only — NOT bucketed into level states. Only vix/vvix/vxn are bucketed,
using real percentile thresholds computed from 5-year yfinance history on
2026-08-25 (see _LEVEL_THRESHOLDS below).

IWM has no small-cap-specific volatility index available for free. ^RVX
(Russell 2000 vol) does not resolve via yfinance under any ticker variant
tried, and OpenD cannot supply it either without a paid Moomoo option-quote
upgrade (tested live against the VPS's OpenD connection 2026-08-25 — see
docs/strategy_graveyard.md). IWM shares the shared VIX-family signal for now.

Source: yfinance (free, no API key, already a project dependency).
"""
from __future__ import annotations

# yfinance ticker -> field name. All 9 fetched every call; a failed ticker
# returns None for that field (fail-open per ticker, not per fetch — mirrors
# fetch_vix_morning.py's fail-open philosophy).
TICKERS: dict[str, str] = {
    "vix": "^VIX",
    "vix1d": "^VIX1D",
    "vix9d": "^VIX9D",
    "vix3m": "^VIX3M",
    "vix6m": "^VIX6M",
    "vvix": "^VVIX",
    "vxn": "^VXN",
    "cor1m": "^COR1M",
    "cor3m": "^COR3M",
}

# Percentile-based thresholds computed from 5-year yfinance history, 2026-08-25.
# Quartile/p90 cuts from the real observed distribution, not guessed round
# numbers (this project's own convention — see e.g. ADX<25 regime filter,
# calibrated the same way). Recompute periodically as more history accrues;
# not a strategy knob (no knob-freeze exception needed to refresh these).
_LEVEL_THRESHOLDS: dict[str, dict[str, float]] = {
    "vix": {"p25": 15.41, "p75": 21.77, "p90": 26.94},
    "vvix": {"p25": 87.53, "p75": 106.91, "p90": 118.59},
    "vxn": {"p25": 19.47, "p75": 27.26, "p90": 32.45},
}


def _level_bucket(field: str, value: float | None) -> str | None:
    """low / normal / elevated / extreme from real percentile cuts. None if
    the field has no calibrated thresholds (term-structure ratios) or the
    value itself is missing (fetch failure)."""
    if value is None or field not in _LEVEL_THRESHOLDS:
        return None
    t = _LEVEL_THRESHOLDS[field]
    if value < t["p25"]:
        return "low"
    if value < t["p75"]:
        return "normal"
    if value < t["p90"]:
        return "elevated"
    return "extreme"


def fetch_vol_levels() -> dict[str, float | None]:
    """Fetch current values for all 9 tickers via yfinance. Fail-open per
    ticker: one bad ticker returns None for that field, doesn't abort the
    whole fetch."""
    import warnings

    import yfinance as yf
    warnings.filterwarnings("ignore")

    levels: dict[str, float | None] = {}
    for field, ticker in TICKERS.items():
        try:
            df = yf.download(ticker, period="5d", progress=False, auto_adjust=False)
            if df.empty:
                levels[field] = None
                continue
            close = df["Close"]
            if hasattr(close, "iloc") and close.ndim > 1:
                close = close.iloc[:, 0]
            close = close.dropna()
            levels[field] = round(float(close.iloc[-1]), 2) if not close.empty else None
        except Exception:
            levels[field] = None
    return levels


def compute_vol_state(levels: dict[str, float | None]) -> dict:
    """Deterministic classification from raw levels — no AI, pure math.

    Returns:
      levels: the raw input, unchanged (for logging/audit)
      ratios: term-structure ratios as raw floats, NOT bucketed (see module
        docstring on why — no historical backfill to calibrate cuts from yet)
      buckets: level classification for vix/vvix/vxn (calibrated, real
        thresholds) plus per-symbol assignment: spy_level uses vix, qqq_level
        uses vxn, iwm_level uses vix (no RVX-equivalent available — shares
        the SPY bucket, not a distinct small-cap signal)
    """
    vix = levels.get("vix")
    vix1d = levels.get("vix1d")
    vix9d = levels.get("vix9d")
    vix3m = levels.get("vix3m")
    vvix = levels.get("vvix")
    vxn = levels.get("vxn")

    def _ratio(a: float | None, b: float | None) -> float | None:
        return round(a / b, 3) if a is not None and b not in (None, 0) else None

    return {
        "levels": levels,
        "ratios": {
            "vix1d_over_vix": _ratio(vix1d, vix),
            "vix9d_over_vix": _ratio(vix9d, vix),
            "vix_over_vix3m": _ratio(vix, vix3m),
            "vxn_over_vix": _ratio(vxn, vix),
        },
        "buckets": {
            "spy_level": _level_bucket("vix", vix),
            "qqq_level": _level_bucket("vxn", vxn),
            "iwm_level": _level_bucket("vix", vix),
            "vol_of_vol": _level_bucket("vvix", vvix),
        },
    }

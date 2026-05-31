"""
Tests for mm/indicators.py and mm/signals.py.

Covers: output shape/columns, no-crash behavior, KDJ cross detection,
signal score calculation, and edge cases.
"""
import numpy as np
import pandas as pd
import pytest

from mm.indicators import bollinger_bands, atr, kdj, rsi, adx, add_all, kdj_golden_cross, kdj_death_cross, bb_width_percentile, BB_PERCENTILE_WINDOW
from mm.signals import score_df, snapshot, SIGNALS, RSI_OVERSOLD, ADX_RANGING, VOLUME_SPIKE_MULT


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_candles(n: int = 50, base: float = 100.0, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = base + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0.1, 0.5, n)
    low = close - rng.uniform(0.1, 0.5, n)
    open_ = close + rng.normal(0, 0.2, n)
    volume = rng.uniform(1_000_000, 3_000_000, n)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    })


def _make_candles_trending_down(n: int = 50) -> pd.DataFrame:
    """Candles with a clear downtrend — close near low repeatedly."""
    close = np.linspace(120, 80, n)
    return pd.DataFrame({
        "open": close + 0.2,
        "high": close + 0.5,
        "low": close - 0.1,
        "close": close,
        "volume": np.full(n, 1_500_000.0),
    })


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

class TestBollingerBands:
    def test_columns_added(self):
        df = bollinger_bands(_make_candles())
        for col in ("bb_upper", "bb_middle", "bb_lower", "bb_width"):
            assert col in df.columns, f"missing column: {col}"

    def test_original_columns_preserved(self):
        df = _make_candles()
        out = bollinger_bands(df)
        for col in df.columns:
            assert col in out.columns

    def test_row_count_unchanged(self):
        df = _make_candles(60)
        assert len(bollinger_bands(df)) == 60

    def test_middle_is_rolling_mean(self):
        df = _make_candles()
        out = bollinger_bands(df, period=20)
        expected = df["close"].rolling(20).mean()
        pd.testing.assert_series_equal(out["bb_middle"].dropna(), expected.dropna(), check_names=False)

    def test_upper_above_middle(self):
        out = bollinger_bands(_make_candles()).dropna()
        assert (out["bb_upper"] > out["bb_middle"]).all()

    def test_lower_below_middle(self):
        out = bollinger_bands(_make_candles()).dropna()
        assert (out["bb_lower"] < out["bb_middle"]).all()

    def test_width_equals_upper_minus_lower(self):
        out = bollinger_bands(_make_candles()).dropna()
        pd.testing.assert_series_equal(
            out["bb_width"], out["bb_upper"] - out["bb_lower"], check_names=False
        )

    def test_nan_for_first_period_minus_one_rows(self):
        out = bollinger_bands(_make_candles(50), period=20)
        assert out["bb_middle"].iloc[:19].isna().all()
        assert out["bb_middle"].iloc[19:].notna().all()

    def test_does_not_mutate_input(self):
        df = _make_candles()
        original_cols = set(df.columns)
        bollinger_bands(df)
        assert set(df.columns) == original_cols


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

class TestATR:
    def test_column_added(self):
        assert "atr" in atr(_make_candles()).columns

    def test_row_count_unchanged(self):
        df = _make_candles(60)
        assert len(atr(df)) == 60

    def test_atr_non_negative(self):
        out = atr(_make_candles()).dropna()
        assert (out["atr"] >= 0).all()

    def test_atr_positive_for_volatile_data(self):
        # ta library initializes ATR with zeros for the warm-up period (not NaN).
        # Check only the warmed-up rows (period=14, so skip first 14).
        out = atr(_make_candles(), period=14)
        assert (out["atr"].iloc[14:] > 0).all()

    def test_does_not_mutate_input(self):
        df = _make_candles()
        original_cols = set(df.columns)
        atr(df)
        assert set(df.columns) == original_cols


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

class TestRSI:
    def test_column_added(self):
        assert "rsi" in rsi(_make_candles()).columns

    def test_rsi_bounds(self):
        out = rsi(_make_candles()).dropna()
        assert (out["rsi"] >= 0).all()
        assert (out["rsi"] <= 100).all()

    def test_row_count_unchanged(self):
        df = _make_candles(60)
        assert len(rsi(df)) == 60

    def test_trending_down_gives_low_rsi(self):
        """A consistent downtrend should push RSI well below 50."""
        out = rsi(_make_candles_trending_down(), period=14).dropna()
        assert out["rsi"].iloc[-1] < 50


# ---------------------------------------------------------------------------
# ADX
# ---------------------------------------------------------------------------

class TestADX:
    def test_column_added(self):
        assert "adx" in adx(_make_candles()).columns

    def test_adx_non_negative(self):
        out = adx(_make_candles()).dropna()
        assert (out["adx"] >= 0).all()

    def test_row_count_unchanged(self):
        df = _make_candles(60)
        assert len(adx(df)) == 60


# ---------------------------------------------------------------------------
# KDJ
# ---------------------------------------------------------------------------

class TestKDJ:
    def test_columns_added(self):
        out = kdj(_make_candles())
        for col in ("kdj_k", "kdj_d", "kdj_j"):
            assert col in out.columns

    def test_row_count_unchanged(self):
        df = _make_candles(60)
        assert len(kdj(df)) == 60

    def test_j_equals_3k_minus_2d(self):
        out = kdj(_make_candles()).dropna()
        expected = 3 * out["kdj_k"] - 2 * out["kdj_d"]
        pd.testing.assert_series_equal(out["kdj_j"], expected, check_names=False)

    def test_does_not_mutate_input(self):
        df = _make_candles()
        original_cols = set(df.columns)
        kdj(df)
        assert set(df.columns) == original_cols


# ---------------------------------------------------------------------------
# KDJ cross detection
# ---------------------------------------------------------------------------

class TestKDJCross:
    def _df_with_forced_cross(self, golden: bool) -> pd.DataFrame:
        """Build a DataFrame where K crosses D exactly once at index 30."""
        n = 40
        k = np.full(n, 50.0)
        d = np.full(n, 50.0)
        if golden:
            k[:30] = 45.0; d[:30] = 48.0   # K below D before
            k[30:] = 52.0; d[30:] = 48.0   # K above D after (golden cross at 30)
        else:
            k[:30] = 52.0; d[:30] = 48.0   # K above D before
            k[30:] = 45.0; d[30:] = 48.0   # K below D after (death cross at 30)
        df = _make_candles(n)
        df["kdj_k"] = k
        df["kdj_d"] = d
        return df

    def test_golden_cross_detected(self):
        df = self._df_with_forced_cross(golden=True)
        cross = kdj_golden_cross(df)
        assert cross.iloc[30] is True or cross.iloc[30] == True

    def test_golden_cross_only_on_transition(self):
        df = self._df_with_forced_cross(golden=True)
        cross = kdj_golden_cross(df)
        assert cross.sum() == 1

    def test_death_cross_detected(self):
        df = self._df_with_forced_cross(golden=False)
        cross = kdj_death_cross(df)
        assert cross.iloc[30] is True or cross.iloc[30] == True

    def test_death_cross_only_on_transition(self):
        df = self._df_with_forced_cross(golden=False)
        cross = kdj_death_cross(df)
        assert cross.sum() == 1

    def test_no_false_golden_when_k_always_above(self):
        df = _make_candles(40)
        df["kdj_k"] = 60.0
        df["kdj_d"] = 50.0
        assert kdj_golden_cross(df).sum() == 0

    def test_no_false_death_when_k_always_below(self):
        df = _make_candles(40)
        df["kdj_k"] = 40.0
        df["kdj_d"] = 50.0
        assert kdj_death_cross(df).sum() == 0


# ---------------------------------------------------------------------------
# add_all — integration
# ---------------------------------------------------------------------------

class TestBBWidthPercentile:
    def test_column_added(self):
        df = bollinger_bands(_make_candles(100))
        out = bb_width_percentile(df)
        assert "bb_width_pct" in out.columns

    def test_values_in_zero_one_range(self):
        df = bollinger_bands(_make_candles(100))
        out = bb_width_percentile(df)
        valid = out["bb_width_pct"].dropna()
        assert (valid >= 0.0).all() and (valid <= 1.0).all()

    def test_nan_before_window(self):
        df = bollinger_bands(_make_candles(100))
        out = bb_width_percentile(df, window=BB_PERCENTILE_WINDOW)
        # NaN for the first (window-1) rows where bb_width itself may be NaN
        # (actually NaN until bb_width has enough history — bb warmup + pct warmup)
        assert out["bb_width_pct"].iloc[:BB_PERCENTILE_WINDOW - 1].isna().all()

    def test_does_not_mutate_input(self):
        df = bollinger_bands(_make_candles(100))
        original_cols = set(df.columns)
        bb_width_percentile(df)
        assert set(df.columns) == original_cols


class TestAddAll:
    EXPECTED_COLS = {
        "bb_upper", "bb_middle", "bb_lower", "bb_width", "bb_width_pct",
        "atr", "kdj_k", "kdj_d", "kdj_j",
        "kdj_golden_cross", "kdj_death_cross",
        "rsi", "adx", "volume_ma",
    }

    def test_all_columns_present(self):
        out = add_all(_make_candles(60))
        for col in self.EXPECTED_COLS:
            assert col in out.columns, f"missing: {col}"

    def test_row_count_unchanged(self):
        df = _make_candles(60)
        assert len(add_all(df)) == 60

    def test_does_not_mutate_input(self):
        df = _make_candles(60)
        original_cols = set(df.columns)
        add_all(df)
        assert set(df.columns) == original_cols


# ---------------------------------------------------------------------------
# Signal scoring
# ---------------------------------------------------------------------------

class TestSignalScore:
    def _scored_df(self, **overrides) -> pd.DataFrame:
        df = add_all(_make_candles(60))
        for col, val in overrides.items():
            df[col] = val
        return score_df(df)

    def test_score_columns_added(self):
        out = self._scored_df()
        for name in SIGNALS:
            assert f"sig_{name}" in out.columns
        assert "signal_score" in out.columns

    def test_score_zero_when_no_signals(self):
        # Force all signals off
        out = self._scored_df(
            close=200.0,            # well above bb_lower → no bb_touch
            kdj_golden_cross=False,
            rsi=60.0,               # not oversold
            adx=40.0,               # trending
            volume=100.0,           # low volume
            volume_ma=1_000_000.0,
        )
        assert (out["signal_score"] == 0).all()

    def test_score_max_when_all_signals(self):
        df = add_all(_make_candles(60))
        # Force all signals on
        df["close"] = df["bb_lower"] - 0.01
        df["kdj_golden_cross"] = True
        df["rsi"] = RSI_OVERSOLD - 1
        df["adx"] = ADX_RANGING - 1
        df["volume"] = df["volume_ma"] * (VOLUME_SPIKE_MULT + 0.5)
        out = score_df(df)
        # bb_lower and volume_ma are NaN until warm-up completes (period=20).
        # Check only the warmed-up rows.
        warmed = out.iloc[20:]
        assert (warmed["signal_score"] == len(SIGNALS)).all()

    def test_score_is_integer(self):
        out = self._scored_df()
        assert out["signal_score"].dtype in (int, np.int64, np.int32)

    def test_score_range(self):
        out = self._scored_df()
        assert out["signal_score"].between(0, len(SIGNALS)).all()

    def test_adding_signal_increases_score(self):
        df = add_all(_make_candles(60))
        df["close"] = df["bb_lower"] - 0.01   # bb_touch on
        df["kdj_golden_cross"] = False
        df["rsi"] = 60.0
        df["adx"] = 40.0
        df["volume"] = 100.0
        df["volume_ma"] = 1_000_000.0

        score_one = score_df(df)["signal_score"].iloc[-1]

        df["rsi"] = RSI_OVERSOLD - 1           # rsi_oversold on
        score_two = score_df(df)["signal_score"].iloc[-1]

        assert score_two == score_one + 1


# ---------------------------------------------------------------------------
# Signal snapshot (single-row eval used by paper runner)
# ---------------------------------------------------------------------------

class TestSignalSnapshot:
    def test_snapshot_score_matches_df_score(self):
        df = add_all(_make_candles(60))
        df = score_df(df)
        last = df.iloc[-1]
        snap = snapshot(last)
        assert snap.score == int(last["signal_score"])

    def test_snapshot_details_keys(self):
        df = add_all(_make_candles(60))
        last = df.iloc[-1]
        snap = snapshot(last)
        assert set(snap.details.keys()) == set(SIGNALS.keys())

    def test_snapshot_pct_range(self):
        df = add_all(_make_candles(60))
        last = df.iloc[-1]
        snap = snapshot(last)
        assert 0.0 <= snap.pct <= 1.0

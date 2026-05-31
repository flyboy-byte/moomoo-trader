import pandas as pd
import numpy as np
from ta.volatility import BollingerBands, AverageTrueRange
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator


def bollinger_bands(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
    price_col: str = "close",
) -> pd.DataFrame:
    bb = BollingerBands(df[price_col], window=period, window_dev=std_dev)
    df = df.copy()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_width"] = df["bb_upper"] - df["bb_lower"]
    return df


def atr(
    df: pd.DataFrame,
    period: int = 14,
) -> pd.DataFrame:
    df = df.copy()
    df["atr"] = AverageTrueRange(df["high"], df["low"], df["close"], window=period).average_true_range()
    return df


def kdj(
    df: pd.DataFrame,
    period: int = 9,
    signal_period: int = 3,
) -> pd.DataFrame:
    # KDJ is a Chinese stochastic oscillator not in standard TA libraries.
    # K = EWM(RSV, alpha=1/signal_period); D = EWM(K); J = 3K - 2D
    low_min = df["low"].rolling(period).min()
    high_max = df["high"].rolling(period).max()
    denom = high_max - low_min
    rsv = ((df["close"] - low_min) / denom.replace(0, np.nan)) * 100

    df = df.copy()
    k = rsv.ewm(alpha=1 / signal_period, adjust=False).mean()
    d = k.ewm(alpha=1 / signal_period, adjust=False).mean()
    df["kdj_k"] = k
    df["kdj_d"] = d
    df["kdj_j"] = 3 * k - 2 * d
    return df


def kdj_golden_cross(df: pd.DataFrame) -> pd.Series:
    k, d = df["kdj_k"], df["kdj_d"]
    return ((k > d) & (k.shift(1) <= d.shift(1))).rename("kdj_golden_cross")


def kdj_death_cross(df: pd.DataFrame) -> pd.Series:
    k, d = df["kdj_k"], df["kdj_d"]
    return ((k < d) & (k.shift(1) >= d.shift(1))).rename("kdj_death_cross")


def rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    df = df.copy()
    df["rsi"] = RSIIndicator(df["close"], window=period).rsi()
    return df


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    df = df.copy()
    df["adx"] = ADXIndicator(df["high"], df["low"], df["close"], window=period).adx()
    return df


BB_PERCENTILE_WINDOW: int = 50


def bb_width_percentile(df: pd.DataFrame, window: int = BB_PERCENTILE_WINDOW) -> pd.DataFrame:
    """Add bb_width_pct: rolling percentile rank of current BB width (0=narrowest, 1=widest).

    Values near 0 = bands are contracted relative to recent history (ranging market).
    Values near 1 = bands are expanded (volatile/trending market).
    Requires bb_width column (added by bollinger_bands).
    """
    df = df.copy()
    df["bb_width_pct"] = df["bb_width"].rolling(window).rank(pct=True)
    return df


def add_all(df: pd.DataFrame) -> pd.DataFrame:
    """Add all indicators used by the signal engine."""
    df = bollinger_bands(df)
    df = bb_width_percentile(df)
    df = atr(df)
    df = kdj(df)
    df["kdj_golden_cross"] = kdj_golden_cross(df)
    df["kdj_death_cross"] = kdj_death_cross(df)
    df = rsi(df)
    df = adx(df)
    df["volume_ma"] = df["volume"].rolling(20).mean()
    return df

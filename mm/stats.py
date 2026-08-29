"""Sampling uncertainty for trade statistics.

The 2026-08-29 audit's second finding: this project reports profit factor as though it
were a measurement, with no indication of how much of it is noise. At n=106 trades and an
average of +$0.08/trade, every PF in the live report is consistent with zero edge — but
nothing in the output said so, so PF 1.123 read as "slightly profitable" rather than
"indistinguishable from nothing".

Bootstrap rather than a parametric test, because trade PnL distributions here are sharply
non-normal: bounded losses (ATR stops), a long right tail (one ORB runner was +$14 of a
+$2.30 strategy total), and heavy mass near zero. A t-test on that shape understates the
interval. Resampling makes no distributional assumption.

Used by scripts/analyze_trades.py. See docs/research-reset.md Goal A4.
"""
from __future__ import annotations

import numpy as np

# The canonical PF calc, NOT a local reimplementation. mm/backtest.py's docstring records
# that this metric was independently rewritten in ~8 places with two silently-diverged
# conventions (pnl==0 as loss vs. as neither; 999.0 vs inf sentinel), consolidated
# 2026-06-18, and guarded by tests/test_metric_consistency.py. Re-exported here so callers
# working in bps/net-PnL space get uncertainty and the point estimate from one import
# without being tempted to write a ninth version.
from .backtest import profit_factor  # noqa: F401  (re-export)

# Fixed seed: the same trades must always produce the same interval, or two runs of the
# same report disagree and neither can be cited. Bootstrap noise is not information.
_SEED = 20260829

DEFAULT_N_BOOT = 10_000


def _resample_matrix(arr: np.ndarray, n_boot: int) -> np.ndarray:
    rng = np.random.default_rng(_SEED)
    idx = rng.integers(0, arr.size, size=(n_boot, arr.size))
    return arr[idx]


def bootstrap_pf_ci(
    pnls,
    n_boot: int = DEFAULT_N_BOOT,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap CI for profit factor. Returns (lo, hi); (nan, nan) if n < 2.

    Resamples whose gross loss is zero give PF=inf; those are kept rather than dropped,
    since discarding them would bias the upper bound downward.

    method="nearest" is required, not cosmetic: the default linear interpolation computes
    (b - a) between neighbouring order statistics, and inf - inf is nan. On a small,
    mostly-winning sample enough resamples are inf that the upper percentile lands in that
    region and the whole interval silently becomes nan. Picking an actual order statistic
    instead yields inf, which is the truthful answer — "the upper bound is unbounded at
    this sample size" — and is exactly the kind of honest width this module exists for.
    """
    arr = np.asarray([p for p in pnls if p is not None], dtype=float)
    if arr.size < 2:
        return (float("nan"), float("nan"))
    sample = _resample_matrix(arr, n_boot)
    # `<= 0` counts as loss, and gross_loss==0 -> inf: both match
    # mm.backtest.profit_factor exactly. A bootstrap that used a different convention
    # from the point estimate it brackets would produce intervals that don't contain it.
    gross_win = np.where(sample > 0, sample, 0.0).sum(axis=1)
    gross_loss = -np.where(sample <= 0, sample, 0.0).sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        pf = np.where(gross_loss > 0, gross_win / gross_loss, np.inf)
    pf = pf[~np.isnan(pf)]
    if pf.size == 0:
        return (float("nan"), float("nan"))
    return (float(np.percentile(pf, 100 * alpha / 2, method="nearest")),
            float(np.percentile(pf, 100 * (1 - alpha / 2), method="nearest")))


def bootstrap_mean_ci(
    values,
    n_boot: int = DEFAULT_N_BOOT,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean. Returns (lo, hi); (nan, nan) if n < 2."""
    arr = np.asarray([v for v in values if v is not None], dtype=float)
    if arr.size < 2:
        return (float("nan"), float("nan"))
    means = _resample_matrix(arr, n_boot).mean(axis=1)
    return (float(np.percentile(means, 100 * alpha / 2)),
            float(np.percentile(means, 100 * (1 - alpha / 2))))


def prob_positive(values, n_boot: int = DEFAULT_N_BOOT) -> float:
    """Fraction of bootstrap resamples whose mean is > 0.

    Reported instead of a p-value because it answers the question actually being asked
    ("how confident am I that this is better than nothing?") without inviting the
    0.05-threshold ritual. Not a Bayesian posterior — it is a resampling frequency, and
    with n=106 it will sit near 0.5 for anything in this repo. That is the point.
    """
    arr = np.asarray([v for v in values if v is not None], dtype=float)
    if arr.size < 2:
        return float("nan")
    means = _resample_matrix(arr, n_boot).mean(axis=1)
    return float((means > 0).mean())


def summarize(pnls, n_boot: int = DEFAULT_N_BOOT) -> dict:
    """One call for the full uncertainty picture on a set of trade PnLs."""
    arr = [p for p in pnls if p is not None]
    pf_lo, pf_hi = bootstrap_pf_ci(arr, n_boot)
    m_lo, m_hi = bootstrap_mean_ci(arr, n_boot)
    return {
        "n": len(arr),
        "total": float(sum(arr)) if arr else 0.0,
        "mean": float(np.mean(arr)) if arr else float("nan"),
        "pf": profit_factor(arr),
        "pf_ci": (pf_lo, pf_hi),
        "mean_ci": (m_lo, m_hi),
        "prob_positive": prob_positive(arr, n_boot),
    }

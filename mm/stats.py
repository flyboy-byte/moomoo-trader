"""Sampling uncertainty for trade statistics.

The 2026-08-29 audit's second finding: this project reports profit factor as though it
were a measurement, with no indication of how much of it is noise. At n=106 trades and an
average of +$0.08/trade, every PF in the live report is consistent with zero edge — but
nothing in the output said so, so PF 1.123 read as "slightly profitable" rather than
"indistinguishable from nothing".

Bootstrap rather than a parametric test, because trade PnL distributions here are sharply
non-normal: bounded losses (ATR stops), a long right tail (one ORB runner was +$14 of a
+$2.30 strategy total), and heavy mass near zero. A t-test on that shape understates the
interval. Resampling makes no distributional assumption. For pooled cross-symbol results,
trades from one market day are not independent observations; pass matching ``block_keys``
so an entire day moves together. Single-symbol reports retain the original i.i.d. path.

Used by scripts/analyze_trades.py and scripts/web_dashboard.py. See
docs/research-reset.md Goal A4 and docs/PLAN.md Step 4.
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


def _clean_values(values, block_keys=None) -> tuple[np.ndarray, np.ndarray | None]:
    raw = list(values)
    if block_keys is None:
        return np.asarray([value for value in raw if value is not None], dtype=float), None

    keys = list(block_keys)
    if len(keys) != len(raw):
        raise ValueError("block_keys must have the same length as values")
    kept = [(value, key) for value, key in zip(raw, keys, strict=True) if value is not None]
    if any(key is None for _, key in kept):
        raise ValueError("block keys cannot be None for retained values")
    return (
        np.asarray([value for value, _ in kept], dtype=float),
        np.asarray([key for _, key in kept], dtype=object),
    )


def _block_aggregates(arr: np.ndarray, block_keys: np.ndarray) -> dict[str, np.ndarray]:
    """Aggregate trade statistics by block before resampling whole blocks."""
    codes_by_key: dict[object, int] = {}
    codes = np.empty(arr.size, dtype=int)
    for i, key in enumerate(block_keys):
        codes[i] = codes_by_key.setdefault(key, len(codes_by_key))
    n_blocks = len(codes_by_key)
    return {
        "total": np.bincount(codes, weights=arr, minlength=n_blocks),
        "count": np.bincount(codes, minlength=n_blocks),
        "gross_win": np.bincount(codes, weights=np.where(arr > 0, arr, 0.0), minlength=n_blocks),
        "gross_loss": np.bincount(
            codes, weights=-np.where(arr <= 0, arr, 0.0), minlength=n_blocks
        ),
    }


def _resample_block_aggregates(
    arr: np.ndarray, block_keys: np.ndarray, n_boot: int
) -> dict[str, np.ndarray]:
    aggregates = _block_aggregates(arr, block_keys)
    n_blocks = aggregates["total"].size
    rng = np.random.default_rng(_SEED)
    sampled_blocks = rng.integers(0, n_blocks, size=(n_boot, n_blocks))
    return {name: values[sampled_blocks].sum(axis=1) for name, values in aggregates.items()}


def _too_few_observations(arr: np.ndarray, block_keys: np.ndarray | None) -> bool:
    if arr.size < 2:
        return True
    return block_keys is not None and len(set(block_keys.tolist())) < 2


def bootstrap_pf_ci(
    pnls,
    n_boot: int = DEFAULT_N_BOOT,
    alpha: float = 0.05,
    block_keys=None,
) -> tuple[float, float]:
    """Percentile bootstrap CI for PF; optionally resample aligned ``block_keys``.

    Returns (lo, hi); (nan, nan) if fewer than two trades or requested blocks exist.

    Resamples whose gross loss is zero give PF=inf; those are kept rather than dropped,
    since discarding them would bias the upper bound downward.

    method="nearest" is required, not cosmetic: the default linear interpolation computes
    (b - a) between neighbouring order statistics, and inf - inf is nan. On a small,
    mostly-winning sample enough resamples are inf that the upper percentile lands in that
    region and the whole interval silently becomes nan. Picking an actual order statistic
    instead yields inf, which is the truthful answer — "the upper bound is unbounded at
    this sample size" — and is exactly the kind of honest width this module exists for.
    """
    arr, keys = _clean_values(pnls, block_keys)
    if _too_few_observations(arr, keys):
        return (float("nan"), float("nan"))
    if keys is None:
        sample = _resample_matrix(arr, n_boot)
        gross_win = np.where(sample > 0, sample, 0.0).sum(axis=1)
        gross_loss = -np.where(sample <= 0, sample, 0.0).sum(axis=1)
    else:
        sampled = _resample_block_aggregates(arr, keys, n_boot)
        gross_win = sampled["gross_win"]
        gross_loss = sampled["gross_loss"]
    # `<= 0` counts as loss, and gross_loss==0 -> inf: both match
    # mm.backtest.profit_factor exactly. A bootstrap that used a different convention
    # from the point estimate it brackets would produce intervals that don't contain it.
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
    block_keys=None,
) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean, optionally over aligned blocks."""
    arr, keys = _clean_values(values, block_keys)
    if _too_few_observations(arr, keys):
        return (float("nan"), float("nan"))
    if keys is None:
        means = _resample_matrix(arr, n_boot).mean(axis=1)
    else:
        sampled = _resample_block_aggregates(arr, keys, n_boot)
        means = sampled["total"] / sampled["count"]
    return (float(np.percentile(means, 100 * alpha / 2)),
            float(np.percentile(means, 100 * (1 - alpha / 2))))


def prob_positive(values, n_boot: int = DEFAULT_N_BOOT, block_keys=None) -> float:
    """Fraction of bootstrap resamples whose mean is > 0.

    Reported instead of a p-value because it answers the question actually being asked
    ("how confident am I that this is better than nothing?") without inviting the
    0.05-threshold ritual. Not a Bayesian posterior — it is a resampling frequency, and
    with n=106 it will sit near 0.5 for anything in this repo. That is the point.
    """
    arr, keys = _clean_values(values, block_keys)
    if _too_few_observations(arr, keys):
        return float("nan")
    if keys is None:
        means = _resample_matrix(arr, n_boot).mean(axis=1)
    else:
        sampled = _resample_block_aggregates(arr, keys, n_boot)
        means = sampled["total"] / sampled["count"]
    return float((means > 0).mean())


def summarize(pnls, n_boot: int = DEFAULT_N_BOOT, block_keys=None) -> dict:
    """One call for the full uncertainty picture on a set of trade PnLs."""
    raw = list(pnls)
    keys = list(block_keys) if block_keys is not None else None
    arr, _ = _clean_values(raw, keys)
    clean = arr.tolist()
    pf_lo, pf_hi = bootstrap_pf_ci(raw, n_boot, block_keys=keys)
    m_lo, m_hi = bootstrap_mean_ci(raw, n_boot, block_keys=keys)
    return {
        "n": len(clean),
        "total": float(sum(clean)) if clean else 0.0,
        "mean": float(np.mean(clean)) if clean else float("nan"),
        "pf": profit_factor(clean),
        "pf_ci": (pf_lo, pf_hi),
        "mean_ci": (m_lo, m_hi),
        "prob_positive": prob_positive(raw, n_boot, block_keys=keys),
        "bootstrap_method": "block" if keys is not None else "iid",
    }

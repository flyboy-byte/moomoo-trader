"""
Strategy variant research.

Entry variants:
  strict     — close <= bb_lower AND same-bar KDJ golden cross  (live strategy)
  relaxed    — close <= bb_lower AND K > D
  bb_only    — close <= bb_lower
  kdj_only   — KDJ golden cross only

Exit variants (applied to the strict entry to isolate exit impact):
  current    — BB middle OR KDJ death cross OR stop-loss  (live strategy)
  target_stop — BB middle OR stop-loss only  (remove KDJ death cross exit)
  target_only — BB middle exit only  (no stop, no KDJ death cross)
  bars_N     — time-based: exit after N bars regardless
"""
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .indicators import add_all
from .backtest import run_backtest, WindowResult, walk_forward, print_walk_forward
from .logger import get_logger
from .strategy import Signal, Trade

log = get_logger("research")


@dataclass
class VariantResult:
    name: str
    trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    avg_pnl: float
    best: float
    worst: float
    windows: list[WindowResult] = field(default_factory=list)


def _run_variant(df: pd.DataFrame, entry_mask: pd.Series) -> list[Trade]:
    """Generic backtester: uses a custom entry mask but standard exits."""
    from .strategy import Position

    df = add_all(df.copy())
    trades: list[Trade] = []
    position: Position | None = None

    for i, row in df.iterrows():
        if pd.isna(row.get("bb_middle")) or pd.isna(row.get("kdj_k")):
            continue

        if position is None:
            if entry_mask.loc[i]:
                position = Position(
                    entry_idx=i,
                    entry_time=row["time_key"],
                    entry_price=row["close"],
                    stop_price=row["close"] - row["atr"],
                )
        else:
            exit_reason: str | None = None
            if row["close"] >= row["bb_middle"]:
                exit_reason = "EXIT_TARGET"
            elif row["kdj_death_cross"]:
                exit_reason = "EXIT_DEATH_CROSS"
            elif row["close"] < position.stop_price:
                exit_reason = "EXIT_STOP_LOSS"

            if exit_reason:
                trades.append(Trade(
                    entry_time=position.entry_time,
                    entry_price=position.entry_price,
                    exit_time=row["time_key"],
                    exit_price=row["close"],
                    exit_reason=exit_reason,
                ))
                position = None

    return trades


def _summarise(name: str, trades: list[Trade]) -> VariantResult:
    if not trades:
        return VariantResult(name=name, trades=0, wins=0, losses=0,
                             win_rate=0, total_pnl=0, avg_pnl=0, best=0, worst=0)
    wins = [t for t in trades if t.pnl > 0]
    pnls = [t.pnl for t in trades]
    total = sum(pnls)
    return VariantResult(
        name=name,
        trades=len(trades),
        wins=len(wins),
        losses=len(trades) - len(wins),
        win_rate=len(wins) / len(trades) * 100,
        total_pnl=total,
        avg_pnl=total / len(trades),
        best=max(pnls),
        worst=min(pnls),
    )


def compare_variants(df: pd.DataFrame) -> list[VariantResult]:
    df = add_all(df.copy())

    variants = {
        "strict":   (df["close"] <= df["bb_lower"]) & df["kdj_golden_cross"],
        "relaxed":  (df["close"] <= df["bb_lower"]) & (df["kdj_k"] > df["kdj_d"]),
        "bb_only":  df["close"] <= df["bb_lower"],
        "kdj_only": df["kdj_golden_cross"].astype(bool),
    }

    results = []
    for name, mask in variants.items():
        trades = _run_variant(df.copy(), mask)
        r = _summarise(name, trades)
        results.append(r)
        log.info(
            "%-10s  trades=%3d  win=%.1f%%  total=%+.4f  avg=%+.4f  best=%+.4f  worst=%+.4f",
            r.name, r.trades, r.win_rate, r.total_pnl, r.avg_pnl, r.best, r.worst,
        )

    return results


def compare_variants_walk_forward(
    df: pd.DataFrame,
    window_days: int = 30,
) -> dict[str, list[WindowResult]]:
    """Run walk-forward for each variant and return results keyed by variant name."""
    df = add_all(df.copy())

    variants = {
        "strict":   (df["close"] <= df["bb_lower"]) & df["kdj_golden_cross"],
        "relaxed":  (df["close"] <= df["bb_lower"]) & (df["kdj_k"] > df["kdj_d"]),
        "bb_only":  df["close"] <= df["bb_lower"],
        "kdj_only": df["kdj_golden_cross"].astype(bool),
    }

    all_results: dict[str, list[WindowResult]] = {}

    for name, mask in variants.items():
        log.info("=== Walk-forward: %s ===", name)

        df_v = df.copy()
        df_v["_entry"] = mask

        start_ts = df_v["time_key"].iloc[0]
        end_ts = df_v["time_key"].iloc[-1]
        window_results: list[WindowResult] = []
        window_start = start_ts

        while window_start < end_ts:
            window_end = window_start + pd.Timedelta(days=window_days)
            chunk_mask = (df_v["time_key"] >= window_start) & (df_v["time_key"] < window_end)
            chunk = df_v[chunk_mask].reset_index(drop=True)
            label = f"{window_start.strftime('%Y-%m-%d')} → {min(window_end, end_ts).strftime('%Y-%m-%d')}"

            if len(chunk) >= 20:
                entry_m = chunk["_entry"].fillna(False)
                trades = _run_variant(chunk.drop(columns=["_entry"]), entry_m)
                wins = [t for t in trades if t.pnl > 0]
                total_pnl = sum(t.pnl for t in trades) if trades else 0.0
                window_results.append(WindowResult(
                    label=label,
                    start=window_start,
                    end=window_end,
                    candles=len(chunk),
                    trades=len(trades),
                    wins=len(wins),
                    losses=len(trades) - len(wins),
                    total_pnl=total_pnl,
                    avg_pnl=total_pnl / len(trades) if trades else 0.0,
                    win_rate=len(wins) / len(trades) * 100 if trades else 0.0,
                ))

            window_start = window_end

        print_walk_forward(window_results)
        all_results[name] = window_results

    return all_results


def _run_exit_variant(
    df: pd.DataFrame,
    entry_mask: pd.Series,
    use_kdj_death: bool = True,
    use_stop: bool = True,
    exit_after_bars: int | None = None,
) -> list[Trade]:
    """Like _run_variant but with configurable exit conditions."""
    from .strategy import Position

    df = add_all(df.copy())
    trades: list[Trade] = []
    position: Position | None = None
    bars_held = 0

    for i, row in df.iterrows():
        if pd.isna(row.get("bb_middle")) or pd.isna(row.get("kdj_k")):
            continue

        if position is None:
            if entry_mask.loc[i]:
                position = Position(
                    entry_idx=i,
                    entry_time=row["time_key"],
                    entry_price=row["close"],
                    stop_price=row["close"] - row["atr"],
                )
                bars_held = 0
        else:
            bars_held += 1
            exit_reason: str | None = None

            if row["close"] >= row["bb_middle"]:
                exit_reason = "EXIT_TARGET"
            elif use_kdj_death and row["kdj_death_cross"]:
                exit_reason = "EXIT_DEATH_CROSS"
            elif use_stop and row["close"] < position.stop_price:
                exit_reason = "EXIT_STOP_LOSS"
            elif exit_after_bars is not None and bars_held >= exit_after_bars:
                exit_reason = "EXIT_TIME"

            if exit_reason:
                trades.append(Trade(
                    entry_time=position.entry_time,
                    entry_price=position.entry_price,
                    exit_time=row["time_key"],
                    exit_price=row["close"],
                    exit_reason=exit_reason,
                ))
                position = None
                bars_held = 0

    return trades


def compare_exit_variants(df: pd.DataFrame) -> list[VariantResult]:
    """Use the strict entry and test different exit configurations."""
    df = add_all(df.copy())
    strict_entry = (df["close"] <= df["bb_lower"]) & df["kdj_golden_cross"]

    exit_variants: dict[str, dict] = {
        "current":       dict(use_kdj_death=True,  use_stop=True,  exit_after_bars=None),
        "target+stop":   dict(use_kdj_death=False, use_stop=True,  exit_after_bars=None),
        "target_only":   dict(use_kdj_death=False, use_stop=False, exit_after_bars=None),
        "bars_12":       dict(use_kdj_death=False, use_stop=True,  exit_after_bars=12),
        "bars_24":       dict(use_kdj_death=False, use_stop=True,  exit_after_bars=24),
    }

    results = []
    log.info("=== Exit variant comparison (strict entry) ===")
    for name, kwargs in exit_variants.items():
        trades = _run_exit_variant(df.copy(), strict_entry, **kwargs)
        r = _summarise(name, trades)
        results.append(r)
        log.info(
            "%-16s  trades=%3d  win=%.1f%%  total=%+.4f  avg=%+.4f  best=%+.4f  worst=%+.4f",
            r.name, r.trades, r.win_rate, r.total_pnl, r.avg_pnl, r.best, r.worst,
        )

    return results


def _run_parametric(
    df: pd.DataFrame,
    entry_mask: pd.Series,
    atr_mult: float = 1.0,
    entry_tolerance: float = 0.0,
) -> list[Trade]:
    """Backtest with configurable stop width and entry zone.

    entry_tolerance: fraction above bb_lower still accepted as an entry.
                     0.0 = exact touch, 0.002 = within 0.2% above lower band.
    atr_mult: stop = close - atr_mult * ATR.
    """
    from .strategy import Position

    df = add_all(df.copy())
    trades: list[Trade] = []
    position: Position | None = None

    for i, row in df.iterrows():
        if pd.isna(row.get("bb_middle")) or pd.isna(row.get("kdj_k")):
            continue

        if position is None:
            in_zone = row["close"] <= row["bb_lower"] * (1.0 + entry_tolerance)
            if in_zone and entry_mask.loc[i]:
                position = Position(
                    entry_idx=i,
                    entry_time=row["time_key"],
                    entry_price=row["close"],
                    stop_price=row["close"] - atr_mult * row["atr"],
                )
        else:
            exit_reason: str | None = None
            if row["close"] >= row["bb_middle"]:
                exit_reason = "EXIT_TARGET"
            elif row["close"] < position.stop_price:
                exit_reason = "EXIT_STOP_LOSS"

            if exit_reason:
                trades.append(Trade(
                    entry_time=position.entry_time,
                    entry_price=position.entry_price,
                    exit_time=row["time_key"],
                    exit_price=row["close"],
                    exit_reason=exit_reason,
                ))
                position = None

    return trades


def _profit_factor(trades: list[Trade]) -> float:
    gross_win = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
    return gross_win / gross_loss if gross_loss > 0 else float("inf")


def sweep_parameters(
    df: pd.DataFrame,
    entry_key: str = "strict",
    atr_mults: list[float] | None = None,
    entry_tolerances: list[float] | None = None,
) -> pd.DataFrame:
    """Grid search over ATR stop multiplier and entry zone tolerance.

    entry_key: one of strict / relaxed / bb_only / kdj_only
    Returns a DataFrame of results sorted by profit_factor descending.
    """
    atr_mults = atr_mults or [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5]
    entry_tolerances = entry_tolerances or [0.0, 0.001, 0.002, 0.005]

    df = add_all(df.copy())

    entry_masks = {
        "strict":   (df["close"] <= df["bb_lower"]) & df["kdj_golden_cross"],
        "relaxed":  (df["close"] <= df["bb_lower"]) & (df["kdj_k"] > df["kdj_d"]),
        "bb_only":  df["close"] <= df["bb_lower"],
        "kdj_only": df["kdj_golden_cross"].astype(bool),
    }
    base_mask = entry_masks[entry_key]

    rows = []
    for atr_m in atr_mults:
        for tol in entry_tolerances:
            trades = _run_parametric(df.copy(), base_mask, atr_mult=atr_m, entry_tolerance=tol)
            if not trades:
                continue
            wins = [t for t in trades if t.pnl > 0]
            pnls = [t.pnl for t in trades]
            pf = _profit_factor(trades)
            rows.append({
                "entry": entry_key,
                "atr_mult": atr_m,
                "tol_pct": f"{tol*100:.1f}%",
                "trades": len(trades),
                "win_rate": round(len(wins) / len(trades) * 100, 1),
                "total_pnl": round(sum(pnls), 4),
                "avg_pnl": round(sum(pnls) / len(trades), 4),
                "profit_factor": round(pf, 3),
                "best": round(max(pnls), 4),
                "worst": round(min(pnls), 4),
            })

    result_df = pd.DataFrame(rows).sort_values("profit_factor", ascending=False)
    log.info("=== Parameter sweep: entry=%s ===", entry_key)
    log.info("%-8s  %-6s  %6s  %6s  %+9s  %+8s  %6s  %+7s  %+7s",
             "atr_mult", "tol", "trades", "win%", "total_pnl", "avg_pnl", "pf", "best", "worst")
    for _, r in result_df.iterrows():
        log.info("%-8s  %-6s  %6d  %6.1f  %+9.4f  %+8.4f  %6.3f  %+7.4f  %+7.4f",
                 r["atr_mult"], r["tol_pct"], r["trades"], r["win_rate"],
                 r["total_pnl"], r["avg_pnl"], r["profit_factor"], r["best"], r["worst"])
    return result_df


def analyze_stop_exits(df: pd.DataFrame, lookahead_bars: int = 48) -> None:
    """For each stop-loss exit in the current strategy, check if price recovered
    to the BB middle within the next `lookahead_bars` bars after the stop.

    Shows how many stopped trades were 'premature' vs genuinely saved by the stop.
    """
    from .strategy import run_signals, Signal

    df = df.copy()
    df["time_key"] = pd.to_datetime(df["time_key"])
    df = df.sort_values("time_key").reset_index(drop=True)

    annotated = run_signals(df)
    stop_rows = annotated[annotated["signal"] == Signal.EXIT_STOP_LOSS]

    if stop_rows.empty:
        log.info("No stop-loss exits found.")
        return

    recovered = 0
    total = len(stop_rows)
    log.info("=== Stop-loss exit analysis (lookahead=%d bars) ===", lookahead_bars)
    log.info("%-22s  %-8s  %-8s  %-8s  %-10s", "exit_time", "exit_px", "bb_mid", "gap", "recovered?")

    for idx, row in stop_rows.iterrows():
        future = annotated.iloc[idx + 1: idx + 1 + lookahead_bars]
        bb_mid = row["bb_middle"]
        exit_px = row["close"]
        gap = bb_mid - exit_px
        did_recover = (future["close"] >= bb_mid).any() if not future.empty else False
        if did_recover:
            recovered += 1
        log.info("%-22s  %-8.4f  %-8.4f  %-8.4f  %-10s",
                 str(row["time_key"]), exit_px, bb_mid, gap, "YES" if did_recover else "no")

    log.info("Recovered to BB middle within %d bars: %d / %d  (%.0f%%)",
             lookahead_bars, recovered, total, recovered / total * 100)


def sweep_walk_forward(
    df: pd.DataFrame,
    entry_key: str = "strict",
    atr_mults: list[float] | None = None,
    window_days: int = 90,
) -> pd.DataFrame:
    """Run walk-forward for each ATR multiplier and score by cross-window consistency.

    Returns a DataFrame of per-multiplier aggregate results over all windows.
    Positive-pnl window count is the key consistency metric.
    """
    atr_mults = atr_mults or [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

    df = add_all(df.copy())
    entry_masks = {
        "strict":   (df["close"] <= df["bb_lower"]) & df["kdj_golden_cross"],
        "relaxed":  (df["close"] <= df["bb_lower"]) & (df["kdj_k"] > df["kdj_d"]),
        "bb_only":  df["close"] <= df["bb_lower"],
        "kdj_only": df["kdj_golden_cross"].astype(bool),
    }
    base_mask = entry_masks[entry_key]

    start_ts = df["time_key"].iloc[0]
    end_ts = df["time_key"].iloc[-1]

    windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    ws = start_ts
    while ws < end_ts:
        we = ws + pd.Timedelta(days=window_days)
        windows.append((ws, min(we, end_ts)))
        ws = we

    rows = []
    for atr_m in atr_mults:
        win_windows = 0
        total_windows_with_trades = 0
        all_trades: list[Trade] = []

        for ws, we in windows:
            mask = (df["time_key"] >= ws) & (df["time_key"] < we)
            chunk = df[mask].reset_index(drop=True)
            if len(chunk) < 20:
                continue
            chunk_mask = base_mask[mask].reset_index(drop=True)
            trades = _run_parametric(chunk, chunk_mask, atr_mult=atr_m)
            all_trades.extend(trades)
            if trades:
                total_windows_with_trades += 1
                if sum(t.pnl for t in trades) > 0:
                    win_windows += 1

        if not all_trades:
            continue
        wins = [t for t in all_trades if t.pnl > 0]
        pf = _profit_factor(all_trades)
        consistency = win_windows / total_windows_with_trades * 100 if total_windows_with_trades else 0
        rows.append({
            "atr_mult": atr_m,
            "total_trades": len(all_trades),
            "win_rate": round(len(wins) / len(all_trades) * 100, 1),
            "total_pnl": round(sum(t.pnl for t in all_trades), 4),
            "avg_pnl": round(sum(t.pnl for t in all_trades) / len(all_trades), 4),
            "profit_factor": round(pf, 3),
            "pos_windows": win_windows,
            "total_windows": total_windows_with_trades,
            "consistency_pct": round(consistency, 1),
        })

    result_df = pd.DataFrame(rows).sort_values("consistency_pct", ascending=False)
    log.info("=== Walk-forward ATR sweep: entry=%s  window=%dd ===", entry_key, window_days)
    log.info("%-8s  %6s  %6s  %+9s  %+8s  %6s  %10s",
             "atr_mult", "trades", "win%", "total_pnl", "avg_pnl", "pf", "consistency")
    for _, r in result_df.iterrows():
        log.info("%-8s  %6d  %6.1f  %+9.4f  %+8.4f  %6.3f  %d/%d = %.1f%%",
                 r["atr_mult"], r["total_trades"], r["win_rate"], r["total_pnl"],
                 r["avg_pnl"], r["profit_factor"],
                 r["pos_windows"], r["total_windows"], r["consistency_pct"])
    return result_df


def sweep_signal_filter(
    df: pd.DataFrame,
    min_bonus_levels: list[int] | None = None,
) -> pd.DataFrame:
    """Compare alternative ranging/regime filters as the third bonus signal.

    Tests ADX ranging (current), BB width percentile variants, and no regime filter
    at multiple min_bonus thresholds. Core entry (BB touch + KDJ cross) always required.
    Bonus signals: rsi_oversold + <regime_filter> + volume_spike.

    Returns a DataFrame sorted by profit_factor descending.
    """
    from .indicators import BB_PERCENTILE_WINDOW
    from .signals import RSI_OVERSOLD, VOLUME_SPIKE_MULT, ADX_RANGING

    min_bonus_levels = min_bonus_levels or [0, 1, 2, 3]
    df = add_all(df.copy())

    core_gate = (df["close"] <= df["bb_lower"]) & df["kdj_golden_cross"].astype(bool)

    sig_rsi = df["rsi"] < RSI_OVERSOLD
    sig_vol = df["volume"] > VOLUME_SPIKE_MULT * df["volume_ma"]

    # Regime filter variants — what replaces the ranging signal
    regime_variants: dict[str, pd.Series] = {
        "adx_ranging":      df["adx"] < ADX_RANGING,
        "bb_contracted_30": df["bb_width_pct"] < 0.30,
        "bb_contracted_40": df["bb_width_pct"] < 0.40,
        "bb_contracted_50": df["bb_width_pct"] < 0.50,
        "bb_expanding_60":  df["bb_width_pct"] > 0.60,
        "bb_expanding_70":  df["bb_width_pct"] > 0.70,
        "no_regime":        pd.Series(True, index=df.index),
    }

    rows = []
    for regime_name, sig_regime in regime_variants.items():
        # Bonus score for this variant: rsi + regime + volume
        bonus = (
            sig_rsi.astype(int)
            + sig_regime.fillna(False).astype(int)
            + sig_vol.astype(int)
        )
        for min_b in min_bonus_levels:
            entry_mask = core_gate & (bonus >= min_b)
            entry_mask = entry_mask.fillna(False)
            if entry_mask.sum() == 0:
                continue
            trades = _run_parametric(df.copy(), entry_mask)
            if not trades:
                continue
            wins = [t for t in trades if t.pnl > 0]
            stops = [t for t in trades if t.exit_reason == "EXIT_STOP_LOSS"]
            targets = [t for t in trades if t.exit_reason == "EXIT_TARGET"]
            pf = _profit_factor(trades)
            rows.append({
                "regime_filter": regime_name,
                "min_bonus":     min_b,
                "trades":        len(trades),
                "win_pct":       round(len(wins) / len(trades) * 100, 1),
                "total_pnl":     round(sum(t.pnl for t in trades), 4),
                "avg_pnl":       round(sum(t.pnl for t in trades) / len(trades), 4),
                "profit_factor": round(pf, 3),
                "stops":         len(stops),
                "targets":       len(targets),
            })

    result_df = pd.DataFrame(rows).sort_values("profit_factor", ascending=False)
    log.info("=== Signal filter sweep (BB_PCT_WINDOW=%d) ===", BB_PERCENTILE_WINDOW)
    log.info("%-18s  %5s  %6s  %6s  %+9s  %+8s  %6s  %5s/%5s",
             "regime_filter", "bonus", "trades", "win%", "total_pnl", "avg_pnl", "pf",
             "stops", "tgts")
    for _, r in result_df.iterrows():
        log.info("%-18s  %5d  %6d  %6.1f  %+9.4f  %+8.4f  %6.3f  %5d/%5d",
                 r["regime_filter"], r["min_bonus"], r["trades"], r["win_pct"],
                 r["total_pnl"], r["avg_pnl"], r["profit_factor"], r["stops"], r["targets"])
    return result_df


def research_file(
    path: str | Path,
    walk_forward: bool = False,
    window_days: int = 30,
    exits: bool = False,
) -> None:
    df = pd.read_csv(path)
    df["time_key"] = pd.to_datetime(df["time_key"])
    df = df.sort_values("time_key").reset_index(drop=True)
    log.info("Loaded %d candles from %s", len(df), path)

    log.info("=== Entry variant comparison ===")
    compare_variants(df)

    if exits:
        compare_exit_variants(df)

    if walk_forward:
        log.info("=== Walk-forward entry variant comparison (%d-day windows) ===", window_days)
        compare_variants_walk_forward(df, window_days=window_days)

# Strategy Graveyard & On-Hold Features

A reference for everything tested, abandoned, or parked. Nothing here is lost — code exists, findings are documented. This file exists so the next session can pick up context without re-deriving.

---

## Dead Strategies (tested, no deployable edge)

### VWAP Crossover (momentum)
**What it was:** Enter long when price crosses above VWAP, exit when it crosses back below.
**Why it died:** Average hold time = 5 minutes (1 bar). PF 0.877–1.024 across all combos. At 5-min resolution, VWAP crossovers are pure noise — the signal fires constantly and has no predictive value.
**Code:** `mm/vwap_strategy.py`, `mm/vwap_signals.py` — kept for reference, not imported by paper runner.

### VWAP Mean-Reversion (price below VWAP = buy)
**What it was:** Enter long when price drops below VWAP by N × ATR, target return to VWAP.
**Why it died:** Price below VWAP on a 5-min bar is continuation, not reversion. 42% win rate, PF≈1.0 across 48 parameter combos (band mult × stop mult × RSI threshold). The signal fires but the edge isn't there.
**Note:** VWAP Pullback (flush-and-reclaim) is different and IS deployed — see below.

### EMA5/EMA20 Momentum Breakout
**What it was:** Two variants — (1) enter on EMA5 crosses above EMA20 with ADX>N, (2) enter on pullback to EMA5 while EMA5>EMA20.
**Why it died:**
- Cross entry: uniformly negative across all 36 combos × 3 symbols (PF 0.3–0.93). Trend-following at 5-min doesn't work.
- Pullback entry: stop_mult parameter completely inert — EMA20 break always triggers before ATR stop, making risk management broken. ADX=25 anomaly (worse than both ADX=20 and ADX=30 simultaneously) suggests sample artifact.
- ADX=20 shows weak positive PF (1.06–1.20) but with a broken stop — not deployable.
**Code:** `mm/ema_momentum.py`, `scripts/backtest_ema_momentum.py` — kept for reference.
**If revisiting:** Fix stop to be ATR-only (remove min(ema20, atr)). Investigate ADX=25 anomaly on a larger dataset before drawing conclusions.

---

## On Hold (researched but not implemented)

### Session Filter (BLOCKED_HOURS) for BB+KDJ
**What it is:** Suppress BB+KDJ entries during specified ET hours. Exits always fire.
**Research result (1,108 trading days, combined CSVs):**
- Block 10-11: +$3.83 IWM, +$5.31 QQQ, −$0.80 SPY — only universally non-negative filter
- Block 14: +$7.26 SPY, +$1.97 IWM, −$2.08 QQQ — symbol-specific
- Block 15-16: −$21.92 IWM, −$21.75 QQQ, −$33.61 SPY — NEVER do this, close hours are critical
- Block 9 (open): −$14.57 IWM, −$11.00 SPY — open entries are productive
**Why it's on hold:** BB+KDJ already has aggressive multi-condition filtering. Adding a time blackout further suppresses a ~300 trade/4yr strategy. Small sample makes per-hour delta unreliable.
**Code ready:** `strategy.py` has `blocked_hours: set[int] | None = None` param in `run_signals()`. `scripts/sweep_session_filter.py` for analysis. Wire `BLOCKED_HOURS=10,11` in config to activate.

### VIX Daily Regime Filter
**What it is:** Block BB+KDJ entries on high-volatility days (VIX > threshold).
**Backtested (2026-06-04):** `scripts/backtest_vix_filter.py --all` on SPY+QQQ+IWM combined CSVs.
**Result — do not deploy:**
- Combined OOS (2024+): Baseline PF=1.224. All filtered variants worse (best: Block>=20 = 1.208).
- IWM destroyed by any VIX block: Baseline OOS=1.033 → Block>=20 OOS=0.800. High-VIX days are IWM's best mean-reversion entries.
- QQQ OOS baseline (1.260) beats every filtered variant.
- SPY Block>=20 OOS (1.443) looks good in isolation but doesn't hold when combined.
- "Relax>30" (drop min_bonus to 1 on crisis days): Combined OOS=1.193 — also worse than baseline.
**Code:** `scripts/backtest_vix_filter.py` kept for reference. yfinance added to requirements.

### ORB Short Entries
**What it is:** ORB currently long-only in the live runner. Short = enter when price breaks below OR low.
**Why it's on hold:** Margin handling not yet wired up in paper runner. Short requires borrowing logic that adds complexity.
**Backtest note:** Long/short roughly 50/50 split in historical data, so long-only cuts frequency ~in half.
**Code:** `orb_strategy.py` handles both directions in backtest. Paper runner (`paper.py`) only executes longs.

### IWM-Weighted Position Sizing
**What it is:** `SYMBOL_SIZE_OVERRIDES=US.IWM:300,US.SPY:600,US.QQQ:500` to allocate more capital to IWM given its superior edge (61.9% win rate, 38% stop rate vs 50-58% for SPY/QQQ).
**Why it's on hold:** Waiting for first live trades to validate signal engines agree before tuning sizing.

### Web Dashboard Market Conditions Card
**What it is:** Add a live card to `scripts/web_dashboard.py` showing ATR percentile, session return, ADX value, and "why no entry" explanation when the strategy is quiet.
**Why it's on hold:** Low priority vs strategy research. The JSONL `bar_eval` events already have everything needed to build this.

### Multi-Model AI Research Workflow
**What it is:** Use Gemini Flash / GPT-4o for data analysis and hypothesis generation (paste backtest tables, ask for parameter sweep design, flag statistical issues) — preserve Claude Code context for implementation.
**Why it's interesting:** Research tasks (reading CSVs, proposing parameters, checking significance) don't need codebase context and burn it fast. Splitting the work saves tokens and is faster.
**Status:** Discussed, not set up. No tooling needed — just a workflow habit.

---

## Features That Worked (deployed reference)

| Strategy | PF (OOS) | Symbols | Notes |
|----------|----------|---------|-------|
| BB+KDJ mean reversion | 1.843 in-sample, walk-forward validated | IWM, SPY, QQQ | KDJ_WINDOW_BARS=3, MIN_SIGNAL_SCORE=2 |
| ORB (long-only) | 1.215 | IWM, SPY, QQQ | 30-min OR for IWM, 15-min for SPY/QQQ |
| VWAP Pullback | 1.655 SPY, 1.072 QQQ | SPY, QQQ only | IWM excluded (negative OOS) |

---

## Config Knobs That Were Researched and Settled

| Knob | Optimal | Tested Range | Why |
|------|---------|-------------|-----|
| ATR_STOP_MULT | 1.0 | 0.5–2.0 | Best PF + 56% walk-forward consistency |
| MIN_SIGNAL_SCORE | 2 | 0–3 | Flips exit split to target-dominant |
| KDJ_WINDOW_BARS | 3 | 0–5 | 10× signals on IWM/QQQ, SPY stays at 0 |
| EXIT_ON_KDJ_DEATH | false | — | Re-enabling flips SPY PnL from +$2.34 → −$0.83 |
| ORB_TARGET_MULT | 1.5 | 1.0–2.0 | Best combined PF |
| VWAP_PB_MAX_CROSSES | 1 | 0–3 | No-chop filter — critical for VWAP PB edge |
| Timeframe | K_5M | 5M/15M/60M | K_15M produces MORE stops, not fewer |
| Regime filter | ADX < 25 | 7 alternatives | Confirmed best across BB width, volume variants |

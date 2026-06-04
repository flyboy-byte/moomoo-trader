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
**Status: DEPLOYED (2026-06-04).** `ORB_SHORTS_ENABLED=true` default. Kill switch: `STOP_SHORTS.txt` in project root.
**What was built:** `_place_short()` (SELL_SHORT), `_place_cover()` (BUY_BACK), `direction` field on `PaperPosition`, direction-aware stop/target/pnl logic, restart recovery fix. 16 tests in `tests/test_orb_shorts.py`.
**Outstanding:** Live verification that Moomoo paper account accepts `TrdSide.SELL_SHORT` — watch first short signal's `order_result` event in JSONL.

### IWM-Weighted Position Sizing
**What it is:** `SYMBOL_SIZE_OVERRIDES=US.IWM:300,US.SPY:600,US.QQQ:500` to allocate more capital to IWM given its superior edge (61.9% win rate, 38% stop rate vs 50-58% for SPY/QQQ).
**Why it's on hold:** Waiting for first live trades to validate signal engines agree before tuning sizing.

### Web Dashboard Market Conditions Card
**Status: DEPLOYED (2026-06-04).** `scripts/web_dashboard.py` updated.
**What was built:** A `MARKET CONDITIONS` card injected between TRADES and SIGNAL FEED. Three sub-sections — BB+KDJ, ORB, VWAP PB — show the latest eval per symbol per strategy with entry-readiness status. A RECENT SKIPS section shows the last 12 `signal_skip` events with reason and score. `_render_market_conditions()` reads via two new loaders: `_load_latest_evals_by_symbol()` and `_load_recent_skips()`.
**Status labels:** BB+KDJ shows "BB X% away" / "need KDJ" / "READY ▲". ORB shows "LONG READY ▲" / "SHORT READY ▼" / distance to breakout. VWAP PB shows "choppy (N crosses > max)" or "READY ▲".

### Multi-Model AI Research Workflow
**What it is:** Use Gemini Flash / GPT-4o for data analysis and hypothesis generation — preserve Claude Code context for implementation.
**Status:** Active workflow habit. No tooling needed — paste backtest tables to Gemini/GPT, bring findings back here for implementation.

---

## Decided Against (from Gemini expansion plan, June 2026)

### VIX 3-Tier Strategy Switching
**What it was:** Use VIX as a master regime switch — ORB when VIX<15, VWAP PB when VIX 15-28, BB+KDJ when VIX>30.
**Why skipped:** Unvalidated assumption that strategy fit changes by regime. VIX daily filter backtest showed VIX is not predictive for BB+KDJ entries. Regime-strategy mapping needs independent backtesting per cell before trusting.

### Symbol Scaling (DIA / TLT / XLK / XLF)
**What it was:** Add sector ETFs and inverse-correlated assets (TLT) to diversify the symbol universe.
**Why skipped:** Every new symbol needs a full backtest + OOS validation cycle. No bandwidth. The three current symbols (SPY/QQQ/IWM) already cover the liquid ETF space. Add when there's a specific edge hypothesis, not just "more symbols."

### Dynamic ATR Trailing Stops
**What it was:** Replace fixed BB-middle target with a 1.5× ATR trailing stop to capture "pierce" moves.
**Why skipped:** Unvalidated. BB-middle is a clean, interpretable target with a proven OOS edge. Adding a trailing stop introduces a new parameter and potential for premature exit on reversion trades. Needs isolated backtest before considering.

### Economic Event Gating (STOP_FOR_NEWS.txt / vol spike filter)
**What it was:** Pause entries 30 min around CPI/FOMC. Auto-detect via 1-min ATR spike (>3× 60-min avg).
**Why skipped:** Over-engineering for paper trading. STOP_TRADING.txt already handles manual pauses. 1-min ATR requires a separate data feed. Cost > benefit at this stage.

### Push Architecture (intra-bar exits)
**What it was:** Replace 60s polling with `StockQuoteHandlerBase` WebSocket push. Use push data for exits, closed bars for entries only.
**Why deferred:** No evidence slippage is a real problem yet — need live trade data first. WebSocket stability on the VPS is unknown. Build `scripts/live_price_monitor.py` pilot first if this becomes a priority.
**Revisit when:** Live trades show consistent exit slippage > 0.1% per trade.

---

## Features That Worked (deployed reference)

| Strategy | PF (OOS) | Symbols | Notes |
|----------|----------|---------|-------|
| BB+KDJ mean reversion | 1.843 in-sample, walk-forward validated | IWM, SPY, QQQ | KDJ_WINDOW_BARS=3, MIN_SIGNAL_SCORE=2 |
| ORB (long + short) | 1.215 | IWM, SPY, QQQ | 30-min OR for IWM, 15-min for SPY/QQQ. Shorts added 2026-06-04. |
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

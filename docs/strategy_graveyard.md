# Strategy Graveyard & Feature Log

Everything tested, built, abandoned, or parked. Nothing is lost — code exists, findings are
documented. This file keeps sessions context-efficient by recording the "why" behind every decision.

---

## Dead Strategies (tested, no deployable edge)

### VWAP Crossover (momentum)
**Entry:** Price crosses above VWAP, exit when it crosses back below.
**Why dead:** Avg hold = 5 bars. PF 0.877–1.024 across all combos. VWAP crossovers at 5-min are pure noise.
**Code:** `mm/vwap_strategy.py`, `mm/vwap_signals.py` — kept for reference, not imported by paper runner.

### VWAP Mean-Reversion (price below VWAP = buy)
**Entry:** Price drops below VWAP by N × ATR, target return to VWAP.
**Why dead:** 42% win rate, PF≈1.0 across 48 combos. Price below VWAP on 5-min is continuation, not reversion.
**Note:** VWAP Pullback (flush-and-reclaim) is different and IS deployed.

### EMA5/EMA20 Momentum Breakout
**Variants:** (1) EMA5 crosses EMA20 with ADX>N, (2) pullback to EMA5 while EMA5>EMA20.
**Why dead:**
- Cross entry: uniformly negative (PF 0.3–0.93 across 36 combos × 3 symbols). Trend-following at 5-min doesn't work.
- Pullback entry: stop_mult parameter completely inert — EMA20 break always triggers before ATR stop. Risk management broken.
- ADX=25 anomaly (worse than ADX=20 and ADX=30 simultaneously) — sample artifact.
**Code:** `mm/ema_momentum.py`, `scripts/backtest_ema_momentum.py`
**If revisiting:** Fix stop to ATR-only. Investigate ADX=25 anomaly on larger dataset.

### VIX Daily Regime Filter
**What it was:** Block BB+KDJ on high-volatility days (VIX > threshold).
**Backtested (2026-06-04):** `scripts/backtest_vix_filter.py --all` on SPY+QQQ+IWM combined CSVs.
**Why dead:**
- Combined OOS (2024+): Baseline PF=1.224. ALL filtered variants worse. Best: Block>=20 = 1.208.
- IWM destroyed: Baseline OOS=1.033 → Block>=20 OOS=0.800. High-VIX days are IWM's best entries.
- "Relax>30" mode: Combined OOS=1.193 — also worse than baseline.
**Code:** `scripts/backtest_vix_filter.py` kept for reference.

---

## Built & Deployed (live on VPS as of 2026-06-04)

| Feature | Code | Notes |
|---------|------|-------|
| BB+KDJ mean reversion | `mm/strategy.py`, `mm/paper.py` | MIN_SCORE=2, KDJ_WINDOW=3, PF=1.843 |
| ORB long + short | `mm/orb_strategy.py`, `mm/paper.py` | 30-min IWM, 15-min SPY/QQQ. Shorts 2026-06-04. |
| VWAP Pullback | `mm/vwap_pullback.py`, `mm/paper.py` | SPY/QQQ only. PF=1.655 SPY, 1.072 QQQ OOS. |
| Fractional sizing | `mm/risk.py`, `mm/paper.py` | TOTAL_CAPITAL / (symbols × strategies) per slot |
| JSONL event logging | `mm/paper.py` (PaperEventLog) | bar_eval, signal_skip, position_open/close, slippage_bps |
| Web dashboard | `scripts/web_dashboard.py` | Flask :8080 — Market Conditions card, slippage column |
| TUI dashboard | `scripts/dashboard.py` | Textual, past session replay |
| diagnose_logs.py | `scripts/diagnose_logs.py` | 5-section session health report |
| verify.sh | `scripts/verify.sh` | pytest + sync + diagnose + compare in one command |
| compare_paper_vs_backtest | `scripts/compare_paper_vs_backtest.py` | BB+KDJ signal engine agreement check |
| Startup config validation | `mm/config.py` (validate_config) | Fails fast on bad .env before touching broker |
| Broker position reconciliation | `mm/paper.py` (_reconcile_positions) | On restart, clears stale local state if broker disagrees |
| Per-strategy trade limits | `mm/risk.py` (DailyTracker) | MAX_TRADES_PER_STRATEGY config, prevents ORB starving BB+KDJ |

---

## On Hold (parked with a gate condition)

### ATR-Normalized Position Sizing
**What it is:** `share_qty = risk_dollars / (atr × atr_mult)`. Every trade risks the same dollar amount regardless of volatility. Replaces fixed dollar cap.
**Why parked:** Current fractional approach controls dollar exposure per slot but ignores volatility. A $11 position on a 1% vol day vs 4% vol day risks 4× differently. ATR sizing fixes this.
**Gate:** After 2+ weeks of live slippage data — need real fill prices before adding sizing complexity.
**Files to touch:** `mm/config.py` (RISK_DOLLARS_PER_TRADE), `mm/risk.py` (calc_qty_atr), `mm/paper.py` (branch in each _eval_* entry block).

### IWM-Weighted Position Sizing
**What it is:** `SYMBOL_SIZE_OVERRIDES=US.IWM:300,US.SPY:600,US.QQQ:500` — more capital to IWM given superior edge (61.9% win, 38% stop vs 50–58% for SPY/QQQ).
**Why parked:** Superseded by ATR sizing. If done right, ATR sizing naturally gives IWM larger positions when stops are tight. Do ATR sizing first.

### Session Filter (BLOCKED_HOURS) for BB+KDJ
**What it is:** Suppress BB+KDJ entries during specified ET hours. Exits always fire.
**Research (1,108 trading days):**
- Block 10-11: +$3.83 IWM, +$5.31 QQQ, −$0.80 SPY — no universal improvement
- Block 15-16: −$21.92 IWM, −$21.75 QQQ, −$33.61 SPY — catastrophic
- Block 9 (open): −$14.57 IWM, −$11.00 SPY — open entries are productive
**Why parked:** No hour is universally safe to block. Small sample makes per-hour deltas unreliable.
**Code ready:** `strategy.py` has `blocked_hours` param. Wire `BLOCKED_HOURS=10,11` in config to activate.

### ORB Short Live Verification
**Status:** Code deployed, first live short hasn't fired yet.
**What's needed:** Market must break below OR low with volume. Watch `order_result` event in JSONL for `SELL_SHORT`. Until then, the Moomoo paper API path for shorts is unverified.

### Push Architecture (WebSocket exits)
**What it is:** Replace 60s polling with `StockQuoteHandlerBase` WebSocket. Intra-bar exits instead of end-of-bar.
**Gate:** Live trades show consistent exit slippage > 0.1% per trade. Current `slippage_bps` field is 0.0 in SIMULATE — need real fill data before this is justified.
**Revisit when:** slippage_bps readings from live fills show the 60s poll costs real edge.

### paper.py Refactor (Split into Smaller Modules)
**What it is:** `mm/paper.py` is 1,100+ lines. The strategy evaluation, position state, risk gating, event logging, and main loop are all in one file. Split into:
- `mm/execution.py` — _place_buy/_sell/_short/_cover, _reconcile_positions
- `mm/position.py` — PaperPosition, _save/load/clear_position, PaperEventLog
- `mm/loop.py` — run_multi(), _eval_symbol_all_strategies(), main loop
- Strategy evals stay in their own files (or mm/eval_bb_kdj.py etc.)
**Why parked:** Large refactor with no functional benefit right now. Risk of introducing bugs.
**When:** Before adding a 4th strategy or when paper.py hits a natural split point during feature work.

### Qty Floor / Auto-Fallback in `_qty()`
**What it is:** A guard in `_qty()` that detects when fractional-mode produces a quantity
below Moomoo's minimum order size and automatically falls back to whole-share `calc_qty()`.
**Why parked:** Found 2026-06-08 — `TOTAL_CAPITAL=100` + `FRACTIONAL_SHARES=true` split
$100 across ~8 (symbol×strategy) slots → ~$12.50/slot → qty≈0.015 shares. Moomoo's paper
API silently rejected every BUY and SELL_SHORT all of Friday 2026-06-05 with
"Invalid quantity" — zero trades fired, zero P&L, no crash. Reverted VPS `.env` to
`TOTAL_CAPITAL=0` / `FRACTIONAL_SHARES=false` (the proven June 4 whole-share path:
`MAX_POSITION_DOLLARS=900` → qty=1 SPY/QQQ, ~3 IWM — both June 4 entries filled clean).
**Caught by:** structured JSONL `order_attempt`/`order_result` events (success=false) +
`paper.log` ERROR lines. Traced root cause to the `.env` config in minutes — logging worked.
**Gate:** Before re-enabling fractional sizing, determine Moomoo's actual minimum order
quantity/value (test in isolation), then add the floor check so a bad config degrades
gracefully instead of silently killing every order for a session.
**Files to touch:** `mm/paper.py` (`_qty()`), maybe `mm/risk.py` (`calc_qty_fractional`).

---

## Decided Against (with data/reasoning)

### VIX 3-Tier Strategy Switching
**What it was:** ORB when VIX<15, VWAP PB when VIX 15-28, BB+KDJ when VIX>30.
**Why no:** Unvalidated assumption. VIX filter backtest showed VIX is not predictive. Regime-strategy mapping needs per-cell backtesting before trusting.

### Symbol Scaling (DIA / TLT / XLK / XLF)
**Why no:** Every new symbol needs full backtest + OOS cycle. SPY/QQQ/IWM already cover the liquid ETF space. Add only with a specific edge hypothesis.

### Dynamic ATR Trailing Stops
**Why no:** BB-middle is a clean, interpretable target with proven OOS edge. Trailing stop adds a parameter and potential for premature exit. Needs isolated backtest first.

### Economic Event Gating (STOP_FOR_NEWS.txt)
**Why no:** Over-engineering. STOP_TRADING.txt handles manual pauses. 1-min ATR spike filter requires a separate data feed. Cost > benefit at this stage.

---

## Config Knobs Researched and Settled

| Knob | Optimal | Tested Range | Why |
|------|---------|-------------|-----|
| ATR_STOP_MULT | 1.0 | 0.5–2.0 | Best PF + 56% walk-forward consistency |
| MIN_SIGNAL_SCORE | 2 | 0–3 | Flips exit split to target-dominant |
| KDJ_WINDOW_BARS | 3 | 0–5 | 10× signals on IWM/QQQ; SPY excluded or kept at 0 |
| EXIT_ON_KDJ_DEATH | false | — | Re-enabling flips SPY PnL from +$2.34 → −$0.83 |
| ORB_TARGET_MULT | 1.5 | 1.0–2.0 | Best combined PF |
| VWAP_PB_MAX_CROSSES | 1 | 0–3 | Critical no-chop filter for VWAP PB edge |
| Timeframe | K_5M | 5M/15M/60M | K_15M produces MORE stops, not fewer |
| Regime filter | ADX < 25 | 7 alternatives | Confirmed best vs BB width, volume variants |
| ORB window IWM | 30-min | 15/30-min | 15-min PF=1.017 → 30-min PF=1.217 |

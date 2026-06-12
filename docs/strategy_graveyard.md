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
| Order price rounding | `mm/paper.py` (_place_buy/sell/short/cover) | round(price, 2) — Moomoo rejects >2 dp (caught June 4, 8) |
| Entry retry dedup | `mm/paper.py` (_entry_attempted dict) | One attempt per candle per (symbol, strategy) — prevents storm |
| Fractional qty fallback | `mm/paper.py` (_qty()) | qty < 1 → whole-share fallback instead of silently rejecting |
| Daily loss limit | `mm/config.py`, `mm/risk.py` | MAX_DAILY_LOSS raised to $20 — $5 killed full day after 1 VWAP PB loss |

---

## On Hold (parked with a gate condition)

### Risk-Normalized Position Sizing — BUILT DARK 2026-06-12
**What it is:** `share_qty = RISK_DOLLARS_PER_TRADE / (entry − stop)`, capped by the dollar cap.
Every trade risks the same dollars regardless of volatility. Generalizes the original ATR-sizing
design to actual stop distance (covers ORB's range-based stops too).
**Status:** Implemented (`mm/risk.py` calc_qty_risk, all 5 entry blocks in `mm/paper.py`),
7 tests, validated end-to-end via the replay harness. DISABLED by default
(RISK_DOLLARS_PER_TRADE=0 → byte-identical legacy behavior).
**Enablement gate (unchanged):** 2+ weeks of live fill data, then set RISK_DOLLARS_PER_TRADE
in .env.
**Replay A/B (2026 YTD, touch fills, RISK_DOLLARS_PER_TRADE=5 vs dollar-cap baseline):**
total +$65.97 vs +$30.34. ORB PF 1.04→1.16 (+$14→+$45): tight-range days get more shares,
and trades whose stop distance exceeds the $5 risk budget at 1 share are refused outright
(13 fewer ORB trades — the widest/choppiest setups). bb_kdj loss halved; vwap_pb unchanged
(already 1-share). Mechanism is risk discipline, not signal change. Caveats: one 5.5-month
window; SIMULATE fills are optimistic and slippage scales with qty.

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

### paper.py Refactor (Split into Smaller Modules) — ANALYZED 2026-06-12, READY TO EXECUTE
**What:** mm/paper.py is 1,414 lines / 45 defs. Split it along its existing comment-divider
sections. Full recon done; this entry is the execution plan — pull it out and follow it.

**Target layout (with exact current line ranges):**
| New module | Moves from paper.py | ~Lines |
|---|---|---|
| `mm/clock.py` (NEW seam) | nothing moves — new ~40-line module: `now()`, `now_et()`, `today()`, `monotonic()`, `sleep()`, `is_market_open()` | 40 |
| `mm/events.py` | PaperEventLog (64–141), PaperPosition (148–158), _position_file/_save/_load/_clear_position (164–208), _orb_traded_file/_load/_save_orb_traded (327–351) | 250 |
| `mm/execution.py` | reconcile block: constants + _orphan_warned + _order_status + _reconcile_positions (210–325); trade_context/_get_simulate_acc_id (354–376); _place_buy/sell/short/cover (378–448); fill-confirm block: constants + _exit_unfilled_notified + _confirm_fill/_cancel_order/_execute_entry/_execute_exit (459–590) | 420 |
| `mm/evals.py` | _kdj_cross_age (680–694), _eval_bb_kdj (696), _eval_vwap (800), _eval_vwap_pb (888), _eval_orb (998–1179), _entry_attempted dict (600) | 540 |
| `mm/risk.py` (gains) | _qty (603–625), _position_cap (627–635), _slot_dollars (596) + a `set_slot_dollars()` setter — calc_qty* already lives here, avoids an evals→paper import cycle | 45 |
| `mm/paper.py` (keeps) | _latest_closed_candles (638–677), _trigger_eod_summary (1181), run_multi (1205), _eval_symbol_all_strategies (1346), run (1411) + **back-compat re-exports** | 230 |

**Why mm/clock.py first (the real risk in this refactor):** tests and mm/replay.py work by
patching names in mm.paper's namespace (replay patches 9: market_open, datetime, date, time,
notify×3, _latest_closed_candles; plus mm.risk.date and cfg.logs_dir). After the split,
datetime.now is called from events.py AND execution.py AND evals.py AND paper.py — patching
one module no longer covers the others. Route ALL time/market-state access through mm/clock.py
and the patch surface collapses to one module permanently. (mm.risk.DailyTracker's
date.today and market_open also route through clock.)

**Shared mutable state homes (verified by grep):**
- `_entry_attempted` — written by all 5 entry blocks, cleared by run_multi (lines ~1228–1235)
  → lives in evals.py, run_multi calls `evals.reset_session_state()`.
- `_orphan_warned` (reconcile only) and `_exit_unfilled_notified` (execute_exit only)
  → execution.py, private.
- `_slot_dollars` — set by run_multi at startup, read by _qty/_position_cap
  → risk.py with set_slot_dollars(); kills the would-be evals→paper cycle.

**Back-compat re-exports in paper.py (verified importers):**
- scripts/run_paper.py: `from mm.paper import run, run_multi` (stays native)
- scripts/simulate_paper.py: `from mm.paper import PaperEventLog, PaperPosition` (re-export)
- tests/test_paper.py + test_orb_shorts.py: call most functions directly — update their
  imports to the new modules (mechanical); only 1 namespace patch (market_open → clock)
  and 3 timing-constant monkeypatches (_FILL_TIMEOUT_S/_FILL_POLL_S/_CANCEL_RECHECK_S →
  execution) need re-targeting.
- mm/replay.py: rewrite its patch block to target mm.clock (one module) + cfg.logs_dir
  + paper._latest_closed_candles.

**Import graph (acyclic by construction):**
clock ← events ← execution ← evals ← paper(loop); risk imports clock only; nothing imports paper.

**Execution order (half-day session, ~3–4h active):**
1. BEFORE TOUCHING ANYTHING: `python scripts/replay_paper.py --latest --start 2026-01-01
   --end 2026-06-09 --out replay_cert_before` (~40 min, run in background while step 2–3 happen
   on a branch). The sim clock makes event streams fully deterministic.
2. Create mm/clock.py; mechanically reroute datetime/time/market_open/date.today calls in
   paper.py and risk.py through it; run tests + replay diff — MUST be identical before any
   code moves. Commit.
3. Move events.py → execution.py → evals.py → trim paper.py, committing per module,
   tests green at each step.
4. Re-target mm/replay.py and test patch points (small: see above). Full suite green.
5. CERTIFY: same replay → replay_cert_after; `diff -r replay_cert_before replay_cert_after`
   must be EMPTY (timestamps are sim-clock-derived, so byte-identical is the bar).
   Also run scripts/replay_vs_live.py for the latest session.
6. ./deploy.sh AFTER market close only. verify.sh next session.

**Abort criterion:** any non-empty cert diff that isn't explained in one minute of looking
→ `git reset --hard` to the last green commit. The whole point is zero behavior change.

**When:** Evening session, market closed (deploys restart the runner). Knob freeze makes
this the ideal window — no parallel strategy changes to collide with.

---

## Decided Against (with data/reasoning)

### ORB Afternoon Entry Cutoff (ORB_CUTOFF_HOUR)
**What it was:** Block ORB entries after 12:00 ET. Motivated by 2026 YTD replay through the
real runner: hours 12+ = 75 trades, −$93, PF 0.23–0.71, 76% TIME_STOP deaths, while hours
9–11 = 191 trades, +$107. A noon cutoff would have flipped YTD ORB from +$14 to +$107.
**Why no (2026-06-12):** Fails OOS cross-validation. 2022–2025 (backtest engine, same
symbols/windows): hours 12+ = 698 trades, +$64.68, PF 1.16 — profitable, barely below
mornings (PF 1.22). Hours 13–14 actually outperform (PF 1.32/1.46). The 2026 afternoon
bleed is this year's regime or 75-trade variance, not structure.
**If the live ORB gate trips:** slice live trades by entry hour first (scripts/
analyze_orb_hours.py logs/) — if live matches the 2026 replay pattern rather than the
2022–2025 pattern, the cutoff becomes a legitimate pre-registered amendment candidate.

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

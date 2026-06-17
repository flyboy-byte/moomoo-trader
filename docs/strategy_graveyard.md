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
| BB+KDJ mean reversion | `mm/strategy.py`, `mm/evals.py` | MIN_SCORE=2, KDJ_WINDOW=3, PF=1.843 |
| ORB long + short | `mm/orb_strategy.py`, `mm/evals.py` | 30-min IWM, 15-min SPY/QQQ. Shorts 2026-06-04. |
| VWAP Pullback | `mm/vwap_pullback.py`, `mm/evals.py` | SPY/QQQ only. PF=1.655 SPY, 1.072 QQQ OOS. |
| Fractional sizing | `mm/risk.py` (_qty, _slot_dollars) | TOTAL_CAPITAL / (symbols × strategies) per slot |
| JSONL event logging | `mm/events.py` (PaperEventLog) | bar_eval, signal_skip, position_open/close, slippage_bps |
| Web dashboard | `scripts/web_dashboard.py` | Flask :8080 — Market Conditions card, slippage column |
| TUI dashboard | `scripts/dashboard.py` | Textual, past session replay |
| diagnose_logs.py | `scripts/diagnose_logs.py` | 5-section session health report |
| verify.sh | `scripts/verify.sh` | pytest + sync + diagnose + compare in one command |
| compare_paper_vs_backtest | `scripts/compare_paper_vs_backtest.py` | BB+KDJ signal engine agreement check |
| Startup config validation | `mm/config.py` (validate_config) | Fails fast on bad .env before touching broker |
| Broker position reconciliation | `mm/execution.py` (_reconcile_positions) | On restart, clears stale local state if broker disagrees |
| Per-strategy trade limits | `mm/risk.py` (DailyTracker) | MAX_TRADES_PER_STRATEGY config, prevents ORB starving BB+KDJ |
| Order price rounding | `mm/execution.py` (_place_buy/sell/short/cover) | round(price, 2) — Moomoo rejects >2 dp (caught June 4, 8) |
| Entry retry dedup | `mm/evals.py` (_entry_attempted dict) | One attempt per candle per (symbol, strategy) — prevents storm |
| Fractional qty fallback | `mm/risk.py` (_qty()) | qty < 1 → whole-share fallback instead of silently rejecting |
| Daily loss limit | `mm/config.py`, `mm/risk.py` | MAX_DAILY_LOSS raised to $20 — $5 killed full day after 1 VWAP PB loss |

---

## On Hold (parked with a gate condition)

### Gap Fade — BUILT 2026-06-16, pending live verification
**What it is:** Fade the overnight gap when the first 5-min bar (9:35 close) closes against
the gap direction. Gap up + red first bar → short; gap down + green first bar → long.
Target: 50% gap fill. Stop: first bar extreme + 0.1%. Time stop: 11:00 ET.
**Code:** `mm/gap_fade.py`, `scripts/backtest_gap_fade.py`
**Walk-forward (0.3% min gap, 50% fill target):**
| Symbol | Train 2022-23 | OOS 2024-25 | 2026 YTD |
|--------|---------|---------|---------|
| IWM | PF=1.031, 136 tr | PF=**1.938**, 164 tr, 72%WR | PF=2.163, 33 tr |
| SPY | PF=1.022, 147 tr | PF=1.326, 108 tr, 60%WR | — |
| QQQ | PF=1.029, 156 tr | PF=1.022, 143 tr (flat) | excluded |
**Why training is weak (PF≈1.02):** 2022-2023 was a bear market with large, meaningful overnight
gaps that don't fade. The OOS improvement is structural (low-volatility 2024-2025 = more
noise gaps). Regime risk if volatility returns to 2022 levels.
**Enablement gates:**
- ORB short must fire live at least once (same SELL_SHORT code path, currently unverified).
- 15 live paper trades before drawing conclusions.
- QQQ excluded (flat OOS). SPY optional (PF=1.326 OOS is marginal).
- Deploy IWM first (strongest and most consistent across parameter sweep).

### Risk-Normalized Position Sizing — BUILT DARK 2026-06-12
**What it is:** `share_qty = RISK_DOLLARS_PER_TRADE / (entry − stop)`, capped by the dollar cap.
Every trade risks the same dollars regardless of volatility. Generalizes the original ATR-sizing
design to actual stop distance (covers ORB's range-based stops too).
**Status:** Implemented (`mm/risk.py` calc_qty_risk, all 5 entry blocks in `mm/evals.py`),
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

### Gap Fade Pre-Market Features — BUILT 2026-06-16, unvalidated
**What it is:** `mm/premarket.py` + `scripts/research_premarket_gap.py` derive pre-market
fill % (how much of the overnight gap was already retraced by ~9:25 ET) and pre-market
volume ratio (today's premarket volume vs trailing 20-day avg) from Moomoo's
`extended_time=True` candle fetch (`mm/data.py::fetch_candles`), joined onto existing Gap
Fade trades. Three independent deep-research passes (Codex/ChatGPT ×2, Claude online — see
docs/deep/) converged on this as the highest-ROI next step: current `gap_pct` in
`mm/gap_fade.py` is computed purely from RTH candles, blind to 4:00-9:30am activity, and
pre-market volume/fill state is the best informational-vs-noise gap discriminator per the
research, ahead of gap size alone.
**Status:** Code built, NOT validated — could not test against live OpenD in the building
session (`moomoo_OpenD.service` was not running). `GAP_PREMARKET_FILTER_ENABLED` config knob
ships dark (false) in `mm/config.py`; not read anywhere yet — pure scaffolding.
**Enablement gate:** Run `scripts/research_premarket_gap.py` once OpenD is up, confirm
extended-hours bars actually return for the 4:00-9:30 window (Moomoo's docs say extended-hours
history "may be less than 2 years" and don't publish exact session boundaries — unverified).
If the win-rate/PF breakdown by volume-ratio and fill-% tier shows a clean split on ≥30
trades, wire the filter into `mm/gap_fade.py::run_gap_fade()` as a new pre-registered rule.

### Inferred Features — NOT BUILT, parked (2026-06-16 deep research pass)
Five ideas surfaced by the same three research reports that are plausible but premature,
speculative, or high-effort relative to current trade volume. Logged so future sessions don't
re-litigate from scratch:

| Idea | Why parked |
|---|---|
| Self-computed GEX/regime tag from Moomoo's free option-chain greeks (Σgamma×OI per strike) | Real and free, but only useful after ~100+ live trades across strategies to test whether mean-reversion outperforms in positive-GEX regimes. Premature at current trade count. |
| Futures pre-open premium (ES/NQ) as gap-fade confirmation | Research itself flags this as small-sample practitioner-only evidence (~30 cases), not peer-reviewed. Moomoo US accounts are quote-only on futures (no trading); exact ES/NQ/RTY quote-symbol strings were never verified by any of the 3 reports. |
| Order book / tick-data aggressor-side pressure during pre-market | `get_rt_ticker` exposes trade direction but is real-time-only — no historical tick endpoint exists per research. Would need weeks of live data collection before any backtest is possible. |
| OpEx calendar regime tag (vol-compressed mornings, "gamma cliff" the following Monday) | Plausible and documented (Ni/Pearson/Poteshman pinning effect), but orthogonal to Gap Fade — touches ORB/BB+KDJ regime logic instead. Separate research track. |
| External vendor backfill (FirstRate Data / Databento) for pre-market history beyond Moomoo's <2yr retention | Not needed yet — test against whatever window Moomoo actually returns first. Revisit only if that window proves too short for a meaningful sample (<30 gap-fade-eligible days). |

### ORB Short Live Verification — BLOCKED by our own kill switch, not just unfired (2026-06-16 correction)
**Status:** Code deployed, first live short hasn't fired. `STOP_SHORTS.txt` is intentionally
present on the VPS, disabling ORB short entries at runtime (checked in `mm/evals.py`, toggleable
from the dashboard). So the previous wording in this file ("market must break below OR low with
volume") was misleading on its own — that condition may well have occurred already; shorts can't
fire regardless while the kill switch is active. That part is confirmed (file is present, code
path is gated on it).
**Why the switch was flipped on:** The "Moomoo blocks shorting on this account" theory was raised
and then directly checked (2026-06-16) via `OpenSecTradeContext.acctradinginfo_query()` against
the live SIMULATE account — **disproven**. Result for US.IWM: `max_sell_short: 5705.0` (real
short-sell capacity available), `max_position_sell: 0.0` (no long position to sell, as expected).
The account-level `accinfo_query().max_power_short` field showing `N/A` is just an unpopulated
portfolio-level field (no open shorts exist yet to calculate it from) — not a restriction. So
shorting IS permitted on this account; the real reason `STOP_SHORTS.txt` was created is unknown
and needs to come from whoever flipped it on, not from an account-permissions theory.
**Downstream effect either way:** Gap Fade's short side (gap up → short) can't be live-verified
while `STOP_SHORTS.txt` stays in place, since its enablement gate depends on ORB short firing first.
Gap Fade's long side (gap down → long) is unaffected and could be verified independently.
**To revisit:** Find the actual original reason for `STOP_SHORTS.txt` (not account permissions —
that's ruled out). If there's no longer a reason to keep it, removing it unblocks both ORB and
Gap Fade short verification at once.

### Push Architecture (WebSocket exits)
**What it is:** Replace 60s polling with `StockQuoteHandlerBase` WebSocket. Intra-bar exits instead of end-of-bar.
**Gate:** Live trades show consistent exit slippage > 0.1% per trade. Current `slippage_bps` field is 0.0 in SIMULATE — need real fill data before this is justified.
**Revisit when:** slippage_bps readings from live fills show the 60s poll costs real edge.

### paper.py Refactor (Split into Smaller Modules) — COMPLETE 2026-06-16

**What was done:** mm/paper.py (1,200 lines / ~45 defs) split into 4 new modules + mm/risk.py gains.
6 commits on master, 173/173 tests pass, cert-diffed (byte-identical replay before/after).

**Final layout:**
| Module | Contents |
|---|---|
| `mm/clock.py` | now(), now_et(), today(), sleep(), is_market_open(), seconds_until_open() |
| `mm/events.py` | PaperEventLog, PaperPosition, position/ORB file I/O |
| `mm/execution.py` | _place_buy/sell/short/cover, _confirm_fill, _execute_entry/exit, _reconcile_positions |
| `mm/evals.py` | _eval_bb_kdj, _eval_vwap, _eval_vwap_pb, _eval_orb, _entry_attempted |
| `mm/risk.py` (gains) | _qty, _position_cap, _slot_dollars (sizing helpers; avoids evals→paper cycle) |
| `mm/paper.py` (trimmed) | loop + _latest_closed_candles + run_multi + back-compat re-exports (~340 lines) |

**Key architectural invariants discovered:**
- Use `from . import config as _config` + `_config.cfg.*` at runtime in any module replay might
  reload — `from .config import cfg` goes stale after `_reload_paper` replaces mm.config.cfg.
- `_slot_dollars` is a float; tests must set `mm.risk._slot_dollars` not `paper._slot_dollars`.
- `_reload_paper` must reload `mm.evals` so `_entry_attempted` resets between tests.
- `TestMarketHoursGuard` must use `monkeypatch.setattr(mm.clock, ...)` not direct assignment.

**Deploy:** `./deploy.sh` after market close. Refactor is behavior-identical (cert-diffed).

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

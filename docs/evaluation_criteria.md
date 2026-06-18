# Pre-Registered Evaluation Criteria

Written: 2026-06-10, before meaningful live data exists (6 trades total).

Purpose: decide *in advance* what live paper results would change our minds, so outcomes
can't be rationalized after the fact. These gates were set when we had no stake in any
particular result. Changing a gate after data starts arriving requires writing down why
in this file, with the date.

## The knob freeze

**No strategy parameter changes until a gate below trips or its sample size is reached.**

Exceptions:
- Bug fixes (wrong behavior vs documented intent) — always allowed.
- Infrastructure/risk config (MAX_DAILY_LOSS, position caps, polling) — not strategy knobs.
- A new, separately-validated strategy may be added; existing knobs stay frozen.

The biggest risk to this project is not a bad strategy — it's re-tuning parameters faster
than live data can validate them.

## VWAP PB (SPY + QQQ, 10:00 ET filter)

The 0/4 start (Jun 8–9) does NOT count against the strategy: all four entries were 9:50 ET
opening-noise trades under the old 9:45 filter, an identified mechanical cause now fixed.
The clock starts fresh at 2026-06-10 with `VWAP_PB_MIN_ENTRY_TIME=10:00`.

Backtest expectation: SPY OOS PF=1.655, QQQ OOS PF=1.072.

| Gate | Sample | Action |
|------|--------|--------|
| PF < 1.0 or win% < 40% | 20 trades | Suspend (remove from STRATEGIES), post-mortem before any re-tune |
| QQQ PF < 1.0 while SPY PF ≥ 1.2 | 15 trades/symbol | Drop QQQ from VWAP_PB_SYMBOLS (QQQ was marginal in backtest anyway) |
| Any entry logged before 10:00 ET | 1 trade | Bug — fix immediately |

## BB+KDJ (IWM/QQQ at w=3, SPY at w=0)

Backtest expectation at w=3 (corrected 2026-06-18, see amendment log): combined 44.5% win,
PF=1.195, 434 trades on the full dataset — better than the previous "thin edge" framing,
not worse. The w=3 lookback had a day-boundary leak bug (fixed); the old 41.7%/PF=1.107
figure below included contaminated trades. w=0 is still the strongest-validated signal
(PF 2.131 on the original 2022-2025 window, ~20 trades/yr combined) — that finding is
unaffected by the bug (w=0 has no rolling window to leak).

| Gate | Sample | Action |
|------|--------|--------|
| PF < 1.0 | 30 trades | Switch all symbols to w=0 (accept low frequency) — do not suspend, the w=0 edge is the best-validated finding in the project |
| Cross-age subset analysis: w=0-subset trades (kdj_cross_age=0) materially outperform w>0 trades | 3 months of data | Switch to w=0 |
| Zero entries fired | 4 weeks | Investigate signal pipeline (compare vs simulate_paper.py on same dates) — silence is a bug symptom, not patience |

`kdj_cross_age` is logged on every bar_eval/position_open so the subset comparison
requires no parallel runner. See scripts/analyze_trades.py BB+KDJ section.

## ORB (all three symbols, IWM at 30-min OR)

Backtest expectation: PF=1.215, 54.5% win, ~0.9 trades/day combined. Highest-confidence
strategy, but most execution-sensitive (breakout fills are competitive).

| Gate | Sample | Action |
|------|--------|--------|
| PF < 1.0 | 30 trades | Check slippage/fill quality FIRST (intended_price vs fill in JSONL, candle_age_s). Only touch strategy parameters if execution is clean |
| Avg fill worse than intended by > 5 bps | 15 trades | Execution problem — reduce polling latency or accept edge erosion; not a strategy knob issue |
| Win% < 40% with clean execution | 30 trades | Suspend and post-mortem |

## Portfolio-level

| Gate | Trigger | Action |
|------|---------|--------|
| MAX_DAILY_LOSS hit on 2 days in any 10-session window | — | Review concurrent-exposure stacking (scripts/analyze_portfolio.py) before resuming; consider MAX_CONCURRENT_POSITIONS |
| Broker reconciliation mismatch | 1 occurrence | Halt (existing Discord alert), manual review |

## Review cadence

- Weekly: run `python scripts/analyze_trades.py --all` and check samples against gates.
- Do nothing in between. Mid-week results are noise by construction of this document.

## Amendment log

- 2026-06-10: Initial version.
- 2026-06-10 (post-close): VWAP PB trade #1 (QQQ, entry 10:10 ET @ 707.20) VOIDED — does
  not count toward the 20-trade gate. The entry limit order pended 5.5 min; periodic broker
  reconciliation ran at minute 4, saw no broker position, and cleared local state. The order
  then filled at 706.67 and the position was never exit-managed (rode to 695 unmanaged).
  Entry logic itself was correct (10:00 filter, cross_count=1, flush-and-reclaim all valid).
  Hypothetical managed exit: VWAP_LOST at 10:50 ET @ 706.12 = −$1.08. Not counted either way.
  Fix: reconcile now checks entry-order status (filled → keep; pending within 30-min grace →
  keep; pending past grace → cancel + clear). VWAP PB gate counter remains 0/20.
- 2026-06-12: Replay-harness research (no gate or knob changes). (1) 2026 YTD through the
  real runner: vwap_pb PF 1.89 (+$24) — beats backtest expectation; orb PF 1.04 (+$14) —
  near its PF<1.0 gate line; bb_kdj w=3 PF 0.85 (−$8). (2) BB+KDJ w=0 counterfactual, 2026
  YTD: 10 trades, PF 0.98 — the 2022–25 w=0 edge (PF 2.13) does NOT reproduce in 2026
  (sample tiny; treat the gate's "switch to w=0" action with caution if it trips). (3) ORB
  afternoon cutoff REJECTED OOS: 2026 hours-12+ bleed (−$93/75 trades) contradicted by
  2022–25 (+$65/698 trades, PF 1.16) — see graveyard. If the ORB gate trips, slice live
  trades by entry hour as part of the post-mortem (scripts/analyze_orb_hours.py logs/).
- 2026-06-10 (post-close, audit): ORB trades #1–2 (Jun 4 SPY +$2.92, QQQ +$2.52) reclassified
  as UNVERIFIED — broker history shows neither exit executed (SPY sell cancelled unfilled at
  EOD; QQQ sell order failed outright). Entries and signal logic were valid; recorded PnL is
  model PnL, not executed PnL. ORB gate counter resets to 0/30 effective with the
  fill-confirmation deploy (2026-06-10). All gates now evaluate on confirmed-fill PnL only.
- 2026-06-18: BB+KDJ w=3 backtest expectation corrected. Found via systematic adversarial
  audit (not live data): KDJ_WINDOW_BARS lookback didn't respect calendar-day boundaries,
  letting the first 1-3 bars of a new trading day fire on a KDJ cross from the previous
  day's close. Verified 30-39% of historical w=3 entries (SPY 30%, QQQ 38%, IWM 39%) were
  contaminated. Fixed in mm/strategy.py/mm/evals.py (grouped by day now). Old-buggy vs
  new-fixed on full dataset: combined 627→434 trades, 41.8%→44.5% win, PF 1.136→1.195 —
  the contaminated trades were lower quality, not a wash. The w=0 finding (PF=2.131) is
  completely unaffected (no rolling window to leak at w=0) — re-verified exact match to
  the original number on the original data window. No live config changed; this is a
  backtest-expectation correction only. Full numbers in docs/strategy_graveyard.md
  "KDJ Day-Boundary Signal Leak". Does NOT reset the live gate counter — confirmed-fill
  PnL recorded live was computed by the (also-buggy) entry logic at the time, so live
  trades since 2026-06-11 may include some contaminated entries; not retroactively
  reclassified since the live decision was a legitimate consequence of the code as it
  existed then, unlike the Jun 4 ORB case above which was an execution-layer fiction.

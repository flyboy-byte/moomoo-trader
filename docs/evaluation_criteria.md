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

## Sizing a gate: check the ETA before picking N

Added 2026-08-24, after the bb_kdj gate sat at 30 trades for 2+ months while the same document
already stated the strategy's own backtest frequency (~20 trades/yr combined at w=0) — meaning
the gate as written needed **~18 months** to ever trip. Nobody did that arithmetic when 30 was
picked; it was a round number carried over from ORB's gate, which trades ~5x more often.

**Before writing any sample-size gate, compute and write down: backtest (or live, if backtest
unavailable) trades/week for the exact config being gated → weeks to reach N → an ETA.** If the
ETA is beyond ~4-6 months, either the N is wrong for this strategy's frequency, or the strategy
is understood in advance to need a long soak — in which case say so explicitly instead of
implying a normal gate. A gate nobody expects to trip within the project's real time horizon is
not a gate, it's decoration.

This does not mean shrinking N until it trips fast — a low-frequency edge (w=0 BB+KDJ) is
allowed to stay low-frequency; that's the point of it. It means the *threshold* has to be
picked with the frequency in view, not copied from a different strategy's cadence.

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

## BB+KDJ (SPY/IWM at w=0, QQQ at w=3 — corrected 2026-08-24, header had it backwards)

Backtest expectation at w=3 (corrected 2026-06-18, see amendment log): combined 44.5% win,
PF=1.195, 434 trades on the full dataset — better than the previous "thin edge" framing,
not worse. The w=3 lookback had a day-boundary leak bug (fixed); the old 41.7%/PF=1.107
figure below included contaminated trades. w=0 is still the strongest-validated signal
(PF 2.131 on the original 2022-2025 window, ~20 trades/yr combined) — that finding is
unaffected by the bug (w=0 has no rolling window to leak).

| Gate | Sample | Action |
|------|--------|--------|
| PF < 1.0 | 15 trades | Switch all symbols to w=0 (accept low frequency) — do not suspend, the w=0 edge is the best-validated finding in the project |
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

## BB+KDJ LOOSE (research lane, live 2026-07-04)

Added retroactively 2026-08-24 — see amendment log. This is the no-gate variant of BB+KDJ
(MIN_SIGNAL_SCORE ignored, no ADX/ranging filter). Its purpose is to measure what the bonus
gate is worth, so it is judged *relative to* bb_kdj, not on absolute PF.

| Gate | Sample | Action |
|------|--------|--------|
| loose PF < bb_kdj PF by ≥ 0.3 | 20 loose trades | The bonus gate is earning its complexity — document and keep both; no knob change |
| loose PF > bb_kdj PF by ≥ 0.3 | 20 loose trades | The bonus gate is costing money — post-mortem, consider lowering MIN_SIGNAL_SCORE on production bb_kdj |
| \|difference\| < 0.3 | 20 loose trades | Gate is neutral. Retire bb_kdj_loose (it is measurement scaffolding, not a strategy) |

## Gap Fade (live 2026-07-12)

Added retroactively 2026-08-24 — see amendment log. Fires at most once per symbol per day at
9:35 ET, so sample accrues slowly (~1 trade per 6 sessions across all three symbols).

| Gate | Sample | Action |
|------|--------|--------|
| PF < 1.0 | 20 trades | Suspend (remove from STRATEGIES), post-mortem before any re-tune |
| Per-symbol PF < 0.5 while combined PF ≥ 1.0 | 10 trades/symbol | Drop that symbol from gap_fade (mirrors the ORB-shorts precedent) |
| Zero entries fired | 6 weeks | Investigate the 9:35 trigger path — silence is a bug symptom |

## Symbol-level (cross-strategy)

Added 2026-08-24. All prior gates are per-strategy, which cannot see an effect that runs the
other way — a symbol that is bad *across* strategies. Live data through 2026-08-24 shows SPY
net negative in 5 of 5 strategies while QQQ is net positive in 4 of 5. That observation is what
prompted this section, so it is **not** a clean pre-registration; the gate below is set so the
decision still requires more data than the observation was made on.

| Gate | Sample | Action |
|------|--------|--------|
| A symbol is net negative in ≥ 4 of 5 strategies AND combined symbol PF < 0.8 | 50 trades on that symbol | Post-mortem before any action: check spread/slippage and per-strategy stop distances first. Only then consider dropping the symbol from SYMBOLS |
| A symbol is net positive in ≥ 4 of 5 strategies AND combined symbol PF > 1.5 | 50 trades on that symbol | Do **not** concentrate into it — record the finding and leave allocation alone (single-symbol concentration is how this project would blow up its own sample size) |

## Portfolio-level

| Gate | Trigger | Action |
|------|---------|--------|
| MAX_DAILY_LOSS hit on 2 days in any 10-session window | — | Review concurrent-exposure stacking (scripts/analyze_portfolio.py) before resuming; consider MAX_CONCURRENT_POSITIONS |
| Broker reconciliation mismatch | 1 occurrence | Halt (existing Discord alert), manual review |

## Review cadence

This document gates two different things on two different clocks — conflating them caused
confusion (amended 2026-06-18, see log).

- **Health/bug monitoring** — uptime gaps, stale candles, execution quality, log errors.
  Check as often as you want (`scripts/diagnose_logs.py`, `scripts/analyze_trades.py --all`).
  Daily is fine. Finding and fixing a bug is never "too early."
- **Gate/performance evaluation** — deciding whether a strategy's results are good or bad
  enough to act on. This is sample-size-gated, not calendar-gated: the trigger is a gate in
  this doc tripping (e.g. "30 trades reached"), not a day of the week. Looking at PnL more
  often doesn't make the data more meaningful — with 1-3 trades/day across all strategies,
  day-to-day swings are noise around an edge too small to see yet. Look whenever you want;
  just don't change a strategy's parameters off a sample smaller than its gate's threshold.

## Amendment log

- 2026-08-24 (gate ETAs): Computed actual weeks-to-trip for every open gate using live accrual
  rate. Two were broken: **bb_kdj's PF<1.0 gate at 30 trades needs ~13 months** at the live rate
  (0.53 trades/wk) — lowered to **15 trades** (~6.5 months, still slow but the strategy's known
  frequency, not a bug). **bb_kdj_loose's gate at 30 needs ~4.6 months** — lowered to **20**
  (~3.1 months). Neither strategy's entry/exit logic changed; only the sample size that decides
  when to look. Added a "Sizing a gate: check the ETA before picking N" section above the knob
  freeze so future gates are written against the strategy's own accrual rate instead of a round
  number — the 30-trade figure for bb_kdj was traceable to ORB's gate, a strategy that trades
  ~5x more often, and nobody re-derived it for BB+KDJ's actual frequency.
  Also corrected the BB+KDJ section header, which had SPY/IWM's window assignment backwards
  (said "IWM/QQQ at w=3, SPY at w=0"; live config is SPY+IWM at w=0, QQQ at w=3).
  Current ETAs at live pace: vwap_pb SPY symbol-gate ~1.6wk, SPY cross-strategy gate ~2.7wk,
  gap_fade IWM ~4.1wk, gap_fade combined ~6.1wk, bb_kdj_loose ~12.6wk (new gate), IWM
  cross-strategy ~11.6wk, bb_kdj ~26wk (new gate). No strategy has an indefinite ETA now.
- 2026-08-24: **Added three missing gate sections: BB+KDJ LOOSE, Gap Fade, Symbol-level.**
  bb_kdj_loose went live 2026-07-04 and gap_fade 2026-07-12 — both had accumulated live trades
  for 6-7 weeks with *no* pre-registered gate in this file. That is the exact failure mode this
  document exists to prevent, and it happened silently because the file was only ever updated
  when a gate tripped, never when a strategy was added.
  **Honesty caveat:** these gates were written *after* seeing 11 bb_kdj_loose and 10 gap_fade
  trades, so they are retroactive, not pre-registered. They are deliberately set above the
  current sample (20 for gap_fade vs 10 today; 10/symbol vs 6 for IWM today; 50/symbol vs 40
  for SPY today) so that acting on them still requires data we do not yet have. Treat any
  conclusion drawn from them as weaker than one from a genuinely pre-registered gate.
  **New process rule:** adding a strategy to `STRATEGIES` requires adding its gate section here
  in the same change. No exceptions.
  No existing gate thresholds or live knobs were changed by this amendment.

  Gate standing at time of writing (102 live trades, 2026-06-10 → 2026-08-24, +$12.92, PF 1.189):

  | Strategy | Trades | PF | Gate | Status |
  |---|---|---|---|---|
  | vwap_pb | 28 | 2.46 | PF<1.0 @20 | passed, not tripped |
  | orb | 47 | 1.04 | PF<1.0 @30 | recovered from 0.76 (Jul 25) after ORB_LATEST_ENTRY; not tripped |
  | bb_kdj_loose | 11 | 1.73 | vs bb_kdj @20 (resized 08-24, was 30) | 11/20, ~9wk to ETA |
  | gap_fade | 10 | 0.29 | PF<1.0 @20 | 10/20, **on track to trip, ~6wk ETA** |
  | bb_kdj | 6 | 1.32 | PF<1.0 @15 (resized 08-24, was 30) | 6/15, ~17wk to ETA |

  Two findings recorded but **not acted on**, both below their gate:
  (1) vwap_pb on SPY is 2/13 wins, PF 0.09, and every one of the 13 exited `VWAP_LOST` — no
  stop, no target, no time stop. QQQ shares the same exit rule but has a right tail (one 47-min
  runner) that SPY never produces. Sample is 13 vs the 15-trade symbol gate — two trades short.
  (2) gap_fade on IWM is 2/6, PF 0.09, −$4.23 of the strategy's −$4.52 total. Sample is 6 vs
  the new 10-trade symbol gate.
- 2026-06-18: Reworded "Review cadence" — "weekly, do nothing in between" was read as
  forbidding daily bug/health checks, which was never the intent (the events.py UTC-vs-ET
  timestamp bug found this same day was caught by exactly that kind of daily check). The
  actual constraint is sample-size-gated (don't re-tune off too few trades), not calendar-
  gated (don't look more than once a week). No gate thresholds or knobs changed.
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

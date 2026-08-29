# Research Reset — Measurement Rebuild + Universe Expansion

> **Status:** Scoped 2026-08-29, not started. Two goals, sequenced (A gates B).
> **Supersedes as top priority:** Route 2b Phases 2–6 (`docs/expansions/route-2b-volatility-engine.md`)
> — parked, not cancelled. Phase 1 keeps collecting `vol_state.jsonl` for free.
> **Does not touch:** the live paper runner. It keeps running unchanged throughout.

## Why this exists

The audit on 2026-08-29 produced a number that isn't in any report. `analyze_trades.py` prints
AvgBps per strategy next to its own note that round-trip spread+slip ≈ 1–3 bps. Weighted by
trade count across all 106 live trades:

| Strategy | n | AvgBps | vs 1–3 bps hurdle |
|---|---|---|---|
| bb_kdj | 6 | +2.5 | inside the noise band |
| bb_kdj_loose | 11 | +5.9 | clears |
| gap_fade | 12 | −9.3 | badly negative |
| orb | 48 | +0.6 | **below cost** |
| vwap_pb | 29 | +4.9 | clears |

**Portfolio-weighted: +1.31 bps.** That sits *inside* the project's own stated cost band, on
frictionless simulator fills — so the real figure is worse. "PF 1.123, +$8.94" describes a system
whose measured edge is approximately its own cost of trading. ORB is the sharpest case: 45% of all
activity, the most-tuned strategy in the repo, returning below the spread, with a gate that reads
"passed."

Three reasons the framework couldn't see this:

1. **No dollar accounting.** Everything is per-share PnL; `analyze_portfolio.py` says outright
   "not directly comparable at size." The project cannot state its own return on capital.
2. **No benchmark.** No null hypothesis. SPY did roughly +2% over the same window.
3. **No confidence intervals.** At n=106, avg +$0.08/trade, the t-stat is well under 1. Every PF
   in that table is consistent with zero edge.

And the structural cause underneath all three: **the project runs a trading desk's process on a
research desk's problem.** A trading desk is capital-constrained — correlation matters, position
caps matter, you evaluate slowly to protect real money. A research desk is *information*-
constrained — you want maximum instances of a pattern and capital is irrelevant because nothing is
deployed. Every piece of discipline in `evaluation_criteria.md` is correct and premature. 5
strategies × 3 correlated ETFs at ~1.8 trades/day guarantees no strategy reaches significance for
months (the gate doc concedes bb_kdj needs ~26 weeks to reach 15 trades).

The fix is not "trade more often" — at +1.31 bps, more frequency against a fixed cost makes it
worse. The fix is to stop using live paper to answer the edge question. Live paper's job was always
execution validation, and it passed that months ago.

## Scoping findings (verified live 2026-08-29, do not re-derive)

Measured against the real VPS OpenD connection and the real local archives:

| Finding | Value | Consequence |
|---|---|---|
| `history_kl_quota` | **100 total, 3 used, 97 free** | Hard cap on universe size. See below. |
| Quota model | Rolling — `request_time` refreshes per pull; a symbol not pulled for 30d frees its slot | Universe is ~one-shot per 30 days. Selection must be right first time. |
| `sub_quota` | 100 total, **0 used** | Live runner polls `request_history_kline`; it never subscribes. No conflict. |
| Quote rights | `us_qot_right=LV3`, `us_option_qot_right=NO` | US equities fine. Confirms (again) no options/IV. |
| 5-min history depth | **≥ 2019-01-02** (tested 2019/2022/2024, all returned data) | ~7.7 years available, far more than the 2y assumed in `fetch_daily_archive.py`. |
| Fetch speed | 0.06–0.07 s per 1000-bar page | ~137 pages for 7y of one symbol ≈ 10s unthrottled. Fetch is *not* the bottleneck. |
| Local archives | 2022-01-03 → 2026-06-25, 1119 trading days, ~87k bars/symbol | 4.5 years already on disk for SPY/QQQ/IWM. |
| VPS archives | ~4.5k rows (~58 days) | VPS only has its own short rolling archive. Local is the real one. |
| **Replay throughput** | **>17 min per symbol-year (5 strategies) — killed, unfinished** | 100 sym × 4.5y ≈ **>5 days single-threaded.** Not viable for a wide scan. |
| **Fast engine throughput** | **1.56 s per symbol-year per strategy** | 100 sym × 4.5y × 5 strat ≈ **~56 min single-threaded.** Viable. |
| VPS RAM | 7 GB total, ~5 GB available | Naive all-symbols-in-memory replay would OOM. Shard by symbol. |

**The ~650× gap between the two engines is the central architectural fact of this plan.**
`mm/replay.py` recomputes every indicator over the full lookback window on every bar — that's the
price of running the *real* code path, and it's worth paying for confirmation, not for search.

## Goal A — Measurement Rebuild

**A ruler before more measuring.** Expanding the universe first would produce 15,000 trades nobody
can interpret. Everything here is reporting/analysis only — no strategy logic changes, no knob
changes, no live config changes.

### A1 — Cost model (the highest-value single change)
Every engine currently reports frictionless fills. Add a configurable per-symbol round-trip cost
haircut applied at the point PnL is computed, so every downstream number is net of costs by
default. Gross stays available but stops being the headline.

- Per-symbol spread estimate, not one global constant — this matters enormously for Goal B (SPY
  is ~1 bp round trip; a large-cap single name is 5–20 bps, and a strategy that clears costs on SPY
  can be structurally impossible on a stock).
- Default to a deliberately pessimistic figure. Optimism here invalidates everything after it.

### A2 — Dollar accounting and return on capital
Replace per-share PnL as the reporting unit. Requires an explicit capital base and sizing model
(`TOTAL_CAPITAL=0` currently disables sizing entirely and falls through to `MAX_POSITION_DOLLARS`).
Output: equity curve in dollars, return on deployed capital, and exposure-adjusted return
(these strategies hold minutes, so raw return understates capital efficiency — report both).

### A3 — Benchmark
SPY buy-and-hold over the identical window, on every report. Any strategy result that isn't
compared to it is uninterpretable.

### A4 — Confidence intervals
Bootstrap CI on PF and expectancy, plus n, reported inline everywhere PF is reported today. A PF
without an interval at n=106 is a number pretending to be evidence.

### A5 — Re-run history through the new ruler
Re-report all 106 live trades and the existing replay outputs with A1–A4 applied. **Expect the
current positive results to shrink or invert.** That is the point; it is a finding, not a failure.

**Gate A→B:** every existing report reproduces net of costs, in dollars, against benchmark, with
CIs. No new symbols fetched until this holds.

## Goal B — Universe Expansion

### B0 — The quota constraint shapes everything
97 free slots, effectively one shot per 30 days. Symbol selection is therefore a
**pre-registered decision made before looking at any returns**, exactly the discipline
`evaluation_criteria.md` already enforces for knobs.

Recommended allocation (decide before fetching):
- **~50 liquid ETFs** — sector SPDRs, index, bond, commodity. Tight spreads, closest to the domain
  these strategies were designed in. This is the honest test of whether the edge generalizes.
- **~35 high-liquidity single names** — mega-cap only. Wider spreads, so A1's per-symbol cost model
  is what makes them interpretable. Tests generalization to a harder cost regime.
- **~12 held in reserve.** Do not spend the full quota on the first pass.

Selection criteria fixed in advance (liquidity, median spread, price range, sector coverage), and
**survivorship bias documented explicitly** — picking "liquid names as of 2026" and testing back to
2022 selects for survival. Smaller effect for intraday mean reversion than for buy-and-hold, but
real, and it goes in the writeup rather than being quietly ignored.

### B1 — Bulk fetch
Extend `scripts/fetch_daily_archive.py` (don't rebuild it — `update_combined_csv` already
quarantines corruption and dedupes correctly). Needs: request throttling (Futu documents ~30
req/30s; the unthrottled 0.07s/page rate would trip it), resumability, and a quota pre-check that
refuses to start if it would exceed remaining slots. Target 2019→present where available.

### B2 — Engine cross-validation (**mandatory before trusting any wide-scan result**)
The fast engines and `mm/replay.py` are different code paths and are already known to disagree
(2026-06-12: replay vwap_pb PF 1.89 vs backtest expectation). Run both over SPY/QQQ/IWM on the same
window with A1 costs applied and quantify the disagreement. If it's large and unexplained, the wide
scan is measuring the engine, not the market — fix before proceeding.

### B3 — Wide scan
Fast engines across the full universe, sharded by symbol (memory, and per-symbol independence is
what edge measurement wants anyway). **Hard IS/OOS split chosen before results are viewed.**
100 symbols × 5 strategies × parameter sweeps is an overfitting machine; the knob-freeze culture is
the right immune system and has to scale with the search space, not relax for it.

### B4 — Finalist confirmation
Only strategy/symbol combinations that clear costs by a meaningful margin in OOS go to
`mm/replay.py` for real-code-path confirmation. This is where the slow engine earns its cost —
on a handful of candidates, not 450 symbol-years.

## What this plan deliberately does NOT do

- **Does not touch the live paper runner.** It keeps running unchanged. Its job is execution
  validation, which is a different question from edge, and it is currently passing.
- **Does not change any strategy parameter, gate threshold, or live `.env` value.** Goal A is
  reporting only. Any deployment decision comes after B4, as a separate, evidenced choice.
- **Does not suspend gap_fade yet** — though it is the strongest candidate (PF 0.18 on 12 trades,
  degrading, shorts 1/7). Its 20-trade gate exists to prevent parameter fitting, not to delay a
  stop-loss on a losing strategy, and that distinction should be resolved explicitly rather than by
  drift. Flagged here; decision deferred to a deliberate call, not folded silently into this plan.
- **Does not go to 1-minute candles.** 5× the trades at a smaller move per trade against fixed
  costs is the wrong direction at +1.31 bps.
- **Does not resume Route 2b Phases 2–6.** Adding an LLM policy layer on top of an unmeasured base
  is more surface area on the problem this plan exists to fix. Phase 1 keeps logging for free.

## The honest endgame

At n≈15,000 net of realistic costs, this may show that retail intraday mean reversion on liquid US
equities has no edge — it is the most-competed trade in existence, so that is a live outcome.
**A hard null at that sample is a real finding** and frees the engine to be pointed somewhere less
crowded. The current structure cannot produce even that. The failure being fixed here is not that
the answer is bad; it is that no answer is reachable.

## Open decisions (for the user, not assumed)

1. **Capital base for A2.** What dollar figure should returns be computed against?
2. **ETF/single-name split in B0.** Recommendation above is 50/35/12 reserve; it is a judgment call
   about how far outside the design domain to test.
3. **gap_fade** — suspend now on 12 trades, or hold to the pre-registered 20?

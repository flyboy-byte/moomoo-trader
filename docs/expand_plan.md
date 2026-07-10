# Expansion Roadmap

Written: 2026-07-09. Pick one option and start — each section has enough detail to go
straight to implementation without re-researching. Options are independent; do them in
any order or skip any you're not interested in.

---

## Option 1: Deploy Gap Fade Live

**What it is:** Trade the opening gap at 9:35 ET. If a stock gaps up or down significantly
from the prior close, fade the gap (trade against the gap direction, expecting partial fill).

**Current state:** Fully implemented in `mm/gap_fade.py`. Backtested on 9 months of data.
Premarket fill% filter validated empirically and wired in shadow mode (logs `would_filter_skip`
but never blocks). Not in live STRATEGIES.

**What to do:**

1. Enable the premarket filter: set `GAP_PREMARKET_FILTER_ENABLED=true` in `.env`.
2. Wire `gap_fade` into `mm/paper.py`'s eval dispatch — add a branch in
   `_eval_symbol_all_strategies()` that calls a new `_eval_gap_fade()` in `mm/evals.py`.
3. Write `_eval_gap_fade()` in `mm/evals.py`: check signal from `run_gap_fade()` (one bar
   per day, fires at 9:35), place entry via `_execute_entry()`, track position, exit via
   `_execute_exit()`. Follow the same pattern as `_eval_orb`.
4. Add `gap_fade` to `_VALID_STRATEGIES` in `mm/config.py`.
5. Add `gap_fade` to `STRATEGIES` and `SYMBOLS` in `.env` (VPS).
6. Add `gap_fade` to `STRATS` list in `tests/test_replay.py`.

**Key risk:** Gap fade fires at the first 9:35 candle — execution quality is most important
here (price can move fast). The premarket fill% filter (`GAP_PREMARKET_FILL_PCT_MIN`) is the
main quality gate. Run a few replay sessions (`scripts/replay_paper.py`) before going live.

**Effort:** 2–4 hours. The engine is done; this is just wiring.

---

## Option 2: Expand VWAP Pullback

**Current state:** PF=7.4, +$85, 24 live trades. QQQ is carrying it (+$91); SPY slightly
negative (-$7). IWM not in `VWAP_PB_SYMBOLS` (was excluded after negative OOS in original
backtest on 2022–23 train / 2024–25 test window).

**What to do — before adding IWM:**

1. Run a fresh backtest on the current IWM archive (now extends to mid-2026):
   ```bash
   python scripts/backtest_vwap_pb.py logs/US_IWM_K_5M_combined.csv
   ```
2. If OOS PF > 1.0, add `US.IWM` to `VWAP_PB_SYMBOLS` in `.env` and deploy.

**What to do — tune QQQ further (optional):**

- `VWAP_PB_MAX_CROSSES=1` is the proven filter. Try tightening the flush depth
  (require a larger wick below VWAP) — sweep with `scripts/backtest_vwap_pb.py --sweep`.
- Don't change SPY config; it's barely sampled and the baseline PF from backtest is 1.655.

**Caution:** PF=7.4 on 24 trades is likely lucky. Don't expand aggressively until you hit
50+ QQQ trades. The gate in `docs/evaluation_criteria.md` is 20 trades / PF<1.0 — you've
cleared the floor, but it's still a small sample.

**Effort:** 1 hour backtest research + 10 min deploy if IWM looks good.

---

## Option 3: Dashboard — Make It Actually Useful

**Current state:** A text wall with P&L numbers, a kill switch, and a kill switch for the
kill switch. The htop panel was added but the core trading data is not visual.

**Three concrete improvements (do any or all):**

### 3a. Cumulative P&L Chart
Per-strategy P&L over time as a line chart. Pull from JSONL logs. Answers "is this working?"
at a glance instead of requiring a Python run.

- Backend: new `/api/pnl_history` endpoint in `scripts/web_dashboard.py`. Parse
  `position_close` events from all JSONL files, return `{strategy: [(date, cumulative_pnl)]}`.
- Frontend: simple SVG or Canvas line chart, one line per strategy, rendered on the main page.
- ~3 hours.

### 3b. Trade Log Table
Paginated, sortable table of recent closes. Columns: date, symbol, strategy, direction,
entry, exit, P&L, hold bars, reason (TARGET/STOP/etc.). Click a row to expand the full
event stream for that trade (entry → bar_evals during hold → exit).

- Backend: `/api/trades` endpoint, parse JSONL, return structured list.
- Frontend: HTML table with sort headers, expandable rows.
- ~4 hours.

### 3c. Strategy Scorecard
Live side-by-side comparison: PF, win%, trade count, net P&L per strategy. Updates
automatically from JSONL without requiring a manual script run. Replaces the mental
overhead of running `python -c "grep..."` every time you want a status check.

- Backend: extend existing `/api/summary` or add `/api/scoreboard`.
- Frontend: replace or augment the existing "TODAY" card.
- ~2 hours.

---

## Option 4: Go Experimental — Drop the Knob Freeze

**What this means:** The `docs/evaluation_criteria.md` knob freeze was written for a
"treat it like a real fund" mindset. It's a hobby. If something looks worth testing,
test it and deploy it. The gate thresholds are still useful as checkpoints, not laws.

**Concrete experiments worth running now:**

### 4a. BB+KDJ w=0 on 2026 YTD
The w=0 foundational finding (PF=2.13 on 2022–2025) showed signs of degrading in the
2026 YTD replay (PF=0.98 on 10 trades, tiny sample). Settle this:
```bash
python scripts/run_backtest.py logs/US_SPY_K_5M_combined.csv --start 2026-01-01
```
If w=0 looks better in 2026 than w=3, switch SPY+QQQ back to w=0.

### 4b. ORB: Symbol-by-Symbol Tuning
Live data shows IWM longs (+$26, 29 trades) and SPY longs (+$25, 72 trades) are both
positive, QQQ longs slightly dragging. Worth checking: does a tighter vol filter
(`ORB_VOL_MULT=1.5`) improve QQQ specifically? Quick sweep:
```bash
python scripts/backtest_orb.py logs/US_QQQ_K_5M_combined.csv --sweep
```

### 4c. Add IWM to BB+KDJ
IWM already runs bb_kdj (it's in SYMBOLS) but the backtest shows it has the best
win rate (45.0% at w=3). Consider: does adding IWM at w=0 as a separate override
(`KDJ_WINDOW_OVERRIDES=US.IWM:0`) improve results? Already supported in config.

**Effort:** Each is a 30-min backtest run + 10 min deploy if results are positive.

---

## Option 5: Something Completely Different

The infrastructure (5-min candle archive, backtest engine, paper runner, JSONL logging,
replay harness) runs any signal expressible as a pandas function on OHLCV data.

### 5a. Earnings Momentum (easiest)
Buy 1–2 weeks before a known earnings date, exit on the day. No execution risk beyond
normal market hours. Needs a calendar feed — `yfinance` has it (`Ticker.calendar`).

- Research: pull earnings dates for SPY components or just for QQQ/SPY/IWM ETFs,
  check price behavior in the 2-week window before each report date.
- No new infrastructure needed — uses existing backtest engine with a date-filtered signal.
- Probably 1 day of research.

### 5b. Sector Rotation (medium)
Compare relative strength of XLK, XLF, XLE, XLY weekly, hold the top 1–2 for a week.
Swing-trade timeframe, very different from intraday. Needs weekly candle fetch
(`--ktype K_W1` in `scripts/fetch_candles.py`).

- Existing `mm/indicators.py` has EMA; relative strength is just price / N-week EMA.
- New backtest script, new signal logic, but the plumbing is identical.
- Probably 2–3 days.

### 5c. VIX Regime as Entry Gate (easiest to wire)
Not a standalone strategy — layer VIX level onto existing strategies. E.g.:
"Only take BB+KDJ longs when VIX < 20" or "Only take ORB when VIX term structure is normal."
VIX daily data is already being fetched (`scripts/fetch_vix_morning.py`, stored in
`logs/vix_daily.jsonl`). Just wire it into `mm/evals.py` as an additional entry condition.

- Low effort; high potential to improve ORB and BB+KDJ in choppy/high-vol regimes.
- VIX regime filter was graveyard'd before (`docs/strategy_graveyard.md`) but that was
  as a hard block — a softer gate (raise or lower threshold by regime) wasn't tested.

### 5d. SPY/QQQ Spread Mean Reversion
Trade the ratio between SPY and QQQ (or IWM/SPY). When the ratio deviates from its
20-day mean by >1 stdev, go long the laggard and short the leader. Market-neutral.

- Needs simultaneous position tracking across two symbols — new logic in evals.
- More complex but genuinely interesting. Would require expanding execution layer.
- 1–2 day project.

---

## Deciding

No wrong answer. Some rough heuristics:

| If you want... | Pick |
|---|---|
| Fastest path to a 5th live strategy | Option 1 (Gap Fade) |
| Best return on time invested | Option 2 (VWAP PB / IWM) |
| Something to look at on the dashboard | Option 3 |
| Data-driven tuning of what's already running | Option 4 |
| Build something genuinely new | Option 5a or 5c |

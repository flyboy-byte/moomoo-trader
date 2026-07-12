# Expansion Roadmap

Written: 2026-07-09. Pick one option and start — each section has enough detail to go
straight to implementation without re-researching. Options are independent; do them in
any order or skip any you're not interested in.

---

## ~~Option 1: Deploy Gap Fade Live~~ — DONE (2026-07-12)

`gap_fade` is live on VPS. `_eval_gap_fade()` in `mm/evals.py`, wired into `mm/paper.py`'s
dispatch with one-trade-per-day persistence (`_load/_save_gap_fade_traded` in `mm/events.py`).
Replay tests cover it. Premarket filter still in shadow mode (logs `would_filter_skip`).

---

## ~~Option 2: Expand VWAP Pullback~~ — DONE (2026-07-12)

IWM backtest showed PF=1.332 on 265 OOS trades — passes the gate. Added `US.IWM` to
`VWAP_PB_SYMBOLS` in `.env` and deployed. QQQ still the main contributor; IWM is additive.

---

## ~~Option 3: Dashboard — Make It Actually Useful~~ — DONE (2026-07-12)

All three sub-items shipped:

- **3a (P&L Chart):** `/api/pnl_history` + Canvas chart; per-strategy cumulative lines, color-coded.
- **3b (Trade Log):** `/api/trades` + sortable HTML table with 30d/90d/all toggles.
- **3c (Scorecard):** `/api/scoreboard` + "ALL-TIME SCORECARD" card; trades/win%/PF/net P&L.
- **Bonus:** htop panel shows `py:run_paper`, `py:web_dashboard` etc. (full script name via `cmdline()`).

All load on page open with `days=0` (all-time). 30d/90d toggles filter by `?start=`.

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

### 4b. ORB: Symbol-by-Symbol Tuning — DONE (2026-07-12)
OOS sweeps run. Results: `ORB_VOL_MULT=1.5` (global, was 1.2) + per-symbol target mult overrides:
`ORB_TARGET_MULT_OVERRIDES=US.QQQ:2.0,US.IWM:1.0` (QQQ +4.3% PF, IWM +6% PF vs global 1.5×).
Deployed. `ORB_VOL_MULT_OVERRIDES` machinery also built for future per-symbol vol tuning.

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
- The graveyard entry on VIX regime is docs/history — not a prohibition. A softer gate
  (scale position size or filter entries by VIX level) was never tested and is worth trying.

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
| ~~Fastest path to a 5th strategy~~ | ~~Option 1 (Gap Fade)~~ — Done |
| ~~Best return on time~~ | ~~Option 2 (VWAP PB / IWM)~~ — Done |
| ~~Visual dashboard~~ | ~~Option 3~~ — Done |
| ~~ORB symbol-by-symbol tuning~~ | ~~Option 4b~~ — Done |
| Accumulate live data | All 5 strategies are live — wait for samples |
| Regime-aware entries | Option 5c (VIX gate on BB+KDJ or ORB) |
| Build something genuinely new | Option 5a (Earnings Momentum) or 5d (Spread) |

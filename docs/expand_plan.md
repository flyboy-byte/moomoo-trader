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

### ~~4a. BB+KDJ w=0 on 2026 YTD~~ — DONE (2026-07-21)
2026 YTD OOS: SPY bb_kdj is broken regardless of window (w=0: 3 trades -$1.67; w=3: 18 trades
-$10.46). Neither window is recoverable in current regime. IWM at w=0 dramatically better:
72% win, +24.1 bps/trade (18 trades) vs w=3 45% win, +5.4 bps (119 trades).
Deployed: `KDJ_WINDOW_OVERRIDES=US.SPY:0,US.IWM:0` (SPY override was pre-existing).

### 4b. ORB: Symbol-by-Symbol Tuning — DONE (2026-07-12)
OOS sweeps run. Results: `ORB_VOL_MULT=1.5` (global, was 1.2) + per-symbol target mult overrides:
`ORB_TARGET_MULT_OVERRIDES=US.QQQ:2.0,US.IWM:1.0` (QQQ +4.3% PF, IWM +6% PF vs global 1.5×).
Deployed. `ORB_VOL_MULT_OVERRIDES` machinery also built for future per-symbol vol tuning.

### ~~4c. Add IWM to BB+KDJ at w=0~~ — DONE (2026-07-21)
See 4a above. IWM w=0 deployed via `KDJ_WINDOW_OVERRIDES=US.SPY:0,US.IWM:0`.

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
| ~~BB+KDJ w=0 / IWM override~~ | ~~Option 4a/4c~~ — Done (2026-07-21) |
| Accumulate live data | All 6 strategies are live — wait for samples |
| Regime-aware entries | Option 5c (VIX gate) OR **Route 2 in docs/expansions/** |
| Find a non-textbook edge | **Route 1 in docs/expansions/** |
| Build something genuinely new | Option 5a (Earnings Momentum) or 5d (Spread) |

---

## This roadmap is complete. Forward plans live in `docs/expansions/`

All 5 original options are done or explored. The next phase is in
`docs/expansions/` — three routes (data mining, LLM signal layer, real money)
with a full phase-gated plan packet. Start at `docs/expansions/FRAMEWORK.md`.

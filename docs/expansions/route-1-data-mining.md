# Route 1 — Data Mining: Find a Real Anomaly

**Status:** Scaffolding — not started  
**Priority:** High (primary candidate)

## The Idea

Stop deploying textbook signals and start doing actual data science on the candle
archive that's been accumulating since 2024. 2+ years of SPY/QQQ/IWM 5-min candles
(RTH + extended). The question is: what's actually predictive in this data?

Not "does BB lower touch predict mean reversion" (already deployed). Something
non-obvious. Something you found by looking at this specific data.

## Why This Is Interesting

- The infrastructure is already built: candle archive, backtester, replay harness
- The research cycle is fast: write a hypothesis, write a sweep, read the output
- If you find an edge, deploying it is trivial (follows the `_eval_*` pattern in evals.py)
- A real anomaly found in your own data is more interesting to write about than any
  textbook strategy

## Candidate Hypotheses to Test

These are starting points, not commitments. Kill them fast if they don't show up.

### H1 — First-5-Minutes Predictive of Rest of Session

Does the direction and magnitude of the 9:30–9:35 candle predict anything about the
next 60 minutes? Candidates:
- Gap + continuation: gap up AND 9:30 candle green → QQQ net positive for 10am–11am?
- Reversal: gap up AND 9:30 candle red → fade plays win more often?
- Just range prediction: big first candle (ATR expansion) → higher session ATR?

**Data:** SPY/QQQ/IWM 5-min. Trivial to compute: extract first candle per day,
join to summary of 10am–11am returns.

### H2 — Gap Size × VIX Bands → Fade Success

The gap_fade strategy fires on all gaps above a threshold. Does fade success rate
vary by VIX regime AND gap size jointly? Candidates:
- Small gaps (<0.3%) in low VIX (<15): high fill rate?
- Large gaps (>0.8%) in high VIX (>20): gap continuation instead of fade?
- The current uniform 50% target might be wrong — right target depends on gap×VIX?

**Data:** gap_fade.py has the event log now. But with only a few weeks of live data,
this runs on the backtest engine. `run_gap_fade()` returns all trades with gap_pct.
Cross with vix_daily.jsonl (already backfilled 2024→now).

### H3 — Intraday Return Autocorrelation at 5-Min Level

Is there serial correlation in 5-min returns for SPY? Does an up candle predict an
up candle (momentum) or a down candle (mean reversion) at different times of day?

- 9:30–10:30: momentum or mean-reverting?
- 10:30–12:30: different regime?
- 14:00–15:30: pre-close drift?

**Method:** compute 5-min returns, lag-1 autocorrelation by hour-of-day bucket.
If autocorrelation is positive → momentum signal. If negative → mean reversion
(validates the BB+KDJ premise in specific windows).

### H4 — Earnings Drift Adjacent Sessions

In the T+0 session after earnings (pre-announced by AAPL/MSFT/NVDA earnings dates),
do SPY/QQQ show persistent directional drift or higher mean-reversion opportunity?

**Data:** public earnings calendar. Cross with our candle archive. Compute return
distribution vs non-earnings days.

## Tooling to Build

- `scripts/mine_first_bar.py` — H1: loads all CSVs, extracts first-bar stats, runs
  correlation vs subsequent session returns
- `scripts/mine_autocorrelation.py` — H3: lag-1 autocorr by hour bucket, plots
  (ASCII or saves to CSV for plotting)
- Extend `scripts/backtest_gap_fade.py --sweep-vix` — H2: segment by VIX band,
  show PF and target-fill rate per band

## Decision Criteria

A finding is worth deploying if:
- OOS PF ≥ 1.2 on ≥ 100 trades (same gate as existing strategies)
- The signal direction is stable across rolling 30-day windows (walk-forward)
- The mechanism makes economic sense (not just data mining noise)

If the finding is too subtle or too low-frequency to deploy, it's still worth
documenting here as a "known edge" for future research.

## Relationship to Existing Strategies

A data-mining finding doesn't have to replace anything. It might:
- Add a time-of-day filter to BB+KDJ entries (already partially explored with
  `scripts/sweep_session_filter.py`)
- Add a gap-context filter to ORB (does ORB work better when gap direction aligns?)
- Stand alone as a new strategy (`_eval_anomaly_X` in evals.py, toggleable via STRATEGIES=)

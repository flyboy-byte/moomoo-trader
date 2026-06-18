# moomoo-trader

![Python](https://img.shields.io/badge/python-3.12+-blue)
![Tests](https://img.shields.io/badge/tests-182%20passing-brightgreen)
![Trading](https://img.shields.io/badge/trading-paper%20only-orange)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

A systematic strategy research and paper-trading platform built on the [Moomoo API](https://openapi.moomoo.com/moomoo-api-doc/). Three independently validated strategies run simultaneously on multiple symbols, with full backtesting, walk-forward validation, Discord alerts, and live dashboards.

> **No live orders are ever placed.** All trading runs through Moomoo's simulated paper environment (`TRD_ENV=SIMULATE`). Every order attempt checks this before executing.

---

## How it works

```
┌──────────────────────────────────────────────────────────────────────┐
│                           moomoo-trader                              │
│                                                                      │
│  ┌──────────┐    ┌──────────────────────────────────────────────┐   │
│  │  OpenD   │───▶│  Paper Runner (polls every 60s)              │   │
│  │ :11111   │    │                                              │   │
│  └──────────┘    │  fetch candles (once per symbol)             │   │
│                  │              │                               │   │
│                  │    ┌─────────┼──────────┐                   │   │
│                  │    │         │          │                    │   │
│                  │  BB+KDJ    ORB      VWAP PB  ← all run on   │   │
│                  │ signals  signals   signals     same candles  │   │
│                  │    │         │          │                    │   │
│                  │    └─────────┼──────────┘                   │   │
│                  │              │                               │   │
│                  │  risk checks → SIMULATE order                │   │
│                  │  position state (per symbol × strategy)      │   │
│                  │  JSONL event log                             │   │
│                  └──────────────┬───────────────────────────────┘   │
│                                 │                                    │
│           ┌─────────────────────┼─────────────────────┐             │
│           ▼                     ▼                     ▼             │
│      Discord alerts       TUI dashboard         Web dashboard        │
│  (entry/exit/EOD/alive)    (terminal)            (:8080)             │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Strategies

### BB+KDJ Mean Reversion

Enters when price touches the lower Bollinger Band with a KDJ golden cross, targeting a return to the BB midline. A signal confluence engine requires 2 of 3 bonus conditions to filter noise. `KDJ_WINDOW_BARS` allows the cross to have occurred in the N prior bars (grouped by calendar day — a day-boundary leak bug here was found and fixed 2026-06-18, see `docs/strategy_graveyard.md`), increasing signal frequency ~6.7-7.7× while maintaining out-of-sample edge on IWM and QQQ.

```
Entry:  close ≤ BB lower(20,2)
        AND KDJ(9,3) golden cross (within KDJ_WINDOW_BARS prior bars)
        AND 2+ bonus signals (RSI<35, ADX<25, volume spike)

Target: close ≥ BB middle
Stop:   close < entry − 1.0 × ATR(14)
Regime: ADX < 25 (ranging) — fires when ORB/momentum strategies are quiet
```

**Backtest results** — SPY+QQQ+IWM, 2022–2025, score ≥ 2:

| Symbol | Trades | Win% | Total PnL | Stop rate | Avg hold |
|--------|--------|------|-----------|-----------|----------|
| IWM | 21 | **61.9%** | +$8.33 | 38% | 132 min |
| SPY | 22 | 50.0% | +$7.81 | 50% | 309 min |
| QQQ | 17 | 41.2% | +$2.98 | 58% | 507 min |
| **Combined** | **60** | **51.7%** | **+$19.12** | **48%** | — |

Low frequency (~6 trades/year per symbol at `KDJ_WINDOW_BARS=0`; ~60/year at `w=3`). IWM has the strongest edge.

---

### Opening Range Breakout (ORB)

Trades the first directional impulse of the day. The opening range is established, then a breakout with volume confirmation triggers entry. Stop is structural (opposite OR boundary), not ATR-based. Per-symbol OR windows are supported — IWM performs better with a 30-min range.

```
Opening range: first ORB_MINUTES of session (15-min for SPY/QQQ, 30-min for IWM)

Entry:  close > OR high  AND  volume > 1.2× 20-bar MA
Stop:   OR low  (structural)
Target: entry + 1.5 × range height
Rules:  one trade per day per symbol  |  no entries after 15:45 ET
Filter: OR range must be 0.1%–0.8% of price (skips flat opens and news spikes)
```

**Backtest results** — SPY+QQQ+IWM, 2022–2025, 15-min OR, 1.5× target:

| Metric | Value |
|--------|-------|
| Trades | ~2,246 total (~0.9/day combined) |
| Win rate | 54.5% |
| Total PnL | +$346 |
| Profit factor | 1.215 |

> *Short entries are enabled by default (`ORB_SHORTS_ENABLED=true`). Disable via `touch STOP_SHORTS.txt` or the config editor.*

---

### VWAP Pullback (Flush-and-Reclaim)

Institutional-grade VWAP defense play. Enters when price wicks below VWAP intrabar but closes above it — indicating buyers stepped in to defend the level. A no-chop filter (session VWAP cross count ≤ 1) ensures the level has structural significance. Deployed on SPY and QQQ only; IWM fails out-of-sample.

```
Entry:  low < VWAP  (wick below)
        AND close > VWAP  (closes above — buyers defended)
        AND session VWAP cross count ≤ 1  (no-chop filter)
        AND volume < 20-bar MA  (quiet pullback, not distribution)
        AND bar time ≥ 10:00 ET

Exit:   close < VWAP  (level lost)
     OR close < entry − 1.0 × ATR(14)  (stop)
     OR 15:45 ET  (time stop)
```

**Backtest results** — SPY+QQQ, 2022–2025, OOS validation (train 2022–23, test 2024–25):

| Symbol | OOS Profit Factor | Deployed |
|--------|------------------|---------|
| SPY | **1.655** | ✓ |
| QQQ | **1.072** | ✓ |
| IWM | negative | ✗ excluded |

---

## Prerequisites

- [Moomoo](https://www.moomoo.com) account (free; paper trading is free)
- [OpenD](https://openapi.moomoo.com/moomoo-api-doc/) installed and running at `127.0.0.1:11111`
- Python 3.12+

---

## Quick start

```bash
git clone https://github.com/flyboy-byte/moomoo-trader.git
cd moomoo-trader

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env:
#   SYMBOLS=US.IWM,US.SPY,US.QQQ
#   STRATEGIES=bb_kdj,orb,vwap_pb
#   MAX_POSITION_DOLLARS=900        ← must cover one share (IWM ~$285, SPY ~$755, QQQ ~$745)
#   VWAP_PB_SYMBOLS=US.SPY,US.QQQ  ← exclude IWM from VWAP PB
#   ORB_MINUTES_OVERRIDES=US.IWM:30 ← IWM uses 30-min opening range
#   KDJ_WINDOW_BARS=3               ← accept KDJ cross within 3 prior bars
#   DISCORD_WEBHOOK_URL=...         ← optional but recommended

python scripts/health_check.py      # confirm OpenD is reachable

# Fetch historical candles
python scripts/fetch_candles.py --symbol US.IWM --start 2022-01-01 --end 2025-12-31
python scripts/fetch_candles.py --symbol US.SPY --start 2022-01-01 --end 2025-12-31
python scripts/fetch_candles.py --symbol US.QQQ --start 2022-01-01 --end 2025-12-31

# Backtest each strategy
python scripts/run_backtest.py --latest          # BB+KDJ
python scripts/backtest_orb.py --all             # ORB
python scripts/backtest_vwap_pb.py --all         # VWAP Pullback

# Run
./start.sh
python scripts/dashboard.py         # terminal dashboard in a second window
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TRD_ENV` | `SIMULATE` | **Never change.** All orders go to the paper account |
| `LIVE_TRADING_ENABLED` | `false` | Hard kill switch checked before every order |
| `SYMBOLS` | `US.SPY` | Comma-separated: `US.IWM,US.SPY,US.QQQ` |
| `STRATEGIES` | `bb_kdj` | Active strategies: `bb_kdj`, `orb`, `vwap_pb` (comma-separated) |
| `MAX_POSITION_DOLLARS` | `50` | Max notional per trade — **raise before trading** |
| `SYMBOL_SIZE_OVERRIDES` | _(empty)_ | Per-symbol cap: `US.IWM:300,US.SPY:600` |
| `MAX_TRADES_PER_DAY` | `3` | Daily trade limit across all strategies combined |
| `MAX_DAILY_LOSS` | `20` | Daily loss limit in dollars |
| `ATR_STOP_MULT` | `1.0` | BB+KDJ stop multiplier (1.0 validated optimal) |
| `MIN_SIGNAL_SCORE` | `2` | Bonus signals required for BB+KDJ entry (0–3) |
| `KDJ_WINDOW_BARS` | `0` | Look back N bars for KDJ cross at BB touch, grouped by day (3 = ~6.7-7.7× more signals) |
| `ORB_MINUTES` | `15` | Opening range window in minutes |
| `ORB_MINUTES_OVERRIDES` | _(empty)_ | Per-symbol OR window: `US.IWM:30,US.QQQ:15` |
| `ORB_TARGET_MULT` | `1.5` | ORB target = entry + N × range height |
| `VWAP_PB_SYMBOLS` | _(all)_ | Symbols to trade VWAP PB on: `US.SPY,US.QQQ` |
| `VWAP_PB_STOP_MULT` | `1.0` | VWAP PB ATR stop multiplier |
| `VWAP_PB_MAX_CROSSES` | `1` | Max session VWAP crosses before signal is void |
| `EXIT_ON_KDJ_DEATH` | `false` | KDJ death cross exit (research shows it hurts PnL) |
| `DISCORD_WEBHOOK_URL` | _(empty)_ | Trade alerts, daily heartbeat, EOD summary |

---

## Dashboards

**Terminal TUI** — 4 tabs: Overview, Trades, Signals, Log. Auto-refreshes every 5s. No market connection needed.
```bash
python scripts/dashboard.py                      # live session
python scripts/dashboard.py --date 2026-06-02    # review past session
```

**Web dashboard** — auto-refreshing browser page, accessible from any device on the network.
```bash
python scripts/web_dashboard.py    # http://localhost:8080
```

**Discord** — if `DISCORD_WEBHOOK_URL` is set:
- Runner started / new session heartbeat (daily)
- Entry and exit alerts with price, stop, P&L
- EOD summary at market close (4 PM ET)
- Error backoff alerts

---

## Research findings

| Finding | Result |
|---------|--------|
| Optimal ATR stop multiplier | **1.0×** — best PF (1.474) and walk-forward consistency (56%) |
| Optimal signal score | **2** — filters to 60 trades, flips exit split to target-dominant |
| Best timeframe | **K_5M** — K_15M produces *more* stops, not fewer |
| Best BB+KDJ symbol | **IWM** — 61.9% win, 38% stop rate, 132 min avg hold |
| KDJ death cross exit | **Disabled** — re-enabling flips SPY PnL from +$2.34 → −$0.83 |
| Optimal regime filter | **ADX < 25** — 7 alternatives tested, ADX ranging is best |
| KDJ window bars | **w=3** — ~6.7-7.7× more signals on IWM/QQQ, OOS PF > 1.1; SPY fails at w > 0. A day-boundary leak in the lookback (fixed 2026-06-18) had been contaminating 30-39% of entries — corrected numbers are *better*, not worse, see strategy_graveyard.md |
| VWAP Pullback | **Deployed** — OOS PF 1.655 (SPY), 1.072 (QQQ); IWM excluded (fails OOS) |
| VWAP crossover | **Abandoned** — PF ≈ 1.0, avg hold = 1 bar (structural noise issue) |
| EMA5/EMA20 momentum | **No edge** — cross entry uniformly negative; pullback stop inert (EMA20 always breaks first before ATR stop) |

---

## Safety

- `TRD_ENV=SIMULATE` — all orders target Moomoo's paper account, never live
- `LIVE_TRADING_ENABLED=false` checked in code before every order attempt
- `touch STOP_TRADING.txt` pauses the loop without killing the process
- Position state persists to disk — safe to restart mid-session
- No secrets in code — all config via `.env` (gitignored)

---

## Project layout

```
mm/                        core package
  config.py                .env loading, typed config singleton
  clock.py                 time seam — now()/now_et()/today()/is_market_open(), single patch point for tests/replay
  indicators.py            BB, ATR, KDJ, RSI, ADX, VWAP, EMA, BB width percentile
  signals.py               BB+KDJ signal scoring engine
  strategy.py              BB+KDJ entry/exit state machine (backtest engine)
  orb_strategy.py          ORB signal engine and backtest helpers
  vwap_pullback.py         VWAP Pullback backtest engine
  vwap_strategy.py         VWAP crossover (deprecated, PF ≈ 1.0)
  ema_momentum.py          EMA5/EMA20 momentum research (not deployed)
  gap_fade.py              Gap Fade backtest engine (research only, not in live STRATEGIES)
  premarket.py             pre-market fill%/volume-ratio helpers (research, not live-wired)
  paper.py                 multi-strategy paper-trading loop (run_multi, candle fetch)
  events.py                PaperEventLog (JSONL), PaperPosition, position/ORB-tracker persistence
  execution.py             order placement, fill confirmation, broker reconciliation
  evals.py                 per-strategy live eval functions (_eval_bb_kdj, _eval_orb, _eval_vwap_pb)
  replay.py                replay harness — drives the real live code path against historical candles
  backtest.py              backtester, walk-forward, print_summary, canonical profit_factor()
  research.py              parameter sweeps, variant comparison
  risk.py                  kill switch, daily limits, position sizing
  notifications.py         Discord webhook alerts
  data.py / health.py / connection.py / logger.py

scripts/
  run_backtest.py          BB+KDJ backtest
  backtest_orb.py          ORB backtest
  backtest_vwap_pb.py      VWAP Pullback backtest (--sweep, --all)
  backtest_ema_momentum.py EMA momentum research (--sweep, --entry cross|pullback)
  research_premarket_gap.py  Gap Fade pre-market fill% research (not live)
  walk_forward.py          walk-forward validation
  sweep.py                 ATR stop + entry parameter grid search
  sweep_signals.py         regime filter comparison
  multi_backtest.py        compare across multiple symbols / timeframes
  simulate_paper.py        replay historical CSV through paper logic
  replay_paper.py          drive the REAL paper runner against historic candles + a fake broker
  replay_vs_live.py        diff a live session's decisions against a replay of the same day
  compare_paper_vs_backtest.py  validate paper runner vs backtester
  diagnose_logs.py         session health: uptime gaps, signal rates, staleness, why-no-entry
  analyze_trades.py / analyze_portfolio.py / analyze_orb_hours.py  post-hoc trade analysis
  eod_summary.py           end-of-day session recap (+ Discord post)
  weekly_report.py         weekly gate-progress + premarket Discord report (VPS cron)
  fetch_daily_archive.py   VPS daily rolling candle archive builder (cron)
  fetch_vix_morning.py     daily VIX shadow-logger (observational only, cron)
  flatten_simulate.py      clean orphaned SIMULATE broker shares
  dashboard.py             terminal TUI (Textual)
  web_dashboard.py         web dashboard (Flask, :8080)
  install_cron.sh          idempotent VPS cron installer
  verify.sh                one-command session health check (pytest + sync + diagnose + compare)
  fetch_candles.py / health_check.py / run_paper.py

start.sh                   start OpenD + paper runner
stop.sh                    stop paper runner
deploy.sh                  git pull + restart all services (run on local machine)
sync_logs.sh               rsync VPS logs → local logs/
```

---

## Tests

```bash
python -m pytest tests/ -q    # 182 tests: risk, indicators, signals, strategy, orb,
                               # clock, data, paper/evals/execution/replay
```

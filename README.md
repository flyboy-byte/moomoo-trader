# moomoo-trader

![Python](https://img.shields.io/badge/python-3.12+-blue)
![Tests](https://img.shields.io/badge/tests-89%20passing-brightgreen)
![Trading](https://img.shields.io/badge/trading-paper%20only-orange)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

A systematic strategy research and paper-trading platform built on the [Moomoo API](https://openapi.moomoo.com/moomoo-api-doc/). Two independently validated strategies run simultaneously on multiple symbols, with full backtesting, walk-forward validation, Discord alerts, and live dashboards.

> **No live orders are ever placed.** All trading runs through Moomoo's simulated paper environment (`TRD_ENV=SIMULATE`). Every order attempt checks this before executing.

---

## How it works

```
┌─────────────────────────────────────────────────────────────────┐
│                         moomoo-trader                           │
│                                                                 │
│  ┌──────────┐    ┌────────────────────────────────────────┐    │
│  │  OpenD   │───▶│  Paper Runner (polls every 60s)        │    │
│  │ :11111   │    │                                        │    │
│  └──────────┘    │  fetch candles (once per symbol)       │    │
│                  │         │                              │    │
│                  │    ┌────┴────┐                         │    │
│                  │    │         │                         │    │
│                  │  BB+KDJ    ORB      ← both run on      │    │
│                  │ signals  signals      same candles     │    │
│                  │    │         │                         │    │
│                  │    └────┬────┘                         │    │
│                  │         │                              │    │
│                  │  risk checks → SIMULATE order          │    │
│                  │  position state (per symbol+strategy)  │    │
│                  │  JSONL event log                       │    │
│                  └───────────────┬────────────────────────┘    │
│                                  │                             │
│            ┌─────────────────────┼─────────────────────┐      │
│            ▼                     ▼                     ▼      │
│       Discord alerts       TUI dashboard         Web dashboard │
│   (entry/exit/EOD/alive)    (terminal)            (:8080)      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Strategies

### BB+KDJ Mean Reversion

Enters when price touches the lower Bollinger Band with KDJ golden cross confirmation, targeting a return to the BB midline. A signal confluence engine requires 2 of 3 bonus conditions to filter noise.

```
Entry:  close ≤ BB lower(20,2)
        AND KDJ(9,3) golden cross
        AND 2+ bonus signals (RSI<35, ADX<25, volume spike)

Target: close ≥ BB middle
Stop:   close < entry − 1.0 × ATR(14)
```

**Backtest results** — SPY+QQQ+IWM, 2022–2025, score ≥ 2:

| Symbol | Trades | Win% | Total PnL | Stop rate | Avg hold |
|--------|--------|------|-----------|-----------|----------|
| IWM | 21 | **61.9%** | +$8.33 | 38% | 132 min |
| SPY | 22 | 50.0% | +$7.81 | 50% | 309 min |
| QQQ | 17 | 41.2% | +$2.98 | 58% | 507 min |
| **Combined** | **60** | **51.7%** | **+$19.12** | **48%** | — |

Low frequency (~6 trades/year per symbol). IWM has the strongest edge.

---

### Opening Range Breakout (ORB)

Trades the first directional impulse of the day. The 9:30–9:45 opening range is established, then a breakout with volume confirmation triggers entry. Stop is structural (opposite OR boundary), not ATR-based.

```
Opening range: 9:30–9:45 ET high/low (15-min window)

Entry:  close > OR high  AND  volume > 1.2× 20-bar MA
Stop:   OR low  (structural)
Target: entry + 1.5 × range height
Rules:  one trade per day per symbol  |  no entries after 15:45 ET
```

**Backtest results** — SPY+QQQ+IWM, 2022–2025, optimal params (15-min OR, 1.5× target):

| Metric | Value |
|--------|-------|
| Trades | 2,246 total (~0.9/day combined) |
| Win rate | 54.5% |
| Total PnL | +$346 |
| Profit factor | 1.215 |
| Avg hold | ~3 hours |

All 8 tested parameter combinations passed hard validation gates (PF > 1.1, win > 45%).

> *Live runner is long-only. Short entries require `SELL_SHORT` margin handling not yet wired up.*

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
#   MAX_POSITION_DOLLARS=600        ← must cover one share (IWM ~$220, SPY ~$560)
#   STRATEGIES=bb_kdj,orb
#   DISCORD_WEBHOOK_URL=...         ← optional but recommended

python scripts/health_check.py      # confirm OpenD is reachable

# Fetch historical candles
python scripts/fetch_candles.py --symbol US.IWM --start 2022-01-01 --end 2025-12-31
python scripts/fetch_candles.py --symbol US.SPY --start 2022-01-01 --end 2025-12-31
python scripts/fetch_candles.py --symbol US.QQQ --start 2022-01-01 --end 2025-12-31

# Backtest
python scripts/run_backtest.py --latest
python scripts/backtest_orb.py --latest

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
| `SYMBOLS` | `US.SPY` | Comma-separated symbols: `US.IWM,US.SPY,US.QQQ` |
| `STRATEGIES` | `bb_kdj` | Active strategies: `bb_kdj`, `orb`, or `bb_kdj,orb` |
| `MAX_POSITION_DOLLARS` | `50` | Max notional per trade — **raise this before trading** |
| `MAX_TRADES_PER_DAY` | `3` | Daily trade count limit (shared across all strategies) |
| `MAX_DAILY_LOSS` | `5` | Daily loss limit in dollars |
| `ATR_STOP_MULT` | `1.0` | BB+KDJ stop multiplier (1.0 is validated optimal) |
| `MIN_SIGNAL_SCORE` | `2` | Bonus signals required for BB+KDJ entry (0–3) |
| `ORB_MINUTES` | `15` | Opening range window (15 optimal per sweep) |
| `ORB_TARGET_MULT` | `1.5` | ORB target = entry + N × range height |
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

**Discord** — if `DISCORD_WEBHOOK_URL` is set, you get:
- Runner started / new session heartbeat (daily)
- Entry and exit alerts with price, stop, P&L
- EOD summary at market close (4 PM ET)
- Error backoff alerts

---

## Research findings summary

| Finding | Result |
|---------|--------|
| Optimal ATR stop multiplier | **1.0×** — best PF (1.474) and walk-forward consistency (56%) |
| Optimal signal score | **2** — filters to 60 trades, flips exit split to target-dominant |
| Best timeframe | **K_5M** — K_15M produces *more* stops, not fewer |
| Best symbol | **IWM** — 61.9% win, 38% stop rate, 132 min avg hold |
| KDJ death cross exit | **Disabled** — re-enabling flips SPY PnL from +$2.34 → −$0.83 |
| Optimal regime filter | **ADX < 25** — 7 alternatives tested, ADX ranging is best |
| VWAP strategy | **Abandoned** — PF ~1.0, avg hold = 1 bar (noise at 5-min resolution) |

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
mm/                      core package
  config.py              .env loading, typed config singleton
  indicators.py          BB, ATR, KDJ, RSI, ADX, VWAP, BB width percentile
  signals.py             BB+KDJ signal scoring engine
  strategy.py            BB+KDJ entry/exit state machine
  orb_strategy.py        ORB signal engine and backtest helpers
  paper.py               multi-strategy paper-trading loop
  backtest.py            backtester, walk-forward, print_summary
  research.py            parameter sweeps, variant comparison
  risk.py                kill switch, daily limits, position sizing
  notifications.py       Discord webhook alerts
  data.py / health.py / connection.py / logger.py

scripts/
  run_backtest.py        BB+KDJ backtest
  backtest_orb.py        ORB backtest
  walk_forward.py        walk-forward validation
  sweep.py               ATR stop + entry parameter grid search
  sweep_signals.py       regime filter comparison
  multi_backtest.py      compare across multiple symbols
  simulate_paper.py      replay historical CSV through paper logic
  compare_paper_vs_backtest.py  validate paper runner vs backtester
  eod_summary.py         end-of-day session recap (+ Discord post)
  dashboard.py           terminal TUI (Textual)
  web_dashboard.py       web dashboard (Flask, :8080)
  fetch_candles.py / health_check.py / run_paper.py

start.sh                 start OpenD + paper runner
stop.sh                  stop paper runner
deploy.sh                git pull + restart all services (run locally)
```

---

## Tests

```bash
python -m pytest tests/ -q    # 89 tests: risk, indicators, signals, strategy
```

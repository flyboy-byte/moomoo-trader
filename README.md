# moomoo-trader

Python research and paper-trading platform built on the [Moomoo API](https://openapi.moomoo.com/moomoo-api-doc/). Implements a BB + KDJ mean-reversion strategy with a signal confluence engine, full backtesting framework, walk-forward validation, and a live paper-trading loop with both a terminal dashboard and a web dashboard.

> **No live orders are placed.** All trading runs through Moomoo's simulated paper environment (`TRD_ENV=SIMULATE`).

---

## What this is

A complete AI-assisted stock strategy research and paper-trading platform. The core loop:

1. **Research** — sweep strategy parameters against 3+ years of historical candle data across SPY, QQQ, and IWM
2. **Validate** — walk-forward backtesting and pipeline simulation to confirm signal engine correctness
3. **Run** — live paper-trading loop that evaluates closed 5-min candles and places SIMULATE orders via Moomoo's API
4. **Monitor** — terminal TUI or web dashboard showing positions, signals, and daily P&L in real time

The strategy (BB + KDJ mean reversion) has been systematically researched and optimized across 77 trades and 3.5 years of data. See the Research Findings section for full results.

---

## Prerequisites

- A [Moomoo](https://www.moomoo.com) account (free to create, paper trading is free)
- OpenD installed and running — download from [Moomoo's developer page](https://openapi.moomoo.com/moomoo-api-doc/). Runs at `127.0.0.1:11111` by default
- Python 3.12+

---

## Clone and run

```bash
git clone https://github.com/flyboy-byte/moomoo-trader.git
cd moomoo-trader

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — key settings:
#   SYMBOLS=US.IWM                  (or US.SPY, US.QQQ)
#   MAX_POSITION_DOLLARS=300        (must cover at least one share)
#   STRATEGY_MODE=strict            (strict = full signal gate, permissive = looser entry)
```

Run the health check to confirm OpenD is reachable:
```bash
python scripts/health_check.py
```

Fetch historical candles to use for backtesting:
```bash
python scripts/fetch_candles.py --symbol US.IWM --start 2022-01-01 --end 2025-12-31
python scripts/fetch_candles.py --symbol US.SPY --start 2022-01-01 --end 2025-12-31
python scripts/fetch_candles.py --symbol US.QQQ --start 2022-01-01 --end 2025-12-31
```

Run a backtest:
```bash
python scripts/run_backtest.py --latest
```

Start paper trading:
```bash
./start.sh
python scripts/dashboard.py        # terminal dashboard (second window)
# or
python scripts/web_dashboard.py    # web dashboard at http://localhost:8080
```

---

## Quick start

```bash
cp .env.example .env
# Edit .env: set MAX_POSITION_DOLLARS to at least one share's price (IWM ~$220, SPY ~$560)
# Optionally set DISCORD_WEBHOOK_URL for trade alerts

./start.sh               # starts OpenD service + paper runner, warns on bad config
./stop.sh                # stops paper runner (OpenD stays up)

python scripts/dashboard.py    # open live terminal dashboard in a second window
```

`start.sh` checks that the OpenD port is alive before starting the runner and warns if `MAX_POSITION_DOLLARS` is too low to place any trade.

---

## Configuration

Key `.env` variables:

| Variable | Default | Description |
|---|---|---|
| `TRD_ENV` | `SIMULATE` | Never change — all orders are paper |
| `LIVE_TRADING_ENABLED` | `false` | Hard kill switch checked before every order |
| `SYMBOLS` | `US.SPY` | Comma-separated symbols for the paper runner |
| `CANDLE_KTYPE` | `K_5M` | Candle interval |
| `MAX_POSITION_DOLLARS` | `50` | Max notional per trade — **raise this before trading** |
| `MAX_TRADES_PER_DAY` | `3` | Daily trade count limit |
| `MAX_DAILY_LOSS` | `5` | Daily loss limit in dollars |
| `ATR_STOP_MULT` | `1.0` | Stop = entry − N × ATR(14) |
| `MIN_SIGNAL_SCORE` | `2` | Bonus confirmation signals required (0–3) |
| `EXIT_ON_KDJ_DEATH` | `false` | Re-enable KDJ death cross exit (research shows it hurts) |
| `DISCORD_WEBHOOK_URL` | _(empty)_ | Optional trade alerts via Discord |

---

## Strategy

**BB + KDJ mean reversion on 5-min closed candles.**

| | Condition |
|---|---|
| **Entry** | `close ≤ BB lower(20,2)` AND KDJ(9,3) golden cross AND bonus score ≥ `MIN_SIGNAL_SCORE` |
| **Exit — target** | `close ≥ BB middle` |
| **Exit — stop** | `close < entry_price − ATR_STOP_MULT × ATR(14)` |

### Signal confluence engine

The core gate (BB touch + KDJ golden cross) is always required. Three independent bonus signals provide confirmation:

| Signal | Condition | Fire rate on valid entries |
|---|---|---|
| `rsi_oversold` | RSI(14) < 35 | 97% |
| `volume_spike` | volume > 1.5× 20-bar MA | 88% |
| `ranging` | ADX(14) < 25 | 33% |

`MIN_SIGNAL_SCORE=2` requires 2 of 3 bonus signals. This is the validated optimum — it filters noise while keeping 60 of 77 trades and flipping the exit split to target-dominant.

---

## Research findings

All results on 199k 5-min candles, SPY + QQQ + IWM, 2022–2025. Sample sizes are small (60–77 trades over 3.5 years) — treat as directional, not definitive.

### Signal confluence (SPY+QQQ+IWM combined)

| Score threshold | Trades | Win% | Total PnL | Profit factor | Exit split |
|---|---|---|---|---|---|
| 0 — BB+KDJ only | 77 | 48.1% | +$15.49 | 1.474 | 52% stop / 48% target |
| 1 — 1 bonus required | 74 | 50.0% | +$17.56 | 1.573 | 50% / 50% |
| **2 — 2 bonus required *(default)*** | **60** | **51.7%** | **+$19.12** | **1.843** | **48% stop / 52% target** |
| 3 — all 3 bonus | 11 | — | — | — | too few trades |

### Multi-symbol breakdown (score ≥ 2)

| Symbol | Trades | Win% | Total PnL | Stop rate | Avg hold |
|---|---|---|---|---|---|
| SPY | 22 | 50.0% | +$7.81 | 50% | 309 min |
| QQQ | 17 | 41.2% | +$2.98 | 58% | 507 min |
| **IWM** | **21** | **61.9%** | **+$8.33** | **38%** | **132 min** |
| **Combined** | **60** | **51.7%** | **+$19.12** | **48%** | — |

IWM dominates: lowest stop rate, fastest reversals. Not explained by volatility — IWM's BB+KDJ signal is simply more predictive on this strategy.

### ATR stop multiplier sweep (77 trades, 90-day walk-forward windows)

| ATR mult | Win% | Total PnL | Profit factor | Consistency |
|---|---|---|---|---|
| 0.5 | 29.9% | −$1.19 | 0.962 | 15/39 = 38% |
| 0.75 | 39.0% | +$4.94 | 1.147 | 17/39 = 44% |
| **1.0 *(default)*** | **48.1%** | **+$15.49** | **1.474** | **22/39 = 56%** |
| 1.25 | 50.6% | +$13.16 | 1.349 | 23/39 = 59% |
| 1.5 | 54.5% | +$11.60 | 1.287 | 21/39 = 54% |
| 2.0 | 54.5% | +$5.10 | 1.109 | 19/39 = 49% |

ATR=1.0 has the best profit factor and near-best walk-forward consistency.

### Other findings

- **KDJ death cross exit disabled** — re-enabling it flips SPY PnL from +$2.34 → −$0.83. It cuts winning mean-reversion trades before they recover to BB middle.
- **K_5M is the right timeframe** — K_15M produces *more* stop-outs (59% vs 52%), not fewer. K_60M has 5 trades in 3.5 years; not actionable.
- **ADX ranging confirmed optimal** — 7 alternative regime filters tested (BB contracted/expanding variants). ADX < 25 is best for combined portfolio. BB contracted rarely co-occurs with entries (entries happen during band expansion, not contraction).

---

## Usage

All scripts run from the project root with the venv active.

### Start / stop the full stack

```bash
./start.sh    # start OpenD + paper runner (checks port, warns on bad config)
./stop.sh     # stop paper runner (OpenD stays up)
```

### Dashboards

**Terminal (Textual TUI):**
```bash
python scripts/dashboard.py                    # monitor today's live session
python scripts/dashboard.py --date 2026-06-02  # review a past session
```
Four tabs: **Overview** (positions per symbol, daily P&L, loss bar, config), **Trades** (entry/exit/P&L per trade), **Signals** (entries, blocks, skips), **Log** (raw JSONL stream). Auto-refreshes every 5s. `r` to refresh, `q` to quit. No OpenD connection needed.

**Web dashboard:**
```bash
python scripts/web_dashboard.py                # serves at http://localhost:8080
python scripts/web_dashboard.py --date 2026-06-02  # review past session
```
Auto-refreshing browser page showing runner status, signal feed (last 20 bars), open positions, trades, and daily P&L. Accessible from any device on the network. Useful for monitoring a remote VPS runner.

### Paper runner (manual)

```bash
python scripts/run_paper.py                          # uses SYMBOLS from .env
python scripts/run_paper.py --symbol US.IWM
python scripts/run_paper.py --symbols US.SPY,US.QQQ,US.IWM
```

- Polls OpenD every 60 seconds on closed candles only
- Position size: `floor(MAX_POSITION_DOLLARS / price)` — blocks if price exceeds cap
- Resets daily limits at midnight
- Kill switch: `touch STOP_TRADING.txt` pauses without stopping the process
- Position persists to disk — restarts safely recover open state
- Events logged to `logs/paper_{symbol}_{date}.jsonl`

### Health check

```bash
python scripts/health_check.py
```

### Fetch historical candles

```bash
python scripts/fetch_candles.py --start 2022-01-01 --end 2025-05-30
python scripts/fetch_candles.py --symbol US.IWM --ktype K_5M
```

### Backtest and research

```bash
python scripts/run_backtest.py --latest
python scripts/walk_forward.py --latest --window 90
python scripts/research.py --latest --exits --walk-forward
python scripts/sweep.py --latest --window 90
python scripts/sweep_signals.py --latest              # regime filter comparison
python scripts/multi_backtest.py --sweep              # all K_5M CSVs in logs/
```

### Validate pipeline

Simulate the paper runner on historical data (no market hours needed):
```bash
python scripts/simulate_paper.py logs/US_IWM_K_5M_2026-05-31.csv \
    --start 2024-01-01 --end 2025-05-30 --compare
```

Compare a live session against the backtester:
```bash
python scripts/compare_paper_vs_backtest.py logs/paper_US_IWM_2026-06-02.jsonl
```

---

## Running as a service

The paper runner can run as a systemd user service (alongside OpenD):

```bash
# Check status
systemctl --user status moomoo-paper.service

# View logs
journalctl --user -u moomoo-paper.service -f

# Enable auto-start on login (optional)
systemctl --user enable moomoo-paper.service
```

Service file at `~/.config/systemd/user/moomoo-paper.service`. Restarts automatically on failure with a 30s delay.

---

## Project layout

```
mm/
  config.py           .env loading, typed config singleton
  logger.py           file + console logging
  connection.py       OpenQuoteContext context manager
  health.py           socket + live quote health check
  data.py             historical candle fetcher with pagination
  indicators.py       BB(20,2), ATR(14), KDJ(9,3), RSI(14), ADX(14), BB width percentile
  signals.py          signal scoring engine (core gate + 3 bonus signals)
  strategy.py         entry/exit state machine, Trade/Signal types
  backtest.py         backtester, walk-forward, print_summary
  research.py         entry/exit variants, parameter sweeps, signal filter sweep
  risk.py             kill switch, daily limits, position sizing
  paper.py            live paper-trading loop (single + multi-symbol)
  notifications.py    optional Discord webhook alerts

scripts/
  health_check.py               confirm OpenD is reachable
  fetch_candles.py              fetch and save historical candles
  run_backtest.py               backtest over a saved CSV
  walk_forward.py               walk-forward backtest
  research.py                   compare entry/exit strategy variants
  sweep.py                      ATR stop multiplier + entry tolerance grid search
  sweep_signals.py              regime/ranging signal filter comparison
  multi_backtest.py             compare results across multiple symbols
  simulate_paper.py             replay historical CSV through paper-trading logic
  compare_paper_vs_backtest.py  validate paper runner signal engine vs backtester
  run_paper.py                  start the paper-trading loop
  dashboard.py                  live terminal dashboard (4-tab Textual TUI)
  web_dashboard.py              Flask web dashboard at :8080 (auto-refreshing)

start.sh / stop.sh              start/stop the full stack
logs/                           CSV candle data and JSONL event logs (gitignored)
tests/                          87 tests: risk, indicators/signals, strategy
```

---

## Safety

- `TRD_ENV=SIMULATE` — all orders target Moomoo's paper account, never live
- `LIVE_TRADING_ENABLED=false` is checked in code before every order attempt
- `STOP_TRADING.txt` in project root pauses the loop without killing the process
- `live_trade_runner.py.DISABLED` is intentionally never executed
- No secrets in code — all config via `.env` (gitignored)

---

## Tests

```bash
python -m pytest tests/ -q    # 87 tests
```

Covers: position sizing safety, daily limit guards, kill switch behavior, indicator formulas, signal scoring, KDJ cross detection, strategy entry/exit state machine, integration against real CSV data.

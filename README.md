# moomoo-trader

Python research and paper-trading platform built on the [Moomoo API](https://openapi.moomoo.com/moomoo-api-doc/). Implements a BB + KDJ mean-reversion strategy with a signal confluence engine, backtesting framework, walk-forward validation, and a live paper-trading loop.

> **No live orders are placed.** All trading uses Moomoo's simulated/paper environment (`TRD_ENV=SIMULATE`).

---

## Requirements

- Moomoo desktop app installed with OpenD running (`127.0.0.1:11111` by default)
- Python 3.12+

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Setup

```bash
cp .env.example .env
# Edit .env — at minimum set MAX_POSITION_DOLLARS to at least one share's price
```

Key config variables:

| Variable | Default | Description |
|---|---|---|
| `TRD_ENV` | `SIMULATE` | Never change — all orders are paper |
| `LIVE_TRADING_ENABLED` | `false` | Hard kill switch checked before every order |
| `SYMBOLS` | `US.SPY` | Comma-separated symbols for paper runner |
| `CANDLE_KTYPE` | `K_5M` | Candle interval |
| `MAX_POSITION_DOLLARS` | `50` | Max notional per trade — raise to at least one share's price |
| `MAX_TRADES_PER_DAY` | `3` | Daily trade count limit |
| `MAX_DAILY_LOSS` | `5` | Daily loss limit in dollars |
| `ATR_STOP_MULT` | `1.0` | Stop = entry − N × ATR(14) |
| `MIN_SIGNAL_SCORE` | `2` | Bonus confirmation signals required (0–3) |
| `EXIT_ON_KDJ_DEATH` | `false` | Re-enable KDJ death cross exit (research: hurts results) |
| `DISCORD_WEBHOOK_URL` | _(empty)_ | Optional trade alerts |

---

## Strategy

**BB + KDJ mean reversion on 5-min closed candles.**

| | Condition |
|---|---|
| **Entry** | `close ≤ BB lower(20,2)` **AND** KDJ(9,3) golden cross **AND** bonus score ≥ `MIN_SIGNAL_SCORE` |
| **Exit — target** | `close ≥ BB middle` |
| **Exit — stop** | `close < entry_price − ATR_STOP_MULT × ATR(14)` |

### Signal confluence engine

The core entry (BB touch + KDJ golden cross) is always required. Three independent bonus signals add confirmation:

| Signal | Condition | Fire rate |
|---|---|---|
| `rsi_oversold` | RSI(14) < 35 | 97% of valid entries |
| `volume_spike` | volume > 1.5× 20-bar MA | 88% of valid entries |
| `ranging` | ADX(14) < 25 | 33% of valid entries |

`MIN_SIGNAL_SCORE=2` requires 2 of 3 bonus signals to also fire. This is the validated default.

---

## Research findings

Results on 199k 5-min candles, SPY + QQQ + IWM, 2022–2025. Sample sizes are small (60–77 trades over 3.5 years) — treat as directional, not definitive. All findings below survive until forward paper testing shows otherwise.

### Signal confluence (60 trades at MIN_SIGNAL_SCORE=2)

| Score threshold | Trades | Win% | Total PnL | Profit factor | Exit split |
|---|---|---|---|---|---|
| 0 — BB+KDJ only | 77 | 48.1% | +$15.49 | 1.474 | 52% stop / 48% target |
| 1 — need 1 bonus | 74 | 50.0% | +$17.56 | 1.573 | 50% / 50% |
| **2 — need 2 bonus *(default)*** | **60** | **51.7%** | **+$19.12** | **1.843** | **48% stop / 52% target** |
| 3 — all 3 bonus | 11 | — | — | — | too few trades |

Score=2 flips exit split to target-dominant, indicating better signal quality.

### Multi-symbol validation

| Symbol | Trades (score≥2) | Win% | Total PnL |
|---|---|---|---|
| SPY | 22 | 50.0% | +$7.81 |
| QQQ | 17 | 41.2% | +$2.98 |
| **IWM** | **21** | **61.9%** | **+$8.33** |
| **Combined** | **60** | **51.7%** | **+$19.12** |

IWM outperforms significantly: 38% stop rate (vs 50–58% for SPY/QQQ) and faster mean-reversion (132 min avg hold vs 309/507 min).

### ATR stop multiplier sweep (77 trades, SPY+QQQ+IWM, 90-day walk-forward windows)

| ATR mult | Win% | Total PnL | Profit factor | Consistency |
|---|---|---|---|---|
| 0.5 | 29.9% | −$1.19 | 0.962 | 15/39 = 38% |
| 0.75 | 39.0% | +$4.94 | 1.147 | 17/39 = 44% |
| **1.0 *(default)*** | **48.1%** | **+$15.49** | **1.474** | **22/39 = 56%** |
| 1.25 | 50.6% | +$13.16 | 1.349 | 23/39 = 59% |
| 1.5 | 54.5% | +$11.60 | 1.287 | 21/39 = 54% |
| 2.0 | 54.5% | +$5.10 | 1.109 | 19/39 = 49% |

ATR=1.0 has the best profit factor with near-best consistency.

### KDJ death cross exit

Disabling it flips SPY PnL from −$0.83 → +$2.34. The death cross was cutting winning mean-reversion trades before they reached the BB middle. Disabled by default.

### Timeframe comparison

| Timeframe | Trades | Win% | Total PnL | Stop rate |
|---|---|---|---|---|
| **K_5M *(default)*** | **77** | **48.1%** | **+$15.49** | **52%** |
| K_15M | 27 | 40.7% | +$5.61 | 59% |
| K_60M | 5 | 80.0% | +$16.76 | 20% |

K_5M is best. K_15M produces more stop-outs, not fewer. K_60M has too few signals to be actionable.

### Regime filter sweep (ADX vs BB width alternatives)

7 regime filter variants tested via `scripts/sweep_signals.py`. ADX ranging (ADX < 25) confirmed optimal for combined portfolio: +$19.12 PnL, PF=1.843. BB contracted/expanding filters do not improve results — entries occur during band expansion, not contraction.

---

## Usage

All scripts run from the project root with the venv active.

### Health check
```bash
python scripts/health_check.py
```

### Fetch historical candles
```bash
python scripts/fetch_candles.py --start 2022-01-01 --end 2025-05-30
python scripts/fetch_candles.py --symbol US.IWM --ktype K_5M
```

### Backtest
```bash
python scripts/run_backtest.py --latest
python scripts/walk_forward.py --latest --window 90
```

### Research and parameter sweeps
```bash
python scripts/research.py --latest --exits --walk-forward
python scripts/sweep.py --latest --entry strict --window 90
python scripts/multi_backtest.py --sweep                       # all K_5M CSVs in logs/
python scripts/sweep_signals.py --latest                       # regime filter comparison
```

### Paper trading
```bash
python scripts/run_paper.py                                    # uses SYMBOLS from .env
python scripts/run_paper.py --symbol US.IWM
python scripts/run_paper.py --symbols US.SPY,US.QQQ,US.IWM
```

### Dashboard

Live terminal UI — run alongside the paper runner:
```bash
python scripts/dashboard.py              # today's session
python scripts/dashboard.py --date 2026-06-02   # review a past session
```

Four tabs: **Overview** (positions + daily stats + config), **Trades** (P&L per trade), **Signals** (entries, blocks, skips), **Log** (raw JSONL event stream). Auto-refreshes every 5 seconds. Press `r` to refresh manually, `q` to quit. Reads `logs/paper_*.jsonl` — no OpenD connection needed.

- Polls OpenD every 60 seconds on **closed candles only**
- Position size: `floor(MAX_POSITION_DOLLARS / price)` — returns 0 and blocks if price exceeds cap
- Resets daily limits at midnight
- Kill switch: create `STOP_TRADING.txt` in project root to pause without stopping the process
- Position persists to disk — restarts safely recover open positions
- All events logged to `logs/paper_{symbol}_{date}.jsonl`

### Validate paper runner vs backtester

Run a simulation on historical data (no market hours needed):
```bash
python scripts/simulate_paper.py logs/US_IWM_K_5M_2026-05-31.csv \
    --start 2024-01-01 --end 2025-05-30 --compare
```

Or compare a live paper session against the backtester:
```bash
python scripts/compare_paper_vs_backtest.py logs/paper_US_IWM_2026-06-02.jsonl
```

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
  signals.py          signal scoring engine (5 signals, core gate + bonus)
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

logs/                           CSV candle data and JSONL event logs (gitignored)
tests/                          87 tests: risk, indicators/signals, strategy
```

---

## Safety

- `TRD_ENV=SIMULATE` — all orders target Moomoo's paper account, never live
- `LIVE_TRADING_ENABLED=false` is checked in code before every order
- `STOP_TRADING.txt` in project root pauses the loop without killing the process
- `live_trade_runner.py.DISABLED` is intentionally never executed
- No secrets in code — all config via `.env` (gitignored)

---

## Tests

```bash
python -m pytest tests/ -q    # 87 tests
```

Covers: position sizing safety, daily limit guards, kill switch, indicator formulas, signal scoring, KDJ cross detection, strategy entry/exit state machine, integration against real CSV data.

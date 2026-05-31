# moomoo-research

Python project for AI-assisted stock strategy research and paper trading via the [Moomoo API](https://openapi.moomoo.com/moomoo-api-doc/).

> **No live orders are placed.** All trading uses Moomoo's simulated/paper environment.

---

## Requirements

- Moomoo desktop app running with OpenD active (`127.0.0.1:11111` by default)
- Python 3.12+

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Configuration

```bash
cp .env.example .env
```

Key variables:

| Variable | Default | Description |
|---|---|---|
| `MOOMOO_HOST` | `127.0.0.1` | OpenD host |
| `MOOMOO_PORT` | `11111` | OpenD port |
| `TRD_ENV` | `SIMULATE` | Always use `SIMULATE` |
| `LIVE_TRADING_ENABLED` | `false` | Hard kill switch |
| `SYMBOL` | `US.SPY` | Default symbol |
| `CANDLE_KTYPE` | `K_5M` | Candle interval |
| `MAX_POSITION_DOLLARS` | `50` | Max notional per trade |
| `MAX_TRADES_PER_DAY` | `3` | Daily trade count limit |
| `MAX_DAILY_LOSS` | `5` | Daily loss limit in dollars |
| `EXIT_ON_KDJ_DEATH` | `false` | Re-enable KDJ death cross exit (see research note) |
| `DISCORD_WEBHOOK_URL` | _(empty)_ | Optional trade alerts |

---

## Usage

All scripts assume the venv is active (`source .venv/bin/activate`).

### 1. Health check

```bash
python scripts/health_check.py
```

### 2. Fetch historical candles

```bash
python scripts/fetch_candles.py                                         # last 30 days, US.SPY
python scripts/fetch_candles.py --start 2022-01-01 --end 2025-05-30    # full history
python scripts/fetch_candles.py --symbol US.QQQ --ktype K_15M
```

### 3. Backtest

```bash
python scripts/run_backtest.py --latest
python scripts/run_backtest.py logs/US_SPY_K_5M_2026-05-30.csv
```

### 4. Walk-forward backtest

Sequential non-overlapping windows — avoids look-ahead bias:

```bash
python scripts/walk_forward.py --latest
python scripts/walk_forward.py --latest --window 60
```

### 5. Strategy research

Compare entry and exit variants side-by-side:

```bash
python scripts/research.py --latest                      # entry variants only
python scripts/research.py --latest --exits              # + exit variants
python scripts/research.py --latest --walk-forward       # + walk-forward per entry variant
```

### 6. Parameter sweep

Grid search over ATR stop multiplier and entry tolerance, stop-loss recovery analysis, and walk-forward consistency scoring:

```bash
python scripts/sweep.py --latest                    # strict entry, 90-day windows
python scripts/sweep.py --latest --entry relaxed    # more signals, same sweep
python scripts/sweep.py --latest --window 60
```

### 7. Multi-symbol backtest

Compare strategy results across multiple symbols and run a combined ATR sweep:

```bash
python scripts/multi_backtest.py                    # all K_5M CSVs in logs/
python scripts/multi_backtest.py --sweep            # + per-symbol ATR consistency sweep
python scripts/multi_backtest.py --ktype K_15M      # filter by candle interval
```

### 8. Paper-trading loop

```bash
python scripts/run_paper.py
python scripts/run_paper.py --symbol US.QQQ
```

- Polls OpenD every 60 seconds on closed candles only
- Position size: `floor(MAX_POSITION_DOLLARS / price)`, minimum 1 share
- Respects `MAX_TRADES_PER_DAY` and `MAX_DAILY_LOSS` — resets at midnight
- Ctrl-C to stop cleanly
- Create `STOP_TRADING.txt` in the project root to pause without stopping the process

---

## Strategy — BB + KDJ mean reversion on 5-min candles

| | Condition |
|---|---|
| **Entry** | `close ≤ BB lower(20,2)` **AND** KDJ golden cross (K crosses above D) |
| **Exit — target** | `close ≥ BB middle` |
| **Exit — stop** | `close < entry_price − 1 × ATR(14)` |

All signals use **closed candles only**.

### Research findings (2022–2025, 199k 5-min candles, SPY + QQQ + IWM)

**Exit variants (SPY only):**

The original strategy included a KDJ death cross exit that cuts mean-reversion trades before they recover:

| Exit rule | Trades | Win% | Total PnL |
|---|---|---|---|
| BB middle + KDJ death + stop *(original)* | 29 | 27.6% | −$0.83 |
| **BB middle + stop *(current default)*** | **29** | **41.4%** | **+$2.34** |
| BB middle only | 28 | 67.9% | +$6.49 |

KDJ death cross exit is disabled by default (`EXIT_ON_KDJ_DEATH=false`).

**Multi-symbol validation:**

| Symbol | Trades | Win% | Total PnL |
|---|---|---|---|
| SPY | 29 | 41.4% | +$2.34 |
| QQQ | 21 | 42.9% | +$4.21 |
| **IWM** | **27** | **59.3%** | **+$8.95** |
| **Combined** | **77** | **48.1%** | **+$15.49** |

The strategy edge is consistent across all three symbols. IWM outperforms significantly.

**ATR stop multiplier sweep (77 trades, SPY+QQQ+IWM combined, 90-day windows):**

| ATR mult | Win% | Total PnL | Profit factor | Consistency |
|---|---|---|---|---|
| 0.5 | 29.9% | −$1.19 | 0.962 | 15/39 = 38% |
| 0.75 | 39.0% | +$4.94 | 1.147 | 17/39 = 44% |
| **1.0 *(default)*** | **48.1%** | **+$15.49** | **1.474** | **22/39 = 56%** |
| 1.25 | 50.6% | +$13.16 | 1.349 | 23/39 = 59% |
| 1.5 | 54.5% | +$11.60 | 1.287 | 21/39 = 54% |
| 2.0 | 54.5% | +$5.10 | 1.109 | 19/39 = 49% |
| 2.5 | 62.3% | +$18.03 | 1.428 | 22/39 = 56% |

1.0 ATR has the best profit factor (1.474) with near-best consistency. Confirmed across 77 trades — not a small-sample artifact.

**Stop recovery analysis (SPY):** 8/17 stop-loss exits recovered to the BB middle within 48 bars — 47% were "premature." The 9 genuine saves included a trade that fell $8.25 below the BB middle.

Configure with `ATR_STOP_MULT=1.0` in `.env`.

---

## Project layout

```
mm/
  config.py         # .env loading, typed config
  logger.py         # file + console logging
  connection.py     # OpenQuoteContext context manager
  health.py         # socket + quote health checks
  data.py           # historical candle fetcher with pagination
  indicators.py     # BB(20,2), ATR(14), KDJ(9,3)
  strategy.py       # entry/exit signal generation
  backtest.py       # backtester + walk-forward
  research.py       # entry/exit variant comparison
  sweep.py          # ATR + entry tolerance parameter sweep
  risk.py           # kill switch, daily limits, position sizing
  paper.py          # live paper-trading loop
  notifications.py  # optional Discord webhook alerts

scripts/
  health_check.py     # confirm OpenD is reachable
  fetch_candles.py    # fetch and save candles
  run_backtest.py     # backtest over a saved CSV
  walk_forward.py     # walk-forward backtest
  research.py         # compare strategy variants
  sweep.py            # ATR + entry tolerance grid search
  multi_backtest.py   # compare results across multiple symbols
  run_paper.py        # start paper-trading loop

logs/               # CSV candle data and log files (gitignored)
```

---

## Safety

- `TRD_ENV=SIMULATE` — all orders go to Moomoo's paper account
- `LIVE_TRADING_ENABLED=false` is checked before every order
- `STOP_TRADING.txt` in project root pauses the loop without killing the process
- `live_trade_runner.py.DISABLED` is intentionally never executed

---

## Roadmap

- [x] OpenD health check + quote connection test
- [x] Historical candle fetch with pagination
- [x] BB(20,2), ATR(14), KDJ(9,3) indicators
- [x] Strategy signal generation
- [x] Backtester with trade log and summary
- [x] Walk-forward backtest
- [x] Entry + exit variant research
- [x] ATR stop multiplier sweep with walk-forward consistency scoring
- [x] Stop-loss recovery analysis
- [x] Paper-trading loop (SIMULATE orders via OpenSecTradeContext)
- [x] Position sizing, daily trade and loss limits, kill switch
- [x] Discord webhook notifications
- [x] Multi-symbol backtest (SPY + QQQ + IWM validated, 77 trades)

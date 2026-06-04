# System Architecture

## Data Flow

```
OpenD (127.0.0.1:11111)
    │
    ▼
mm/connection.py  ──  quote_context() context manager
    │
    ▼
mm/data.py  ──  fetch_candles() → DataFrame (time_key, open, high, low, close, volume)
    │
    ▼
mm/indicators.py  ──  add_all() adds: bb_upper/middle/lower, atr, kdj_k/d/j,
    │                  rsi, adx, vwap, ema5/ema20, bb_width_pct
    │
    ├──► mm/strategy.py   ──  compute_signals() → bb_touch, kdj_cross, bonus signals
    │                          score_df(), run_signals()
    │
    ├──► mm/orb_strategy.py  ──  _build_opening_ranges() → or_high, or_low per symbol
    │
    └──► mm/vwap_pullback.py ──  VWAP flush-and-reclaim logic
    │
    ▼
mm/paper.py  ──  run_multi() main loop (60s poll)
    │             _eval_bb_kdj(), _eval_orb(), _eval_vwap_pb(), _eval_vwap()
    │             PaperEventLog → logs/paper_SYMBOL_YYYY-MM-DD.jsonl
    │             PaperPosition → logs/paper_SYMBOL_STRATEGY_position.json  (restart recovery)
    │
    ├──► mm/risk.py  ──  trading_allowed(), calc_qty(), calc_qty_fractional(),
    │                     DailyTracker (trade count + daily loss limit)
    │
    └──► mm/notifications.py  ──  Discord webhook (no-ops if URL unset)
    │
    ▼
logs/*.jsonl  ──  structured events: bar_eval, signal_skip, risk_block,
                   order_attempt, order_result, position_open, position_close
    │
    ├──► scripts/web_dashboard.py   ──  Flask, port 8080, auto-refresh 30s
    ├──► scripts/dashboard.py       ──  Textual TUI
    ├──► scripts/diagnose_logs.py   ──  uptime gaps, signal rates, trade pairs, skip reasons
    └──► scripts/compare_paper_vs_backtest.py  ──  BB+KDJ signal engine agreement check
```

## Active Strategies (VPS, as of 2026-06-04)

| Strategy   | Entry condition                          | Exit                         | Symbols        |
|------------|------------------------------------------|------------------------------|----------------|
| bb_kdj     | close ≤ BB lower + KDJ cross + bonus≥2  | BB middle target / ATR stop  | SPY, QQQ, IWM  |
| orb        | close breaks OR high/low + volume        | fixed target / ATR stop      | SPY, QQQ, IWM  |
| vwap_pb    | wick below VWAP, closes above, ≤1 cross  | VWAP lost / ATR stop         | SPY, QQQ only  |

## Key Config Vars (`.env`)

```
STRATEGIES=bb_kdj,orb,vwap_pb
SYMBOLS=US.IWM,US.SPY,US.QQQ
KDJ_WINDOW_BARS=3          # look back N bars for KDJ cross vs BB touch
MIN_SIGNAL_SCORE=2         # bonus signals required (rsi_oversold, ranging, volume_spike)
ATR_STOP_MULT=1.0
ORB_MINUTES=15             # opening range window; IWM overridden to 30
ORB_MINUTES_OVERRIDES=US.IWM:30
ORB_SHORTS_ENABLED=true    # kill switch: create STOP_SHORTS.txt to disable at runtime
VWAP_PB_SYMBOLS=US.SPY,US.QQQ
TOTAL_CAPITAL=100          # total bankroll; divided across symbol×strategy slots
FRACTIONAL_SHARES=true
MAX_POSITION_DOLLARS=900   # fallback if TOTAL_CAPITAL not set
TRD_ENV=SIMULATE           # NEVER change to REAL
LIVE_TRADING_ENABLED=false # NEVER change to true
```

## Kill Switches (runtime, no restart needed)

| File                   | Effect                                    |
|------------------------|-------------------------------------------|
| `STOP_TRADING.txt`     | Pauses all entries (exits still fire)     |
| `STOP_SHORTS.txt`      | Disables ORB short entries only           |

## Test & Verify Commands

```bash
python -m pytest tests/ -q                           # 115 unit tests
python scripts/diagnose_logs.py --date YYYY-MM-DD    # session health check
python scripts/compare_paper_vs_backtest.py logs/paper_US_SPY_YYYY-MM-DD.jsonl
./scripts/verify.sh                                  # all-in-one session verify
```

## Services (VPS)

```
moomoo-paper.service      # paper runner (Restart=always)
moomoo-dashboard.service  # web dashboard on :8080 (Restart=always)
```

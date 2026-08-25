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
    ├──► mm/strategy.py      ──  compute_signals() → bb_touch, kdj_cross, bonus signals
    │
    ├──► mm/orb_strategy.py  ──  _build_opening_ranges() → or_high, or_low per symbol
    │
    └──► mm/vwap_pullback.py ──  VWAP flush-and-reclaim logic
    │
    ▼
mm/paper.py  ──  run_multi() main loop (60s poll), _eval_symbol_all_strategies()
    │             _latest_closed_candles(), back-compat re-exports
    │
    ├──► mm/clock.py     ──  time seam: now(), now_et(), today(), sleep(), is_market_open()
    │                         single patch point for replay and tests
    │
    ├──► mm/evals.py     ──  _eval_bb_kdj(), _eval_bb_kdj_loose(), _eval_orb(),
    │                         _eval_vwap_pb(), _eval_vwap(), _eval_gap_fade()
    │                         _entry_attempted (dedup dict), _kdj_cross_age()
    │
    ├──► mm/events.py    ──  PaperEventLog → logs/paper_SYMBOL_YYYY-MM-DD.jsonl
    │                         PaperPosition → logs/paper_SYMBOL_STRATEGY_position.json
    │                         _load/_save/_clear_position, _load/_save_orb_traded,
    │                         _load/_save_gap_fade_traded
    │
    ├──► mm/execution.py ──  _place_buy/sell/short/cover, _confirm_fill
    │                         _execute_entry/_execute_exit, _reconcile_positions
    │                         trade_context(), _get_simulate_acc_id()
    │
    ├──► mm/risk.py      ──  trading_allowed(), calc_qty(), calc_qty_fractional(),
    │                         DailyTracker, _qty(), _position_cap(), _slot_dollars
    │
    ├──► mm/notifications.py  ──  Discord webhook (no-ops if URL unset)
    │
    └──► mm/replay.py     ──  replay(), FakeBroker — offline candle replay through real runner
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

## Active Strategies (VPS, config verified against live `.env` 2026-08-24)

| Strategy      | Entry condition                          | Exit                         | Symbols        |
|---------------|------------------------------------------|------------------------------|----------------|
| bb_kdj        | close ≤ BB lower + KDJ cross + bonus≥2  | BB middle target / ATR stop  | SPY, QQQ, IWM  |
| bb_kdj_loose  | close ≤ BB lower + KDJ cross (no bonus, no ADX filter) | BB middle / ATR stop | SPY, QQQ, IWM |
| orb           | close breaks OR high/low + volume        | per-symbol target / ATR stop | SPY, QQQ, IWM (shorts: SPY only) |
| vwap_pb       | wick below VWAP, closes above, ≤1 cross  | VWAP lost / ATR stop         | SPY, QQQ, IWM  |
| gap_fade      | 9:35 ET bar: gap>0.5% + rejection candle | 50% fill (TARGET) / STOP / 11:00 TIME_STOP | SPY, QQQ, IWM |

## Key Config Vars (`.env`)

```
STRATEGIES=bb_kdj,bb_kdj_loose,orb,vwap_pb,gap_fade
SYMBOLS=US.IWM,US.SPY,US.QQQ
KDJ_WINDOW_BARS=3               # look back N bars for KDJ cross vs BB touch
KDJ_WINDOW_OVERRIDES=US.SPY:0,US.IWM:0
MIN_SIGNAL_SCORE=2              # bonus signals required (rsi_oversold, ranging, volume_spike)
ATR_STOP_MULT=1.0
ORB_MINUTES=15                  # opening range window; IWM overridden to 30
ORB_MINUTES_OVERRIDES=US.IWM:30
ORB_TARGET_MULT=1.5             # target = mult × OR range height (global default)
ORB_TARGET_MULT_OVERRIDES=US.QQQ:2.0,US.IWM:1.0
ORB_VOL_MULT=1.5
ORB_VOL_MULT_OVERRIDES=US.SPY:2.0
ORB_SHORTS_ENABLED=true
ORB_SHORT_SYMBOLS=US.SPY        # QQQ+IWM disabled 2026-07-09 (0% win rate on 36 trades)
ORB_VIX_MAX=                    # global ORB VIX cap; empty = no filter
ORB_VIX_MAX_OVERRIDES=US.IWM:18  # IWM PF 1.045→1.113 OOS at vix_max=18
ORB_SETUP_SCORER_ENABLED=true   # Claude per-trade scorer — logs confidence but gate disabled (0.0)
ORB_ENTRY_MIN_CONFIDENCE=0.0    # disabled 2026-08-14: features don't discriminate outcomes
ORB_LATEST_ENTRY=12:30          # no new entries after 12:30 ET; activated 2026-08-14
GAP_VIX_MAX=                    # global gap_fade VIX cap; empty = no filter
GAP_VIX_MAX_OVERRIDES=US.SPY:20,US.QQQ:20  # VIX>=20 negative OOS for SPY+QQQ
GAP_MAX_SHORT_PCT=0.01          # gap-up short filter threshold (1%)
GAP_LARGE_SHORT_FILTER_ENABLED=true  # blocks gap-up shorts >1% — IS/OOS confirmed bad edge
VWAP_PB_SYMBOLS=US.SPY,US.QQQ,US.IWM
VWAP_PB_MAX_CROSSES=1           # no-chop filter; critical to the PB edge
VWAP_PB_STOP_MULT=1.0
VWAP_PB_MIN_ENTRY_TIME=10:00    # not set in VPS .env — code default in mm/config.py is 10:00
TOTAL_CAPITAL=0                 # 0 = disabled; sizing falls through to MAX_POSITION_DOLLARS
FRACTIONAL_SHARES=false         # → min 1 whole share, so 1 SPY ≈ $766 notional regardless of TOTAL_CAPITAL
MAX_POSITION_DOLLARS=900        # the ACTIVE sizing path, since TOTAL_CAPITAL=0
TRD_ENV=SIMULATE                # NEVER change to REAL
LIVE_TRADING_ENABLED=false      # NEVER change to true
ANTHROPIC_API_KEY=              # in .env only, never committed
ANTHROPIC_MODEL=claude-sonnet-5       # regime gate only — the one LLM call that blocks live trades
ANTHROPIC_MODEL_CHEAP=claude-haiku-4-5-20251001  # ORB scorer (shadow) + weekly synthesis — split 2026-08-25
REGIME_GATE_ENABLED=true        # blocks bb_kdj/loose on trending days; fail-open
REGIME_GATE_STRATEGIES=bb_kdj,bb_kdj_loose
REGIME_SKIP_LABELS=trending_up,trending_down  # flipped 2026-07-26 (choppy PF=0.928 is fine)
```

## Kill Switches (runtime, no restart needed)

| File                   | Effect                                    |
|------------------------|-------------------------------------------|
| `STOP_TRADING.txt`     | Pauses all entries (exits still fire)     |
| `STOP_SHORTS.txt`      | Disables ORB short entries only — currently NOT present (removed 2026-06-17) |

## Test & Verify Commands

```bash
python -m pytest tests/ -q                           # 255 unit tests, all passing
                                                     # (the 3 long-standing test_data.py failures were a real
                                                     #  bug, fixed 2026-08-24 — see graveyard "Stale cfg in mm/data.py")
python scripts/diagnose_logs.py --date YYYY-MM-DD    # session health check
python scripts/compare_paper_vs_backtest.py logs/paper_US_SPY_YYYY-MM-DD.jsonl
./scripts/verify.sh                                  # all-in-one session verify
```

## Services (VPS)

```
moomoo-paper.service      # paper runner (Restart=always)
moomoo-dashboard.service  # web dashboard on :8080 (Restart=always)
```

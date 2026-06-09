# moomoo-trader: Full Project Map

**AI Context Document** — paste this into any AI session to get full project context without re-deriving.
Last updated: 2026-06-04.

---

## What This Project Is

A Python paper-trading research platform built on the **Moomoo / Futu OpenD API**. It runs
three simultaneous intraday strategies on US ETFs (SPY, QQQ, IWM) in Moomoo's SIMULATE
environment. The goal is validated signal research + a production-quality execution engine
that can be promoted to live trading when ready.

**Stack:** Python 3.12, Moomoo OpenD API, pandas, Flask, Textual. VPS-hosted on Ubuntu (OVH).
**Safety:** `TRD_ENV=SIMULATE` and `LIVE_TRADING_ENABLED=false` are hardcoded checks. No real
money is at risk. `live_trade_runner.py.DISABLED` intentionally never runs.

---

## Repository Layout

```
moomoo-trader/
│
├── mm/                          # Core library (importable package)
│   ├── config.py                # .env loading via python-dotenv; cfg singleton (117 lines)
│   ├── logger.py                # TimedRotatingFileHandler, midnight rotation, 30-day retention
│   ├── connection.py            # quote_context() context manager → OpenD at 127.0.0.1:11111
│   ├── health.py                # run_health_check() — socket ping + quote fetch
│   ├── data.py                  # fetch_candles(), fetch_and_save() (99 lines)
│   ├── indicators.py            # add_all(): BB(20,2), ATR(14), KDJ(9,3), RSI(14),
│   │                            #   ADX(14), VWAP (session reset), EMA5/EMA20,
│   │                            #   volume_ma(20), bb_width_pct (rolling percentile)
│   ├── signals.py               # score_df(), snapshot() — BB+KDJ signal scoring
│   ├── strategy.py              # compute_signals(), run_signals(), Trade, Signal
│   │                            #   blocked_hours param available (not deployed)
│   ├── backtest.py              # run_backtest(), walk_forward(), print_summary()
│   ├── research.py              # compare_variants(), sweep_parameters(),
│   │                            #   analyze_stop_exits(), sweep_signal_filter() (599 lines)
│   ├── risk.py                  # trading_allowed(), calc_qty(), calc_qty_fractional(),
│   │                            #   per_slot_dollars(), DailyTracker (142 lines)
│   ├── paper.py                 # Multi-strategy paper loop — THE MAIN ENGINE (1056 lines)
│   │                            #   PaperEventLog, PaperPosition, run_multi()
│   │                            #   _eval_bb_kdj(), _eval_orb(), _eval_vwap_pb(), _eval_vwap()
│   │                            #   _latest_closed_candles(), _qty(), _position_cap()
│   ├── orb_strategy.py          # ORB backtest engine, _build_opening_ranges() (227 lines)
│   ├── vwap_pullback.py         # VWAP Pullback (flush-and-reclaim) backtest engine (172 lines)
│   ├── vwap_strategy.py         # VWAP crossover strategy — DEPRECATED, PF≈1.0 (174 lines)
│   ├── vwap_signals.py          # VWAP signal scoring (used by vwap crossover only)
│   ├── ema_momentum.py          # EMA5/EMA20 momentum breakout — RESEARCH ONLY, not deployed
│   └── notifications.py         # Discord webhook; no-ops if DISCORD_WEBHOOK_URL not set
│
├── scripts/                     # Runnable entry points (all run from project root)
│   ├── run_paper.py             # Single-symbol paper runner (wraps run_multi)
│   ├── web_dashboard.py         # Flask dashboard :8080 — auto-refresh 30s (541 lines)
│   │                            #   Cards: TODAY stats, OPEN POSITION, TRADES (w/ slippage),
│   │                            #   MARKET CONDITIONS (BB+KDJ/ORB/VWAP PB per symbol),
│   │                            #   SIGNAL FEED (last 20 bb_kdj bars)
│   ├── dashboard.py             # Textual TUI dashboard — same data, terminal UI (535 lines)
│   ├── eod_summary.py           # TradeRecord/SessionSummary, load_summary(), Discord post
│   ├── diagnose_logs.py         # Session health: uptime gaps, signal hit rates, staleness,
│   │                            #   trade pairs, why-no-entry counts (251 lines)
│   ├── compare_paper_vs_backtest.py  # BB+KDJ signal engine agreement: paper vs backtester
│   ├── verify.sh                # One-command: pytest + sync + diagnose + compare
│   ├── fetch_candles.py         # CLI candle fetcher with date range and ktype args
│   ├── health_check.py          # OpenD connection health check
│   ├── run_backtest.py          # BB+KDJ backtest on a CSV
│   ├── walk_forward.py          # Walk-forward validation (rolling train/test windows)
│   ├── research.py              # Multi-variant backtest sweep runner
│   ├── sweep.py                 # ATR/entry parameter sweep
│   ├── sweep_signals.py         # Regime filter sweep (ADX vs BB width variants)
│   ├── sweep_session_filter.py  # Intraday hour blackout sweep for BB+KDJ
│   ├── multi_backtest.py        # Batch backtest across multiple CSVs
│   ├── simulate_paper.py        # Replay backtest against paper runner logic
│   ├── backtest_orb.py          # ORB backtest runner
│   ├── backtest_vwap_pb.py      # VWAP Pullback backtest runner
│   ├── backtest_vwap.py         # VWAP crossover backtest (deprecated)
│   ├── backtest_ema_momentum.py # EMA momentum backtest (research only)
│   ├── backtest_vix_filter.py   # VIX regime filter backtest (graveyard'd — do not deploy)
│   └── sweep_vwap.py            # VWAP parameter sweep
│
├── tests/
│   ├── test_indicators.py       # 47 tests: BB, ATR, KDJ, RSI, ADX, VWAP, EMA, bb_width_pct
│   ├── test_strategy.py         # 18 tests: signal scoring, bonus signals, walk-forward
│   ├── test_risk.py             # 29 tests: calc_qty, DailyTracker, fractional sizing,
│   │                            #   per_slot_dollars, trading_allowed
│   └── test_orb_shorts.py       # 21 tests: ORB long/short entry, exit, PnL, restart recovery
│                                # Total: 115 tests
│
├── docs/
│   ├── PROJECT_MAP.md           # This file — full AI context document
│   ├── ARCHITECTURE.md          # 30-line data flow diagram + config reference
│   ├── HARDENING_PLAN.md        # NEW: Strategy for ATR-sizing and reliability
│   └── strategy_graveyard.md   # All tested/abandoned/parked features with research data
│
├── logs/                        # Runtime output (gitignored)
│   ├── paper_US_SPY_YYYY-MM-DD.jsonl   # Structured event log per symbol per day
│   ├── paper_US_QQQ_YYYY-MM-DD.jsonl
│   ├── paper_US_IWM_YYYY-MM-DD.jsonl
│   ├── paper_US_SPY_orb_position.json  # Open position state (restart recovery)
│   ├── US_SPY_K_5M_combined.csv        # 86,100 candles, 2022-01-03 to 2026-06-03
│   ├── US_QQQ_K_5M_combined.csv        # same date range
│   ├── US_IWM_K_5M_combined.csv        # same date range
│   └── paper.log / risk.log / ...      # Rotating text logs (30-day retention)
│
├── start.sh                     # Start OpenD + paper runner (systemd user service)
├── stop.sh                      # Stop paper runner
├── deploy.sh                    # Run tests → git pull on VPS → restart services
├── sync_logs.sh                 # rsync VPS logs/ → local logs/
├── .env                         # Runtime config (gitignored — see .env.example)
├── .env.example                 # All config vars with defaults and comments
├── CLAUDE.md                    # Claude Code session instructions + full findings index
├── requirements.txt             # pandas, moomoo-api, flask, textual, yfinance, etc.
└── live_trade_runner.py.DISABLED  # Intentionally disabled — never executed
```

---

## Deployed Strategies (VPS, 2026-06-04)

### 1. BB+KDJ Mean Reversion (`bb_kdj`)
**Timeframe:** 5-min candles. **Symbols:** SPY, QQQ, IWM.

**Entry:** All three must be true on the same closed bar:
- `close ≤ BB lower(20,2)` — price at lower Bollinger Band
- KDJ(9,3) golden cross within the last `KDJ_WINDOW_BARS=3` bars (K crosses above D)
- Bonus score ≥ `MIN_SIGNAL_SCORE=2` from: RSI<35 (fires 97% of trades), volume spike >1.5× MA (88%), ADX<25 ranging (33%)

**Exit:**
- Target: `close ≥ BB middle` — mean reversion complete
- Stop: `close < entry - 1.0 × ATR(14)` — confirmed optimal by sweep (PF=1.843, 56% walk-forward)
- KDJ death cross exit: DISABLED (`EXIT_ON_KDJ_DEATH=false`) — re-enabling flips PnL negative

**Backtest results (SPY+QQQ+IWM, 2022–2025, K_5M):**
- 60 trades (at MIN_SCORE=2), 51.7% win rate, +$19.12 total, PF=1.843
- Exit split: 48% stop / 52% target (target-dominant, better than stop-dominant)
- IWM outperforms: 61.9% win, 38% stop rate vs 50–58% for SPY/QQQ
- OOS (walk-forward): PF consistently > 1.0 across 22/39 windows

**Key research decisions locked:**
- `ATR_STOP_MULT=1.0` — optimal (not 1.5 or 2.0)
- `MIN_SIGNAL_SCORE=2` — optimal (score=3 has too few trades)
- `KDJ_WINDOW_BARS=3` — 10× more signals on IWM/QQQ vs 0; SPY excluded or kept at 0
- Regime filter: ADX<25 confirmed best vs 6 alternatives (BB width, volume variants)
- Timeframe: K_5M confirmed best — K_15M produces MORE stops, not fewer

---

### 2. Opening Range Breakout (`orb`)
**Timeframe:** 5-min candles. **Symbols:** SPY, QQQ, IWM.

**Opening range:**
- SPY, QQQ: first 15 minutes (9:30–9:45 ET) — `ORB_MINUTES=15`
- IWM: first 30 minutes (9:30–10:00 ET) — `ORB_MINUTES_OVERRIDES=US.IWM:30`
- Range must be 0.1%–0.8% of close price (filters tiny flat opens and news spikes)

**Entry (Long):** `close > OR high` + volume > 1.2× 20-bar MA + after OR window closes
**Entry (Short):** `close < OR low` + volume > 1.2× MA + `ORB_SHORTS_ENABLED=true`
- Short kill switch: create `STOP_SHORTS.txt` in project root (no restart needed)

**Exit:**
- Target: entry + 1.5 × OR range (`ORB_TARGET_MULT=1.5`)
- Stop (long): OR low. Stop (short): OR high.
- Time stop: 15:45 ET

**One trade per day enforced** — state persisted in `logs/paper_*_orb_traded.json` for restart recovery.

**Live trades (2026-06-04):**
- SPY: entry $755.37 → exit $758.29, +$2.92 (TARGET hit) ✓
- QQQ: entry $739.65 → exit $742.17, +$2.52 (TIME_STOP) ✓

---

### 3. VWAP Pullback (`vwap_pb`)
**Timeframe:** 5-min candles. **Symbols:** SPY, QQQ only (IWM excluded — negative OOS).

**Entry (flush-and-reclaim):** All four on same closed bar after 9:45 ET:
- `low < VWAP` (wick dipped below — the "flush")
- `close > VWAP` (closed above — the "reclaim")
- Session VWAP cross count ≤ 1 (`VWAP_PB_MAX_CROSSES=1`) — critical no-chop filter
- `volume < volume_ma` — quiet bar, not distribution selling

**Exit:**
- `close < VWAP` — level lost
- `close < entry - 1.0 × ATR` — ATR stop
- 15:45 ET time stop

**Backtest OOS (train 2022–23, test 2024–25):**
- SPY PF=1.655, QQQ PF=1.072
- IWM: negative OOS — excluded via `VWAP_PB_SYMBOLS=US.SPY,US.QQQ`

---

## Risk Management (`mm/risk.py`)

### Position Sizing
**Mode 1 — Fractional (current VPS config):**
```
TOTAL_CAPITAL=100
FRACTIONAL_SHARES=true
per_slot = 100 / (3 symbols × 3 strategies) = $11.11/position
qty = round(slot_dollars / price, 6)  → e.g. $11.11 / $755 = 0.014715 shares
```
Moomoo paper accepts float qty natively. Dollar P&L scales proportionally; percentage edge unchanged.

**Mode 2 — Whole share (fallback):**
```
MAX_POSITION_DOLLARS=900  (or SYMBOL_SIZE_OVERRIDES=US.IWM:300,...)
qty = floor(cap / price)
```

### Daily Guards (`DailyTracker` in `mm/risk.py`)
- `MAX_TRADES_PER_DAY=3` — global cap across ALL strategies combined
- `MAX_TRADES_PER_STRATEGY=0` — per-strategy cap (0 = disabled). Set to 1 to prevent ORB consuming all 3 global slots and starving BB+KDJ/VWAP PB.
- `MAX_DAILY_LOSS=5` — daily P&L floor; trips if cumulative loss ≥ $5. Both limits checked on every `can_open(strategy=...)` call.

### Startup Safety (`mm/config.py` → `mm/paper.py`)
- `validate_config()` runs before the main loop — fails fast on bad `.env` (wrong TRD_ENV, unknown strategies, invalid numerics). CRITICAL errors abort; warnings log and continue.
- `_reconcile_positions()` runs on startup if any local position files exist — queries broker via `position_list_query()` and clears stale local state if broker disagrees.

### Kill Switches (runtime, no restart)
| File | Effect |
|------|--------|
| `STOP_TRADING.txt` | Pauses all entries; exits still fire |
| `STOP_SHORTS.txt` | ORB short entries only |

---

## Structured Event Log (JSONL)

Every poll cycle appends structured JSON to `logs/paper_US_SYMBOL_YYYY-MM-DD.jsonl`.

### Event Types
```jsonc
// Bar evaluation — emitted every poll, every strategy
{"ts":"2026-06-04T15:10:00","event":"bar_eval","strategy":"bb_kdj","symbol":"US.SPY",
 "candle_ts":"2026-06-04 15:05:00","candle_age_s":60,"close":754.24,"signal_score":2,
 "bonus_score":2,"regime_label":"ranging",
 "signals":{"bb_touch":false,"kdj_cross":false,"rsi_oversold":false,
            "ranging":true,"volume_spike":true,"bb_lower":754.36,"bb_middle":755.25}}

// Signal skipped (entry criteria partially met but not fully)
{"event":"signal_skip","strategy":"orb","reason":"orb_vol_fail","score":0,"min_score":0}
// reason codes: bonus_below_threshold, orb_vol_fail, orb_before_cutoff,
//               orb_shorts_disabled, orb_shorts_kill_switch

// Risk block (signal met but risk gate blocked it)
{"event":"risk_block","strategy":"bb_kdj","reason":"price_exceeds_max_position",
 "price":754.24,"max_dollars":11.11}
// reason codes: price_exceeds_max_position, daily_limit_reached

// Order placement
{"event":"order_attempt","strategy":"orb","side":"BUY","symbol":"US.SPY","qty":1,"price":755.37}
{"event":"order_result","strategy":"orb","side":"BUY","success":true,"order_id":"661944"}

// Trade lifecycle
{"event":"position_open","strategy":"orb","symbol":"US.SPY","entry":755.37,"stop":751.47,
 "qty":1,"direction":"long","slippage_bps":0.0,"vix_at_entry":null}
{"event":"position_close","strategy":"orb","symbol":"US.SPY","exit":758.29,"reason":"TARGET",
 "pnl":2.92,"hold_bars":8,"direction":"long","slippage_bps":0.0}
```

### Position State (restart recovery)
Open positions survive process restarts via JSON files:
`logs/paper_US_SPY_orb_position.json` — stores entry_price, stop_price, qty, direction, target_price, order_id. Direction field critical for ORB shorts (wrong direction = inverted stop/target logic).

---

## Observability & Tooling

### `scripts/verify.sh` — One-command session check
```bash
./scripts/verify.sh                    # today
./scripts/verify.sh --date 2026-06-04  # past session
./scripts/verify.sh --no-sync          # skip VPS sync
```
Runs: pytest (115 tests) → rsync logs → diagnose_logs → compare_paper_vs_backtest (all 3 symbols).

### `scripts/diagnose_logs.py` — Session health
```bash
python scripts/diagnose_logs.py --date 2026-06-04
```
Five sections:
1. **Uptime gaps** — bar_eval gaps > 10 min (runner was down)
2. **Signal hit rates** — bb_touch%, kdj_cross%, bonus distribution per symbol
3. **Candle staleness** — candle_age_s > 600 during market hours (data lag)
4. **Trade pairs** — entry/exit/pnl/hold_bars/direction per trade
5. **Why no entry** — signal_skip and risk_block counts by strategy+reason

### `scripts/compare_paper_vs_backtest.py` — Signal engine agreement
Validates BB+KDJ paper runner and offline backtester produce identical signals on the same candles.
Uses filename date as range start to avoid stale-candle contamination of the comparison window.
June 4 result: ✓ All 3 symbols agree (0 BB+KDJ signals that session — confirmed by both engines).

### Web Dashboard (`scripts/web_dashboard.py`) — Flask, port 8080
Auto-refreshes every 30s. Cards:
- **TODAY** — P&L, trade count, wins/losses, targets/stops, bars evaluated
- **OPEN POSITION** — live unrealized P&L
- **TRADES** — entry/exit/P&L/reason/hold time/**slippage_bps** column + strategy badge
- **MARKET CONDITIONS** — per-symbol per-strategy: entry readiness status
  - BB+KDJ: signal dots + "BB X% away" / "need KDJ" / "READY ▲"
  - ORB: OR high/low + "LONG READY ▲" / "SHORT READY ▼" / distance to breakout
  - VWAP PB: cross count + above/wick flags + "choppy (N crosses > 1)" / "READY ▲"
  - Recent skips: last 12 signal_skip events with reason
- **SIGNAL FEED** — last 20 bb_kdj bar_eval events with signal dots

### TUI Dashboard (`scripts/dashboard.py`) — Textual
```bash
python scripts/dashboard.py                    # live
python scripts/dashboard.py --date 2026-06-04  # replay past session
```

---

## VPS Deployment

**Server:** Ubuntu VPS (OVH), UTC timezone.
**OpenD:** Moomoo's broker gateway. Installed as AppImage, managed via systemd user service.
**Python env:** System Python 3 + project venv at `~/moomoo/.venv`.

### Services
```
moomoo-paper.service      # paper runner — Restart=always
moomoo-dashboard.service  # web dashboard on :8080 — Restart=always
```

### Active `.env` (VPS)
```env
TRD_ENV=SIMULATE
LIVE_TRADING_ENABLED=false
STRATEGIES=bb_kdj,orb,vwap_pb
SYMBOLS=US.IWM,US.SPY,US.QQQ
KDJ_WINDOW_BARS=3
MIN_SIGNAL_SCORE=2
ATR_STOP_MULT=1.0
ORB_MINUTES=15
ORB_MINUTES_OVERRIDES=US.IWM:30
ORB_TARGET_MULT=1.5
ORB_SHORTS_ENABLED=true
VWAP_PB_SYMBOLS=US.SPY,US.QQQ
VWAP_PB_MAX_CROSSES=1
TOTAL_CAPITAL=100
FRACTIONAL_SHARES=true
MAX_TRADES_PER_DAY=3
MAX_DAILY_LOSS=5
```

### Deployment Workflow
```bash
# Local → VPS
./deploy.sh           # runs pytest locally, git pull on VPS, restarts services

# VPS → Local logs
./sync_logs.sh        # rsync VPS logs/ → local logs/

# Full verify after sync
./scripts/verify.sh
```

---

## Historical Data

Stored in `logs/` (gitignored). Combined CSV = deduped merge of 2022–2025 data + fresh fetch.

| File | Candles | Date Range |
|------|---------|------------|
| `US_SPY_K_5M_combined.csv` | 86,100 | 2022-01-03 → 2026-06-03 |
| `US_QQQ_K_5M_combined.csv` | 86,100 | 2022-01-03 → 2026-06-03 |
| `US_IWM_K_5M_combined.csv` | 86,100 | 2022-01-03 → 2026-06-03 |
| `US_*_K_15M_*.csv` | 22,158 | 2022-01-03 → 2025-05-30 |
| `US_*_K_60M_*.csv` | 5,967 | 2022-01-03 → 2025-05-30 |

---

## Test Suite (115 tests)

```bash
python -m pytest tests/ -q              # all 115
python -m pytest tests/test_risk.py    # risk + sizing (29)
python -m pytest tests/test_orb_shorts.py  # ORB shorts (21)
```

Coverage by area:
- **Indicators** (47): BB, ATR, KDJ, RSI, ADX, VWAP, EMA, bb_width_pct edge cases
- **Strategy/Signals** (18): BB+KDJ scoring, bonus signals, walk-forward
- **Risk** (29): calc_qty, DailyTracker, fractional sizing, per_slot_dollars
- **ORB Shorts** (21): long/short entry, stop/target direction, PnL sign, restart recovery

---

## What's Parked / Backlog

See `docs/strategy_graveyard.md` for full details with research data and graveyard'd features.

| Item | Status | Gate |
|------|--------|------|
| ATR-normalized sizing (`risk_dollars / (atr × mult)`) | On hold | 2+ weeks live slippage data |
| IWM-weighted sizing | On hold | Superseded by ATR sizing — do that first |
| Session filter (BLOCKED_HOURS) | Swept, no universal benefit | Data is definitive |
| VIX daily regime filter | Graveyard'd | IWM OOS 0.800 vs 1.033 baseline — destroyed edge |
| Push architecture (WebSocket exits) | Deferred | slippage_bps shows 60s poll costs real edge |
| ORB short live verification | Waiting | First short order in JSONL needed |
| paper.py refactor (split 1,100-line file) | On hold | Large project, no functional gain yet |

---

## Key Invariants (Never Violate)

1. `TRD_ENV=SIMULATE` always
2. `LIVE_TRADING_ENABLED=false` always — code checks this before every order
3. Only evaluate **closed** candles — `_latest_closed_candles()` drops the last (forming) bar and checks age of the resulting last closed bar (≤15 min old)
4. `STOP_TRADING.txt` / `STOP_SHORTS.txt` — runtime kill switches, no restart needed
5. `live_trade_runner.py.DISABLED` — never executed
6. No secrets in code — all credentials in `.env` (gitignored)

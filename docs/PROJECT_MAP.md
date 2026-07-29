# moomoo-trader: Full Project Map

**AI Context Document** — paste this into any AI session to get full project context without re-deriving.
Last updated: 2026-07-29.

---

## What This Project Is

A Python paper-trading research platform built on the **Moomoo / Futu OpenD API**. It runs
five simultaneous intraday strategies on US ETFs (SPY, QQQ, IWM) in Moomoo's SIMULATE
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
│   ├── logger.py                # TimedRotatingFileHandler, midnight rotation, kept forever (backupCount=0)
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
│   ├── clock.py                 # Time seam: now(), now_et(), today(), sleep(),
│   │                            #   is_market_open(), seconds_until_open() — single patch point
│   ├── events.py                # PaperEventLog, PaperPosition, position/ORB file I/O
│   │                            #   _load/_save/_clear_position, _load/_save_orb_traded,
│   │                            #   _load/_save_gap_fade_traded
│   ├── execution.py             # _place_buy/sell/short/cover, _confirm_fill,
│   │                            #   _execute_entry/_execute_exit, _reconcile_positions,
│   │                            #   trade_context(), _get_simulate_acc_id()
│   ├── evals.py                 # _eval_bb_kdj(), _eval_bb_kdj_loose(), _eval_vwap(),
│   │                            #   _eval_vwap_pb(), _eval_orb(), _eval_gap_fade()
│   │                            #   _entry_attempted (dedup dict), _kdj_cross_age()
│   ├── risk.py                  # trading_allowed(), calc_qty(), calc_qty_fractional(),
│   │                            #   per_slot_dollars(), DailyTracker, _qty(), _position_cap(),
│   │                            #   _slot_dollars
│   ├── paper.py                 # Loop + candle fetch + back-compat re-exports (~340 lines)
│   │                            #   run_multi(), _eval_symbol_all_strategies(),
│   │                            #   _latest_closed_candles(), _trigger_eod_summary()
│   ├── orb_strategy.py          # ORB backtest engine, _build_opening_ranges() (227 lines)
│   ├── vwap_pullback.py         # VWAP Pullback (flush-and-reclaim) backtest engine (172 lines)
│   ├── vwap_strategy.py         # VWAP crossover strategy — DEPRECATED, PF≈1.0 (174 lines)
│   ├── vwap_signals.py          # VWAP signal scoring (used by vwap crossover only)
│   ├── ema_momentum.py          # EMA5/EMA20 momentum breakout — RESEARCH ONLY, not deployed
│   ├── replay.py                # replay(), FakeBroker, symbol_from_csv() — offline replay engine
│   ├── morning_regime.py        # classify_regime(), load_regime_today(), synthesize_week(),
│   │                            #   score_orb_setup(), _append_api_usage() — Claude API layer
│   │                            #   fail-open throughout: API errors never block trades
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
│   ├── backtest_gap_fade.py     # Gap Fade backtest (research only, companion to mm/gap_fade.py)
│   ├── backtest_ema_momentum.py # EMA momentum backtest (research only)
│   ├── analyze_trades.py        # per-strategy P&L, win%, PF from JSONL logs
│   ├── analyze_portfolio.py     # cross-strategy exposure, daily-loss stacking analysis
│   ├── fetch_vix_morning.py     # VPS cron: fetch VIX daily data each morning
│   ├── classify_regime.py       # VPS cron 9:20 ET: Claude regime classification → regime_YYYY-MM-DD.json
│   ├── weekly_synthesis.py      # VPS cron Mon 9:00 ET: Claude weekly trade summary → Discord
│   ├── mine_first_bar.py        # H1 research: first-bar direction → 10am-11am return (IS/OOS)
│   ├── mine_autocorrelation.py  # H3 research: lag-1 autocorr by hour bucket (IS/OOS)
│   ├── flatten_simulate.py      # flatten Moomoo simulate account to zero positions
│   └── eod_summary.py           # TradeRecord/SessionSummary, load_summary(), Discord post
│
├── tests/
│   ├── test_indicators.py       # 47 tests: BB, ATR, KDJ, RSI, ADX, VWAP, EMA, bb_width_pct
│   ├── test_strategy.py         # 20 tests: signal scoring, bonus signals, walk-forward,
│   │                            #   KDJ day-boundary regression (added 2026-06-18)
│   ├── test_risk.py             # 43 tests: calc_qty, DailyTracker, fractional sizing,
│   │                            #   per_slot_dollars, trading_allowed
│   ├── test_paper.py            # 40 tests: evals, execution, events, reconcile
│   ├── test_orb_shorts.py       # 19 tests: ORB long/short entry, exit, PnL, restart recovery
│   ├── test_bb_kdj_loose.py     # 12 tests: no bonus gate, no ADX filter, unlimited trades,
│   │                            #   entry dedup, stop/target exit
│   ├── test_execution.py        # 7 tests: _confirm_fill (partial/timeout), _reconcile_positions
│   ├── test_events.py           # 9 tests: PaperEventLog, PaperPosition file I/O
│   ├── test_clock.py            # 2 tests: today() ET-date regression (added 2026-06-18)
│   ├── test_clock_seam.py       # 2 tests: static guard against raw datetime.now() usage
│   ├── test_config_staleness.py # 6 tests: cfg reload correctness across module reloads
│   ├── test_metric_consistency.py # 4 tests: backtest metric reimplementation drift guard
│   ├── test_web_dashboard_config.py # 4 tests: dashboard .env config editor safety
│   ├── test_data.py             # 4 tests: combined-archive merge/dedup
│   ├── test_replay.py           # 7 tests: replay harness invariants
│   └── test_regime_gate.py      # 11 tests: regime gate logic, fail-open, integration
│                                # Total: 234 passing tests (3 pre-existing test_data.py failures)
│
├── docs/
│   ├── PROJECT_MAP.md           # This file — full AI context document
│   ├── ARCHITECTURE.md          # 30-line data flow diagram + config reference
│   ├── expand_plan.md           # Original 5-option roadmap — all options now done/explored
│   ├── strategy_graveyard.md   # All tested/abandoned/parked features with research data
│   ├── evaluation_criteria.md  # Pre-registered gates per strategy (knob freeze)
│   └── expansions/              # Next phase plans (data mining + LLM signal layer)
│       ├── FRAMEWORK.md         # Phase-gated status tracker for both routes
│       ├── README.md            # Doc index
│       ├── route-1-data-mining.md   # Hypotheses, scripts, deploy criteria
│       ├── route-2-llm-signals.md   # LLM regime gate architecture and rollout plan
│       ├── route-3-real-money.md    # Parked — real money prerequisites
│       ├── docs/                # Scoping packet (overview, approach, infra, risks, notes)
│       └── research/            # Raw deep-research output intake
│
├── logs/                        # Runtime output (gitignored)
│   ├── paper_US_SPY_YYYY-MM-DD.jsonl   # Structured event log per symbol per day
│   ├── paper_US_QQQ_YYYY-MM-DD.jsonl
│   ├── paper_US_IWM_YYYY-MM-DD.jsonl
│   ├── paper_US_SPY_orb_position.json  # Open position state (restart recovery)
│   ├── US_SPY_K_5M_combined.csv        # 86,100 candles, 2022-01-03 to 2026-06-03
│   ├── US_QQQ_K_5M_combined.csv        # same date range
│   ├── US_IWM_K_5M_combined.csv        # same date range
│   └── paper.log / risk.log / ...      # Rotating text logs (kept forever, backupCount=0)
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

## Deployed Strategies (VPS, as of 2026-07-29)

### Live Performance (2026-06-10 → 2026-07-29, 65 trades)

| Strategy | Trades | Win% | PF | PnL |
|----------|--------|------|----|-----|
| bb_kdj | 3 | 67% | 0.97 | -$0.06 |
| bb_kdj_loose | 5 | 60% | 1.50 | +$1.89 |
| gap_fade | 1 | 0% | 0.00 | -$0.64 |
| orb | 39 | 44% | 0.76 | -$11.04 |
| vwap_pb | 17 | 41% | 1.88 | +$5.89 |
| **TOTAL** | **65** | **45%** | **0.93** | **-$3.96** |

ORB is the main drag (35/39 exit via TIME_STOP — structural entry timing issue). Regime gate live with corrected skip labels (trending_up/trending_down) since 2026-07-26. Gap large-short filter active since 2026-07-29.

---

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

**Backtest results, w=0 baseline (SPY+QQQ+IWM, 2022–2025-05-30, K_5M):**
- 60 trades (at MIN_SCORE=2), 51.7% win rate, +$19.12 total, PF=1.843
- Exit split: 48% stop / 52% target (target-dominant, better than stop-dominant)
- IWM outperforms: 61.9% win, 38% stop rate vs 50–58% for SPY/QQQ
- OOS (walk-forward): PF consistently > 1.0 across 22/39 windows
- Re-verified 2026-06-18 post-bug-fix (see below): identical to the decimal — this
  finding never touched the buggy code path, since w=0 has no rolling window at all.

**Backtest results, LIVE deployed config (SPY w=0, QQQ/IWM w=3, full dataset thru
2026-06), corrected 2026-06-18:** A day-boundary signal leak in the KDJ window lookback
(`mm/strategy.py`/`mm/evals.py` — fixed 2026-06-17) let the first 1-3 bars of a new
trading day fire on a stale KDJ cross from the previous session's close. Verified
old-buggy vs new-fixed on real data, full dataset, MIN_SIGNAL_SCORE=2:

| Symbol | Trades (buggy→fixed) | Win% (buggy→fixed) | PF (buggy→fixed) |
|--------|------------------------|----------------------|----------------------|
| SPY (w=0) | 26 → 26 | 53.8% → 53.8% | 1.999 → 1.999 (unaffected) |
| QQQ (w=3) | 292 → 199 | 40.1% → 42.7% | 1.038 → 1.064 |
| IWM (w=3) | 309 → 209 | 42.4% → 45.0% | 1.279 → 1.390 |
| **Combined** | **627 → 434** | **41.8% → 44.5%** | **1.136 → 1.195** |

The edge survives and is slightly better post-fix (contaminated trades were lower
quality, not a wash) — fewer trades (-31%) but higher win rate and PF on both w>0
symbols. Full reasoning and the contamination-rate numbers (30-39% of historical
entries affected) in `docs/strategy_graveyard.md`'s "KDJ Day-Boundary Signal Leak" entry.

**Key research decisions locked:**
- `ATR_STOP_MULT=1.0` — optimal (not 1.5 or 2.0)
- `MIN_SIGNAL_SCORE=2` — optimal (score=3 has too few trades)
- `KDJ_WINDOW_BARS=3` — ~6.7-7.7× more signals on IWM/QQQ vs w=0 on corrected data
  (previously documented as "10×" on the pre-fix buggy signal set); SPY excluded or kept at 0
- Regime filter: ADX<25 confirmed best vs 6 alternatives (BB width, volume variants)
- Timeframe: K_5M confirmed best — K_15M produces MORE stops, not fewer

---

### 2. BB+KDJ Loose (`bb_kdj_loose`) — Research Lane
**Timeframe:** 5-min candles. **Symbols:** SPY, QQQ, IWM. **Live since:** 2026-07-04.

Same entry/exit mechanics as `bb_kdj` with all gates relaxed:
- **No bonus score gate** — any BB touch + KDJ cross fires (MIN_SIGNAL_SCORE ignored)
- **No ADX/ranging filter** — fires in trending markets the standard strategy skips
- Same exit logic: BB middle target, ATR stop, optional KDJ death cross (disabled by default)
- Runs independently as `strategy='bb_kdj_loose'` — P&L is fully separable from bb_kdj

Purpose: quantify how much edge the bonus gate and ADX filter actually add. If loose underperforms
standard by a meaningful margin after ~30 trades, the gates are earning their keep.

**Backtest:** Not separately backtested (parameters match the researched bb_kdj config minus gates).
**Live data:** accumulating — see evaluation_criteria.md for gate thresholds.

---

### 3. Opening Range Breakout (`orb`)
**Timeframe:** 5-min candles. **Symbols:** SPY, QQQ, IWM.

**Opening range:**
- SPY, QQQ: first 15 minutes (9:30–9:45 ET) — `ORB_MINUTES=15`
- IWM: first 30 minutes (9:30–10:00 ET) — `ORB_MINUTES_OVERRIDES=US.IWM:30`
- Range must be 0.1%–0.8% of close price (filters tiny flat opens and news spikes)

**Entry (Long):** `close > OR high` + volume > 1.5× 20-bar MA + after OR window closes (`ORB_VOL_MULT=1.5`)
**Entry (Short):** `close < OR low` + volume > 1.5× MA + `ORB_SHORTS_ENABLED=true`
- SPY shorts only: `ORB_SHORT_SYMBOLS=US.SPY` (QQQ+IWM disabled 2026-07-09 — 0% win rate on 36 trades)
- Short kill switch: create `STOP_SHORTS.txt` in project root (no restart needed)

**VIX gate (live 2026-07-23):** `ORB_VIX_MAX_OVERRIDES=US.IWM:18` — IWM entries blocked when prior-day VIX>18 (OOS sweep PF 1.045→1.113). SPY/QQQ unfiltered (VIX filter hurts them at every threshold). Fail-open: missing VIX data = no block. Source: `logs/vix_daily.jsonl`.

**ORB setup scorer (live 2026-07-23, shadow → active):** `ORB_SETUP_SCORER_ENABLED=true`. Before each entry, calls Claude (`claude-haiku-4-5`) with direction/OR range%/vol ratio/VIX/regime. Blocks if `confidence < ORB_ENTRY_MIN_CONFIDENCE=0.65`. Fail-open: API error → confidence=1.0 (trade allowed). Scores logged to `logs/api_usage.jsonl`.

**Exit:**
- Target: per-symbol mult × OR range. Global `ORB_TARGET_MULT=1.5`; per-symbol overrides via `ORB_TARGET_MULT_OVERRIDES`.
  - OOS (2024+) optimal: QQQ=2.0× (+4.3% PF), IWM=1.0× (+6% PF), SPY=1.5× (marginal)
- Stop (long): OR low. Stop (short): OR high.
- Time stop: 15:45 ET

**One trade per day enforced** — state persisted in `logs/paper_*_orb_traded.json` for restart recovery.

**Live trades (2026-06-04):**
- SPY: entry $755.37 → exit $758.29, +$2.92 (TARGET hit) ✓
- QQQ: entry $739.65 → exit $742.17, +$2.52 (TIME_STOP) ✓

---

### 3. VWAP Pullback (`vwap_pb`)
**Timeframe:** 5-min candles. **Symbols:** SPY, QQQ, IWM (IWM added 2026-07-12: PF=1.332, 265 trades OOS).

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
- IWM PF=1.332 (265 trades OOS — added 2026-07-12)

---

### 4. Gap Fade (`gap_fade`) — Live 2026-07-12
**Timeframe:** 5-min candles. **Symbols:** SPY, QQQ, IWM. **Fires once per day at 9:35 ET bar.**

**Entry:** Previous close → first bar computes `gap_pct = (today_open - prev_close) / prev_close`
- Gap must be ≥ 0.3% and ≤ 2.0% (`GAP_MIN_PCT=0.003`, `GAP_MAX_PCT=0.02` in `mm/gap_fade.py`)
- Gap up + rejection (close < today_open) → short
- Gap down + rejection (close > today_open) → long
- `GAP_SHORTS_ENABLED=true` required for short entries

**Exit:**
- TARGET: 50% gap fill (`GAP_TARGET_FILL_PCT=0.5`)
- STOP: first-bar extreme × (1 ± `GAP_STOP_BUFFER=0.001`)
- TIME_STOP: 11:00 ET

**One trade per day** — state persisted in `logs/paper_*_gap_fade_traded.json`.

**VIX gate (live 2026-07-23):** `GAP_VIX_MAX_OVERRIDES=US.SPY:20,US.QQQ:20` — SPY and QQQ entries blocked when prior-day VIX≥20. OOS sweep (2024+): VIX 20-25 gives SPY PF 0.626, QQQ PF 0.655; VIX>25 also negative OOS. IWM positive at all VIX bands — unfiltered. Source: `logs/vix_daily.jsonl`.

**Large-gap-short filter (live 2026-07-29):** `GAP_LARGE_SHORT_FILTER_ENABLED=true`, `GAP_MAX_SHORT_PCT=0.01`. Blocks gap-up short entries when gap > 1.0%. Validated: IS PF=0.939, OOS PF=0.519 on N≥49 trades — consistent bad edge.

**Premarket fill% filter** wired in shadow mode (`GAP_PREMARKET_FILTER_ENABLED=false` default —
logs `would_filter_skip` without blocking). Validated on 9-month sample; see `strategy_graveyard.md`.

**Config knobs**: entry/exit constants in `mm/gap_fade.py` (read from `.env`); VIX gate knobs in `cfg.*` (standard pattern).

### 5. LLM Regime Gate (Route 2 — live 2026-07-23)
**Module:** `mm/morning_regime.py`. **VPS cron:** 9:20 ET Mon–Fri via `scripts/classify_regime.py`.

**What it does:** Calls Claude (`claude-haiku-4-5`) at market open with prior-day VIX, SPY/QQQ session stats, and macro calendar. Returns one of: `trending_up`, `trending_down`, `choppy`, `risk_off`, `neutral`. Result cached in `logs/regime_YYYY-MM-DD.json`.

**Gate:** `REGIME_GATE_STRATEGIES=bb_kdj,bb_kdj_loose`. When label is in `REGIME_SKIP_LABELS=trending_up,trending_down` (flipped 2026-07-26 — validated on 618 days: trending_up PF=0.513, neutral PF=0.880), all bb_kdj entries are blocked for the session.

**Fail-open:** API error or missing file → `neutral` → trades proceed normally. `REGIME_GATE_ENABLED=false` restores pre-gate behavior with zero code change.

**Live:** Gate active since 2026-07-26, blocks ~23% of days.

**Weekly synthesis:** `scripts/weekly_synthesis.py` (VPS cron Mon 9:00 ET) reads last week's position_close + signal_skip JSONL events, sends compact stats to Claude-haiku for structured analysis, writes `logs/synthesis_YYYY-WW.json`, posts to Discord.

**ORB setup scorer:** Per-trade Claude confidence gate before each ORB entry. `score_orb_setup()` in `mm/morning_regime.py`. Scores and reasons logged to `logs/api_usage.jsonl`. Gate threshold: `ORB_ENTRY_MIN_CONFIDENCE=0.50` (shadow-mode — never blocks). Mechanical calibration on 2924 trades found edge drivers are OR range + entry timing, not LLM-discriminable features. Fail-open: API error → confidence=1.0.

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
- `MAX_TRADES_PER_DAY=5` — global cap across ALL strategies combined
- `MAX_TRADES_PER_STRATEGY=0` — per-strategy cap (0 = disabled). Set to 1 to prevent ORB consuming all global slots and starving BB+KDJ/VWAP PB.
- `MAX_DAILY_LOSS=20` — daily P&L floor; trips if cumulative loss ≥ $20. Both limits checked on every `can_open(strategy=...)` call.

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
Runs: pytest (234 passing tests) → rsync logs → diagnose_logs → compare_paper_vs_backtest (all 3 symbols) → replay_vs_live diff.

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

### Active `.env` (VPS, as of 2026-07-29)
```env
TRD_ENV=SIMULATE
LIVE_TRADING_ENABLED=false
STRATEGIES=bb_kdj,bb_kdj_loose,orb,vwap_pb,gap_fade
SYMBOLS=US.IWM,US.SPY,US.QQQ
KDJ_WINDOW_BARS=3
KDJ_WINDOW_OVERRIDES=US.SPY:0,US.IWM:0
MIN_SIGNAL_SCORE=2
ATR_STOP_MULT=1.0
ORB_MINUTES=15
ORB_MINUTES_OVERRIDES=US.IWM:30
ORB_TARGET_MULT=1.5
ORB_TARGET_MULT_OVERRIDES=US.QQQ:2.0,US.IWM:1.0
ORB_VOL_MULT=1.5
ORB_VOL_MULT_OVERRIDES=US.SPY:2.0
ORB_SHORTS_ENABLED=true
ORB_SHORT_SYMBOLS=US.SPY       # QQQ+IWM shorts disabled 2026-07-09 (0% win rate, 36 trades)
ORB_VIX_MAX=
ORB_VIX_MAX_OVERRIDES=US.IWM:18
ORB_SETUP_SCORER_ENABLED=true
ORB_ENTRY_MIN_CONFIDENCE=0.50  # lowered 2026-07-29 — scorer stays shadow-mode
GAP_VIX_MAX=
GAP_VIX_MAX_OVERRIDES=US.SPY:20,US.QQQ:20
GAP_MAX_SHORT_PCT=0.01
GAP_LARGE_SHORT_FILTER_ENABLED=true  # active 2026-07-29 — IS/OOS confirmed bad edge
VWAP_PB_SYMBOLS=US.SPY,US.QQQ,US.IWM
VWAP_PB_MAX_CROSSES=1
TOTAL_CAPITAL=100
FRACTIONAL_SHARES=false
MAX_TRADES_PER_DAY=0           # unlimited (bb_kdj_loose needs room; 5 was too restrictive)
MAX_DAILY_LOSS=20
ANTHROPIC_API_KEY=<in .env, never committed>
ANTHROPIC_MODEL=claude-sonnet-5
REGIME_GATE_ENABLED=true
REGIME_GATE_STRATEGIES=bb_kdj,bb_kdj_loose
REGIME_SKIP_LABELS=trending_up,trending_down  # flipped 2026-07-26 (choppy PF=0.928 is fine)
TOTP_SECRET=<in .env, never committed>       # DASHBOARD_PASSWORD removed — TOTP only
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
Row counts/date ranges below are a snapshot (2026-06-18) — these grow continuously via
manual `fetch_candles.py` runs and (on the VPS) `scripts/fetch_daily_archive.py`'s cron;
don't trust this table as exact, just directionally current. Check `wc -l` if it matters.

| File | Candles (snapshot) | Date Range (snapshot) |
|------|---------|------------|
| `US_SPY_K_5M_combined.csv` | 86,412 | 2022-01-03 → 2026-06-09 |
| `US_QQQ_K_5M_combined.csv` | 86,412 | 2022-01-03 → 2026-06-09 |
| `US_IWM_K_5M_combined.csv` | 86,724 | 2022-01-03 → 2026-06-16 |
| `US_*_K_15M_*.csv` | 22,158 | 2022-01-03 → 2025-05-30 |
| `US_*_K_60M_*.csv` | 5,967 | 2022-01-03 → 2025-05-30 |

---

## Test Suite (234 passing tests)

```bash
python -m pytest tests/ -q              # 234 passing (3 pre-existing test_data.py failures)
python -m pytest tests/test_risk.py    # risk + sizing (43)
python -m pytest tests/test_orb_shorts.py  # ORB shorts (19)
python -m pytest tests/test_paper.py   # evals, execution, events, reconcile (40)
```

Coverage by area:
- **Indicators** (47): BB, ATR, KDJ, RSI, ADX, VWAP, EMA, bb_width_pct edge cases
- **Strategy/Signals** (20): BB+KDJ scoring, bonus signals, walk-forward, KDJ day-boundary regression
- **Risk** (43): calc_qty, DailyTracker, fractional sizing, per_slot_dollars
- **ORB Shorts** (19): long/short entry, stop/target direction, PnL sign, restart recovery
- **BB+KDJ Loose** (12): no bonus gate, no ADX filter, unlimited trades, dedup, exits
- **Paper/Evals/Execution** (47): eval functions, fill confirmation, reconcile, events, loose eval
- **Regime Gate** (11): `_regime_gate()` logic, `load_regime_today()` fail-open, integration replay
- **Clock/Seam** (4): today() ET-date regression, static clock-seam violation guard
- **Config Staleness** (6): cfg reload correctness across module reloads
- **Metric Consistency** (4): backtest metric reimplementation drift guard
- **Dashboard Config** (4): web dashboard .env editor safety
- **Data** (4): combined-archive merge/dedup
- **Replay** (7): replay harness invariants

---

## What's Parked / Backlog

See `docs/strategy_graveyard.md` for full details with research data and graveyard'd features.
See `docs/expand_plan.md` for the original 5-option roadmap (all options now done/explored).
See `docs/expansions/FRAMEWORK.md` for the next phase — data mining and LLM signal layer.

| Item | Status | Note |
|------|--------|------|
| ATR-normalized sizing (`risk_dollars / (atr × mult)`) | On hold | Needs more live slippage data |
| IWM-weighted sizing | On hold | Superseded by ATR sizing — do that first |
| Session filter (BLOCKED_HOURS) | Swept, no universal benefit | Data is definitive |
| VIX daily regime filter on BB+KDJ | Graveyard'd | IWM OOS 0.800 vs 1.033 baseline — destroyed edge |
| Push architecture (WebSocket exits) | Deferred | slippage_bps shows 60s poll costs real edge |
| ORB QQQ+IWM shorts | Disabled 2026-07-09 | 0% win rate on 36 live trades; SPY shorts kept |
| Route 1 data mining (H1/H2/H3) | **COMPLETE** 2026-07-23 | H1 null; H2 deployed as VIX gates; H3 IWM signal documented |
| Route 2 LLM regime gate | **COMPLETE** 2026-07-23 | classify_regime + gate + scorer + synthesis all live |
| Gap fade premarket fill% filter | Shadow mode | `GAP_PREMARKET_FILTER_ENABLED=false`; validated empirically but needs forward data |
| Gap fade large-gap-short filter | **ACTIVE** 2026-07-29 | `GAP_LARGE_SHORT_FILTER_ENABLED=true`; IS PF=0.939, OOS PF=0.519 — consistent bad edge |
| Flip `GAP_PREMARKET_FILTER_ENABLED=true` | Waiting | Need live forward data on gap fade first |
| Dashboard auth | **TOTP** 2026-07-29 | DASHBOARD_PASSWORD removed; TOTP_SECRET in .env; /config TOTP-protected, / and /api/* public |

---

## Key Invariants (Never Violate)

1. `TRD_ENV=SIMULATE` always
2. `LIVE_TRADING_ENABLED=false` always — code checks this before every order
3. Only evaluate **closed** candles — `_latest_closed_candles()` drops the last (forming) bar and checks age of the resulting last closed bar (≤15 min old)
4. `STOP_TRADING.txt` / `STOP_SHORTS.txt` — runtime kill switches, no restart needed
5. `live_trade_runner.py.DISABLED` — never executed
6. No secrets in code — all credentials in `.env` (gitignored)

# moomoo-trader — Audit Context Bundle (assembled 2026-08-24)

This is a single-file context dump for an independent LLM audit (ChatGPT). It concatenates
the project's own canonical docs, unmodified, in reading order. Treat everything below as the
project's self-reported state — verify claims against the actual code where it matters, the
same way this project treats its own cross-model audits as "input to verify, not fact."

## Read this first

- **Purpose of the audit requested:** general review — code quality, doc consistency,
  process/methodology soundness, anything that looks structurally weak or that an AI workflow
  would trip over as the repo keeps growing. Same spirit as the prior Codex audits already in
  `docs/codex-grand-audit-2026-06-19.md`, `docs/codex-ai-size.md` (not included below — ask if
  you want those too; they're past *outputs*, not inputs).
- **Safety framing, non-negotiable:** this is a **paper-trading-only** research project.
  `TRD_ENV=SIMULATE` and `LIVE_TRADING_ENABLED=false` always. No real money at risk, ever.
  Any audit finding should assume this constraint is permanent, not a TODO.
- **Known staleness in the docs below:** `PROJECT_MAP.md`'s per-file line-count annotations
  (e.g. "data.py (99 lines)") are from 2026-07-29 and drifted — `mm/data.py` is actually 154
  lines as of today. Line counts are decoration, not load-bearing; don't flag the drift itself
  as a finding, but don't trust exact numbers in that section either.
- **Two bugs found and fixed *today* (2026-08-24), for calibration** — if your audit
  independently surfaces either of these, that's a good sign it's doing real analysis rather
  than pattern-matching the docs back:
  1. `mm/data.py` used the stale-cfg import pattern (`from .config import cfg` bound at import
     time) that a 2026-06-18 audit fixed everywhere else in the package — this one module was
     missed. Consequence: the test suite silently wrote 4 fabricated OHLC rows (including a
     close=999.0 on a ~$292 ETF) into the live, never-pruned research archive
     (`logs/US_IWM_K_5M_combined.csv`), and this had been happening for ~2 months, presenting
     as "3 pre-existing test failures" that were documented as an acceptable quirk rather than
     investigated. Full writeup: `docs/strategy_graveyard.md`, "Stale cfg in mm/data.py
     poisoned the live research archive."
  2. `docs/evaluation_criteria.md` set bb_kdj's PF<1.0 gate to "30 trades" while the same
     document already stated that strategy's own backtest frequency as ~20 trades/yr — meaning
     the gate needed ~18 months to ever trip. Nobody had multiplied those two numbers together.
     Full writeup: same file, amendment log entry dated 2026-08-24 ("gate ETAs").

## Table of contents (in reading order below)

1. `CLAUDE.md` — project root instructions / orientation
2. `docs/PROJECT_MAP.md` — full file map, strategy specs, repo structure (self-declared AI context doc)
3. `docs/ARCHITECTURE.md` — data flow, live config reference, kill switches
4. `docs/evaluation_criteria.md` — pre-registered strategy gates ("the knob freeze")
5. `docs/strategy_graveyard.md` — full history: dead strategies, bugs found/fixed, decisions, methodology

---


---

# SOURCE FILE: CLAUDE.md

Project: Moomoo API trading research and paper-trading project.

Directory:
~/projects/moomoo

Environment:
- Arch Linux.
- Moomoo desktop runs.
- OpenD is already installed and launched externally through a systemd user service.
- Python moomoo-api has already connected successfully to OpenD at 127.0.0.1:11111.
- Do not modify OpenD, the extracted AppImage files, the OpenD wrapper script, or the systemd service.
- Python venv at .venv/ — activate with: source .venv/bin/activate
- Main package is mm/ (NOT src/, NOT moomoo/ — moomoo/ would shadow the pip package)

Goal:
Build a practical Python project for AI-assisted stock strategy research and Moomoo paper trading.
Intended for GitHub publication. Keep it clean, readable, and extensible but not over-engineered.

Where the real state lives (read these, not your memory of past sessions):
- docs/ARCHITECTURE.md      — data flow diagram, deployed strategy table, config reference, kill switches
- docs/PROJECT_MAP.md       — full file map, strategy specs with backtest numbers, risk/sizing, event log format
- docs/evaluation_criteria.md — pre-registered gates per strategy (the "knob freeze" — read before touching any strategy parameter)
- docs/strategy_graveyard.md — every tested/dead/parked feature with the research data and reasoning,
  current "on hold" items, plus a "Bug-Hunting Methodology" section (recurring bug categories, when to
  run a fork-based audit, what's deliberately out of scope for a solo project)
This file (CLAUDE.md) intentionally does NOT duplicate that detail. If something here conflicts with
those docs, the docs win — update this file's pointer, don't re-paste their content back in here.

Logging: logs/ is gitignored. Per-symbol-per-day JSONL trade event logs are kept forever (the actual
research data — never pruned). Plain-text debug logs (paper.log, risk.log, etc.) rotate daily and are
also kept forever (backupCount=0 in mm/logger.py). VPS and local each keep their own independent
historical candle archives under the same filenames — sync_logs.sh explicitly excludes the VPS's
small rolling archive from ever overwriting local's much larger one. See mm/data.py::update_combined_csv.

Package layout:
  mm/config.py         — .env loading, cfg singleton (all config lives here)
  mm/logger.py         — file + console logging (TimedRotatingFileHandler, midnight rotation, kept forever)
  mm/connection.py     — quote_context() context manager for OpenD
  mm/health.py         — run_health_check() (socket + quote ping)
  mm/data.py           — fetch_candles(), fetch_and_save(), update_combined_csv() (rolling archive merge)
  mm/clock.py          — time seam: now(), now_et(), today(), sleep(), is_market_open(), seconds_until_open()
  mm/indicators.py     — bollinger_bands(), atr(), kdj(), rsi(), adx(), vwap(), ema(), add_all()
  mm/signals.py        — score_df(), snapshot() — BB+KDJ signal scoring
  mm/strategy.py       — compute_signals(), run_signals(), Trade, Signal
  mm/backtest.py       — run_backtest(), walk_forward(), print_summary()
  mm/research.py       — compare_variants(), sweep_parameters(), analyze_stop_exits(), sweep_signal_filter()
  mm/premarket.py      — premarket_session(), premarket_fill_pct(), premarket_volume_ratio() (research, not live-wired)
  mm/gap_fade.py        — Gap Fade strategy engine (live 2026-07-12) + backtest engine
  mm/events.py         — PaperEventLog, PaperPosition, position/ORB file I/O (_load/_save/_clear_position, _load/_save_orb_traded)
  mm/execution.py      — order placement (_place_buy/sell/short/cover), fill confirmation, _reconcile_positions, trade_context
  mm/evals.py          — per-strategy eval functions (_eval_bb_kdj, _eval_bb_kdj_loose, _eval_vwap, _eval_vwap_pb, _eval_orb), _entry_attempted
  mm/risk.py           — trading_allowed(), calc_qty(), DailyTracker, _qty(), _position_cap(), _slot_dollars
  mm/paper.py          — loop + _latest_closed_candles + _eval_symbol_all_strategies + run_multi + back-compat re-exports
  mm/replay.py         — replay(), FakeBroker, symbol_from_csv() — offline candle replay through the real runner + fake broker
  mm/orb_strategy.py   — ORB backtest engine, _build_opening_ranges() (supports per-symbol orb_minutes)
  mm/vwap_pullback.py  — VWAP Pullback (flush-and-reclaim) backtest engine
  mm/vwap_strategy.py  — VWAP crossover strategy (deprecated, PF≈1.0)
  mm/vwap_signals.py   — VWAP signal scoring (used by vwap crossover strategy)
  mm/ema_momentum.py   — EMA5/EMA20 momentum breakout backtest engine (research only, not deployed)
  mm/notifications.py  — Discord webhook (no-ops if URL not set)

  IMPORTANT — module ref pattern: use `from . import config as _config` + `_config.cfg.*` at runtime in any module
  that replay tests might reload. `from .config import cfg` binds at import time and becomes stale after _reload_paper.
  Bug fix 2026-06-18: mm/strategy.py, mm/backtest.py, mm/research.py were violating this (found via a new test
  exposing stale cfg across reloads) — all three now correctly re-fetch `cfg = _config.cfg` inside each function.

Scripts (all run from project root with venv active):
  python scripts/health_check.py
  python scripts/fetch_candles.py [--symbol US.SPY] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--ktype K_5M] [--extended-time]
  python scripts/fetch_daily_archive.py [--symbols ...] [--lookback-days 10]  # VPS cron: builds own rolling RTH+EXT archive
  python scripts/research_premarket_gap.py --symbol US.IWM [--start ...] [--end ...] [--details]
  python scripts/run_backtest.py --latest
  python scripts/walk_forward.py --latest [--window 30]
  python scripts/research.py --latest [--exits] [--walk-forward]
  python scripts/sweep.py --latest [--entry strict|relaxed] [--window 90]
  python scripts/sweep_signals.py --latest                                  # regime/ranging signal filter sweep
  python scripts/multi_backtest.py [csvs...] [--sweep] [--ktype K_5M] [--window 90]
  python scripts/simulate_paper.py [csv] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--compare]
  python scripts/run_paper.py [--symbol US.SPY]
  python scripts/compare_paper_vs_backtest.py [paper_jsonl] [--candle-csv CSV]
  python scripts/backtest_vwap_pb.py [csvs...] [--latest] [--all] [--sweep]
  python scripts/backtest_ema_momentum.py [csvs...] [--latest] [--all] [--sweep] [--entry cross|pullback]
  python scripts/sweep_session_filter.py [csvs...] [--all]                    # BB+KDJ entry hour filter sweep
  python scripts/replay_paper.py --latest [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--fill touch|instant|never|entry_only]
                                                                               # replay candles through the REAL runner + fake broker
  python scripts/replay_vs_live.py [--date YYYY-MM-DD]                         # diff live session decisions vs replay (verify.sh step 5)
  python scripts/weekly_report.py [--dry-run]                                  # Discord gate-progress + premarket report
  python scripts/analyze_orb_hours.py [event_dir]                              # ORB entry-hour edge analysis (replay or live dirs)
  python scripts/analyze_trades.py [--all] [--start YYYY-MM-DD]                # per-strategy P&L, win%, PF from JSONL logs
  python scripts/analyze_portfolio.py [--start YYYY-MM-DD]                     # cross-strategy exposure and daily-loss stacking
  python scripts/backtest_orb.py [csvs...] [--latest] [--all] [--sweep]
  python scripts/backtest_gap_fade.py [csvs...] [--latest] [--all]             # Gap Fade backtest (research only)
  python scripts/flatten_simulate.py                                            # flatten Moomoo simulate account to zero positions
  python scripts/fetch_vix_morning.py                                           # VPS cron: fetch VIX daily data each morning
  python scripts/web_dashboard.py [--host HOST] [--port PORT]                  # Flask dashboard (VPS :8080, behind nginx)
  python scripts/eod_summary.py [--date YYYY-MM-DD] [--dry-run]               # end-of-day summary post to Discord
  python scripts/dashboard.py                                                  # live TUI dashboard
  python scripts/dashboard.py --date YYYY-MM-DD                               # review past session
  python scripts/diagnose_logs.py [--date YYYY-MM-DD] [--all] [--symbol US.SPY]
  ./scripts/verify.sh [--date YYYY-MM-DD] [--no-sync]                         # pytest + sync + diagnose + compare
  ./start.sh                                                                   # start OpenD + paper runner
  ./stop.sh                                                                    # stop paper runner
  ./sync_logs.sh                                                               # rsync VPS logs → local logs/
  ./scripts/install_cron.sh                                                    # idempotent VPS cron installer

Safety rules (never violate):
- TRD_ENV=SIMULATE always. Never change to REAL.
- LIVE_TRADING_ENABLED=false always. Code checks this before placing any order.
- STOP_TRADING.txt in project root pauses the paper runner without killing the process.
- STOP_SHORTS.txt would disable ORB short entries at runtime if recreated — currently NOT present
  (removed 2026-06-17; ORB shorts are live in SIMULATE — see strategy_graveyard.md for why).
- live_trade_runner.py.DISABLED is intentionally never executed.
- Do not store secrets in code.

Strategy (BB + KDJ mean reversion, 5-min candles) — the core spec, parameters may evolve, see evaluation_criteria.md:
- Entry: close <= BB lower(20,2) AND KDJ(9,3) golden cross within KDJ_WINDOW_BARS, plus bonus score gate
- Exit target: close >= BB middle
- Exit stop: close < entry_price - ATR_STOP_MULT * ATR(14)
- KDJ death cross exit is DISABLED by default (EXIT_ON_KDJ_DEATH=false in .env)
- All signals use closed candles only
- bb_kdj_loose: research lane variant — same entry/exit but no bonus gate (MIN_SIGNAL_SCORE ignored)
  and no ADX/ranging filter. Runs independently as strategy='bb_kdj_loose' so P&L is separable.
- ORB and VWAP Pullback are also live — see docs/ARCHITECTURE.md for their specs, not duplicated here.
- gap_fade: fires once per day at 9:35 ET; fades the opening gap (gap up+rejection→short,
  gap down+rejection→long); exit on TARGET (50% fill) / STOP / TIME_STOP (11:00 ET).
  One trade per day per symbol. Deployed live 2026-07-12.

Current priorities — this is a snapshot, not a sequence. Use judgment about what's actually most
useful right now; deviate freely when something better surfaces (e.g. a dashboard bug, an unblocked
strategy, a doc cleanup). Don't treat this list as a gate against doing other useful work.
- Six live strategies: bb_kdj, bb_kdj_loose (live 2026-07-04, research lane), orb (SPY shorts only
  as of 2026-07-09 — QQQ+IWM shorts disabled after 0% win rate on 36 trades), vwap_pb,
  gap_fade (live 2026-07-12).
- Accumulate live data — most "what does the data say" questions need more samples.
  See docs/evaluation_criteria.md for the actual pre-registered sample-size gates per strategy.
- docs/expand_plan.md is the original 5-option roadmap — all 5 options are done or explored.
  Next phase is in docs/expansions/ — start at docs/expansions/FRAMEWORK.md.
  Two primary routes: Route 1 (data mining, scripts/mine_*.py) and
  Route 2 (LLM regime gate, mm/morning_regime.py + mm/evals.py).
- Gap Fade (mm/gap_fade.py) is LIVE as of 2026-07-12. Fires once per day at 9:35 ET.
  GAP_LARGE_SHORT_FILTER_ENABLED=true on VPS (blocks gap-up shorts >1.0% — IS/OOS confirmed bad edge).
  GAP_PREMARKET_FILTER_ENABLED=false (shadow mode only, logs would_filter_skip).
  Knobs are self-contained module constants in mm/gap_fade.py (file deliberately doesn't import cfg).
- docs/codex-ai-size.md / codex-ai-size-remedies.md — repo doc-hierarchy analysis, explicitly
  parked for a future dedicated session, not in progress.

Do not ask before every small change. Make reasonable implementation decisions.
After changes, explain what was built, how to run it, and what remains.

---

# SOURCE FILE: docs/PROJECT_MAP.md

# moomoo-trader: Full Project Map

**AI Context Document** — paste this into any AI session to get full project context without re-deriving.
Last updated: 2026-08-24.

**Live scoreboard (102 trades, 2026-06-10 → 2026-08-24): +$12.92, PF 1.189, 49% win.**
vwap_pb PF 2.46 and orb PF 1.04 (recovered from 0.76 after `ORB_LATEST_ENTRY=12:30`) carry it;
gap_fade PF 0.29 is the only net drag. Per-*symbol* the picture is starker than per-strategy —
QQQ +$28.99, SPY −$8.88, IWM −$10.54 — see the cross-strategy symbol effect entry in
`strategy_graveyard.md`. Gates and their current standing live in `evaluation_criteria.md`.

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

---

# SOURCE FILE: docs/ARCHITECTURE.md

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
ANTHROPIC_MODEL=claude-sonnet-5
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

---

# SOURCE FILE: docs/evaluation_criteria.md

# Pre-Registered Evaluation Criteria

Written: 2026-06-10, before meaningful live data exists (6 trades total).

Purpose: decide *in advance* what live paper results would change our minds, so outcomes
can't be rationalized after the fact. These gates were set when we had no stake in any
particular result. Changing a gate after data starts arriving requires writing down why
in this file, with the date.

## The knob freeze

**No strategy parameter changes until a gate below trips or its sample size is reached.**

Exceptions:
- Bug fixes (wrong behavior vs documented intent) — always allowed.
- Infrastructure/risk config (MAX_DAILY_LOSS, position caps, polling) — not strategy knobs.
- A new, separately-validated strategy may be added; existing knobs stay frozen.

The biggest risk to this project is not a bad strategy — it's re-tuning parameters faster
than live data can validate them.

## Sizing a gate: check the ETA before picking N

Added 2026-08-24, after the bb_kdj gate sat at 30 trades for 2+ months while the same document
already stated the strategy's own backtest frequency (~20 trades/yr combined at w=0) — meaning
the gate as written needed **~18 months** to ever trip. Nobody did that arithmetic when 30 was
picked; it was a round number carried over from ORB's gate, which trades ~5x more often.

**Before writing any sample-size gate, compute and write down: backtest (or live, if backtest
unavailable) trades/week for the exact config being gated → weeks to reach N → an ETA.** If the
ETA is beyond ~4-6 months, either the N is wrong for this strategy's frequency, or the strategy
is understood in advance to need a long soak — in which case say so explicitly instead of
implying a normal gate. A gate nobody expects to trip within the project's real time horizon is
not a gate, it's decoration.

This does not mean shrinking N until it trips fast — a low-frequency edge (w=0 BB+KDJ) is
allowed to stay low-frequency; that's the point of it. It means the *threshold* has to be
picked with the frequency in view, not copied from a different strategy's cadence.

## VWAP PB (SPY + QQQ, 10:00 ET filter)

The 0/4 start (Jun 8–9) does NOT count against the strategy: all four entries were 9:50 ET
opening-noise trades under the old 9:45 filter, an identified mechanical cause now fixed.
The clock starts fresh at 2026-06-10 with `VWAP_PB_MIN_ENTRY_TIME=10:00`.

Backtest expectation: SPY OOS PF=1.655, QQQ OOS PF=1.072.

| Gate | Sample | Action |
|------|--------|--------|
| PF < 1.0 or win% < 40% | 20 trades | Suspend (remove from STRATEGIES), post-mortem before any re-tune |
| QQQ PF < 1.0 while SPY PF ≥ 1.2 | 15 trades/symbol | Drop QQQ from VWAP_PB_SYMBOLS (QQQ was marginal in backtest anyway) |
| Any entry logged before 10:00 ET | 1 trade | Bug — fix immediately |

## BB+KDJ (SPY/IWM at w=0, QQQ at w=3 — corrected 2026-08-24, header had it backwards)

Backtest expectation at w=3 (corrected 2026-06-18, see amendment log): combined 44.5% win,
PF=1.195, 434 trades on the full dataset — better than the previous "thin edge" framing,
not worse. The w=3 lookback had a day-boundary leak bug (fixed); the old 41.7%/PF=1.107
figure below included contaminated trades. w=0 is still the strongest-validated signal
(PF 2.131 on the original 2022-2025 window, ~20 trades/yr combined) — that finding is
unaffected by the bug (w=0 has no rolling window to leak).

| Gate | Sample | Action |
|------|--------|--------|
| PF < 1.0 | 15 trades | Switch all symbols to w=0 (accept low frequency) — do not suspend, the w=0 edge is the best-validated finding in the project |
| Cross-age subset analysis: w=0-subset trades (kdj_cross_age=0) materially outperform w>0 trades | 3 months of data | Switch to w=0 |
| Zero entries fired | 4 weeks | Investigate signal pipeline (compare vs simulate_paper.py on same dates) — silence is a bug symptom, not patience |

`kdj_cross_age` is logged on every bar_eval/position_open so the subset comparison
requires no parallel runner. See scripts/analyze_trades.py BB+KDJ section.

## ORB (all three symbols, IWM at 30-min OR)

Backtest expectation: PF=1.215, 54.5% win, ~0.9 trades/day combined. Highest-confidence
strategy, but most execution-sensitive (breakout fills are competitive).

| Gate | Sample | Action |
|------|--------|--------|
| PF < 1.0 | 30 trades | Check slippage/fill quality FIRST (intended_price vs fill in JSONL, candle_age_s). Only touch strategy parameters if execution is clean |
| Avg fill worse than intended by > 5 bps | 15 trades | Execution problem — reduce polling latency or accept edge erosion; not a strategy knob issue |
| Win% < 40% with clean execution | 30 trades | Suspend and post-mortem |

## BB+KDJ LOOSE (research lane, live 2026-07-04)

Added retroactively 2026-08-24 — see amendment log. This is the no-gate variant of BB+KDJ
(MIN_SIGNAL_SCORE ignored, no ADX/ranging filter). Its purpose is to measure what the bonus
gate is worth, so it is judged *relative to* bb_kdj, not on absolute PF.

| Gate | Sample | Action |
|------|--------|--------|
| loose PF < bb_kdj PF by ≥ 0.3 | 20 loose trades | The bonus gate is earning its complexity — document and keep both; no knob change |
| loose PF > bb_kdj PF by ≥ 0.3 | 20 loose trades | The bonus gate is costing money — post-mortem, consider lowering MIN_SIGNAL_SCORE on production bb_kdj |
| \|difference\| < 0.3 | 20 loose trades | Gate is neutral. Retire bb_kdj_loose (it is measurement scaffolding, not a strategy) |

## Gap Fade (live 2026-07-12)

Added retroactively 2026-08-24 — see amendment log. Fires at most once per symbol per day at
9:35 ET, so sample accrues slowly (~1 trade per 6 sessions across all three symbols).

| Gate | Sample | Action |
|------|--------|--------|
| PF < 1.0 | 20 trades | Suspend (remove from STRATEGIES), post-mortem before any re-tune |
| Per-symbol PF < 0.5 while combined PF ≥ 1.0 | 10 trades/symbol | Drop that symbol from gap_fade (mirrors the ORB-shorts precedent) |
| Zero entries fired | 6 weeks | Investigate the 9:35 trigger path — silence is a bug symptom |

## Symbol-level (cross-strategy)

Added 2026-08-24. All prior gates are per-strategy, which cannot see an effect that runs the
other way — a symbol that is bad *across* strategies. Live data through 2026-08-24 shows SPY
net negative in 5 of 5 strategies while QQQ is net positive in 4 of 5. That observation is what
prompted this section, so it is **not** a clean pre-registration; the gate below is set so the
decision still requires more data than the observation was made on.

| Gate | Sample | Action |
|------|--------|--------|
| A symbol is net negative in ≥ 4 of 5 strategies AND combined symbol PF < 0.8 | 50 trades on that symbol | Post-mortem before any action: check spread/slippage and per-strategy stop distances first. Only then consider dropping the symbol from SYMBOLS |
| A symbol is net positive in ≥ 4 of 5 strategies AND combined symbol PF > 1.5 | 50 trades on that symbol | Do **not** concentrate into it — record the finding and leave allocation alone (single-symbol concentration is how this project would blow up its own sample size) |

## Portfolio-level

| Gate | Trigger | Action |
|------|---------|--------|
| MAX_DAILY_LOSS hit on 2 days in any 10-session window | — | Review concurrent-exposure stacking (scripts/analyze_portfolio.py) before resuming; consider MAX_CONCURRENT_POSITIONS |
| Broker reconciliation mismatch | 1 occurrence | Halt (existing Discord alert), manual review |

## Review cadence

This document gates two different things on two different clocks — conflating them caused
confusion (amended 2026-06-18, see log).

- **Health/bug monitoring** — uptime gaps, stale candles, execution quality, log errors.
  Check as often as you want (`scripts/diagnose_logs.py`, `scripts/analyze_trades.py --all`).
  Daily is fine. Finding and fixing a bug is never "too early."
- **Gate/performance evaluation** — deciding whether a strategy's results are good or bad
  enough to act on. This is sample-size-gated, not calendar-gated: the trigger is a gate in
  this doc tripping (e.g. "30 trades reached"), not a day of the week. Looking at PnL more
  often doesn't make the data more meaningful — with 1-3 trades/day across all strategies,
  day-to-day swings are noise around an edge too small to see yet. Look whenever you want;
  just don't change a strategy's parameters off a sample smaller than its gate's threshold.

## Amendment log

- 2026-08-24 (gate ETAs): Computed actual weeks-to-trip for every open gate using live accrual
  rate. Two were broken: **bb_kdj's PF<1.0 gate at 30 trades needs ~13 months** at the live rate
  (0.53 trades/wk) — lowered to **15 trades** (~6.5 months, still slow but the strategy's known
  frequency, not a bug). **bb_kdj_loose's gate at 30 needs ~4.6 months** — lowered to **20**
  (~3.1 months). Neither strategy's entry/exit logic changed; only the sample size that decides
  when to look. Added a "Sizing a gate: check the ETA before picking N" section above the knob
  freeze so future gates are written against the strategy's own accrual rate instead of a round
  number — the 30-trade figure for bb_kdj was traceable to ORB's gate, a strategy that trades
  ~5x more often, and nobody re-derived it for BB+KDJ's actual frequency.
  Also corrected the BB+KDJ section header, which had SPY/IWM's window assignment backwards
  (said "IWM/QQQ at w=3, SPY at w=0"; live config is SPY+IWM at w=0, QQQ at w=3).
  Current ETAs at live pace: vwap_pb SPY symbol-gate ~1.6wk, SPY cross-strategy gate ~2.7wk,
  gap_fade IWM ~4.1wk, gap_fade combined ~6.1wk, bb_kdj_loose ~12.6wk (new gate), IWM
  cross-strategy ~11.6wk, bb_kdj ~26wk (new gate). No strategy has an indefinite ETA now.
- 2026-08-24: **Added three missing gate sections: BB+KDJ LOOSE, Gap Fade, Symbol-level.**
  bb_kdj_loose went live 2026-07-04 and gap_fade 2026-07-12 — both had accumulated live trades
  for 6-7 weeks with *no* pre-registered gate in this file. That is the exact failure mode this
  document exists to prevent, and it happened silently because the file was only ever updated
  when a gate tripped, never when a strategy was added.
  **Honesty caveat:** these gates were written *after* seeing 11 bb_kdj_loose and 10 gap_fade
  trades, so they are retroactive, not pre-registered. They are deliberately set above the
  current sample (20 for gap_fade vs 10 today; 10/symbol vs 6 for IWM today; 50/symbol vs 40
  for SPY today) so that acting on them still requires data we do not yet have. Treat any
  conclusion drawn from them as weaker than one from a genuinely pre-registered gate.
  **New process rule:** adding a strategy to `STRATEGIES` requires adding its gate section here
  in the same change. No exceptions.
  No existing gate thresholds or live knobs were changed by this amendment.

  Gate standing at time of writing (102 live trades, 2026-06-10 → 2026-08-24, +$12.92, PF 1.189):

  | Strategy | Trades | PF | Gate | Status |
  |---|---|---|---|---|
  | vwap_pb | 28 | 2.46 | PF<1.0 @20 | passed, not tripped |
  | orb | 47 | 1.04 | PF<1.0 @30 | recovered from 0.76 (Jul 25) after ORB_LATEST_ENTRY; not tripped |
  | bb_kdj_loose | 11 | 1.73 | vs bb_kdj @20 (resized 08-24, was 30) | 11/20, ~9wk to ETA |
  | gap_fade | 10 | 0.29 | PF<1.0 @20 | 10/20, **on track to trip, ~6wk ETA** |
  | bb_kdj | 6 | 1.32 | PF<1.0 @15 (resized 08-24, was 30) | 6/15, ~17wk to ETA |

  Two findings recorded but **not acted on**, both below their gate:
  (1) vwap_pb on SPY is 2/13 wins, PF 0.09, and every one of the 13 exited `VWAP_LOST` — no
  stop, no target, no time stop. QQQ shares the same exit rule but has a right tail (one 47-min
  runner) that SPY never produces. Sample is 13 vs the 15-trade symbol gate — two trades short.
  (2) gap_fade on IWM is 2/6, PF 0.09, −$4.23 of the strategy's −$4.52 total. Sample is 6 vs
  the new 10-trade symbol gate.
- 2026-06-18: Reworded "Review cadence" — "weekly, do nothing in between" was read as
  forbidding daily bug/health checks, which was never the intent (the events.py UTC-vs-ET
  timestamp bug found this same day was caught by exactly that kind of daily check). The
  actual constraint is sample-size-gated (don't re-tune off too few trades), not calendar-
  gated (don't look more than once a week). No gate thresholds or knobs changed.
- 2026-06-10: Initial version.
- 2026-06-10 (post-close): VWAP PB trade #1 (QQQ, entry 10:10 ET @ 707.20) VOIDED — does
  not count toward the 20-trade gate. The entry limit order pended 5.5 min; periodic broker
  reconciliation ran at minute 4, saw no broker position, and cleared local state. The order
  then filled at 706.67 and the position was never exit-managed (rode to 695 unmanaged).
  Entry logic itself was correct (10:00 filter, cross_count=1, flush-and-reclaim all valid).
  Hypothetical managed exit: VWAP_LOST at 10:50 ET @ 706.12 = −$1.08. Not counted either way.
  Fix: reconcile now checks entry-order status (filled → keep; pending within 30-min grace →
  keep; pending past grace → cancel + clear). VWAP PB gate counter remains 0/20.
- 2026-06-12: Replay-harness research (no gate or knob changes). (1) 2026 YTD through the
  real runner: vwap_pb PF 1.89 (+$24) — beats backtest expectation; orb PF 1.04 (+$14) —
  near its PF<1.0 gate line; bb_kdj w=3 PF 0.85 (−$8). (2) BB+KDJ w=0 counterfactual, 2026
  YTD: 10 trades, PF 0.98 — the 2022–25 w=0 edge (PF 2.13) does NOT reproduce in 2026
  (sample tiny; treat the gate's "switch to w=0" action with caution if it trips). (3) ORB
  afternoon cutoff REJECTED OOS: 2026 hours-12+ bleed (−$93/75 trades) contradicted by
  2022–25 (+$65/698 trades, PF 1.16) — see graveyard. If the ORB gate trips, slice live
  trades by entry hour as part of the post-mortem (scripts/analyze_orb_hours.py logs/).
- 2026-06-10 (post-close, audit): ORB trades #1–2 (Jun 4 SPY +$2.92, QQQ +$2.52) reclassified
  as UNVERIFIED — broker history shows neither exit executed (SPY sell cancelled unfilled at
  EOD; QQQ sell order failed outright). Entries and signal logic were valid; recorded PnL is
  model PnL, not executed PnL. ORB gate counter resets to 0/30 effective with the
  fill-confirmation deploy (2026-06-10). All gates now evaluate on confirmed-fill PnL only.
- 2026-06-18: BB+KDJ w=3 backtest expectation corrected. Found via systematic adversarial
  audit (not live data): KDJ_WINDOW_BARS lookback didn't respect calendar-day boundaries,
  letting the first 1-3 bars of a new trading day fire on a KDJ cross from the previous
  day's close. Verified 30-39% of historical w=3 entries (SPY 30%, QQQ 38%, IWM 39%) were
  contaminated. Fixed in mm/strategy.py/mm/evals.py (grouped by day now). Old-buggy vs
  new-fixed on full dataset: combined 627→434 trades, 41.8%→44.5% win, PF 1.136→1.195 —
  the contaminated trades were lower quality, not a wash. The w=0 finding (PF=2.131) is
  completely unaffected (no rolling window to leak at w=0) — re-verified exact match to
  the original number on the original data window. No live config changed; this is a
  backtest-expectation correction only. Full numbers in docs/strategy_graveyard.md
  "KDJ Day-Boundary Signal Leak". Does NOT reset the live gate counter — confirmed-fill
  PnL recorded live was computed by the (also-buggy) entry logic at the time, so live
  trades since 2026-06-11 may include some contaminated entries; not retroactively
  reclassified since the live decision was a legitimate consequence of the code as it
  existed then, unlike the Jun 4 ORB case above which was an execution-layer fiction.

---

# SOURCE FILE: docs/strategy_graveyard.md

# Strategy Graveyard & Feature Log

Everything tested, built, abandoned, or parked. Nothing is lost — code exists, findings are
documented. This file keeps sessions context-efficient by recording the "why" behind every decision.

---

## Data Mining Results (Route 1 — scripts/mine_*.py)

### H1 — First-Bar Direction Predicts 10am-11am Returns — TESTED 2026-07-23, NULL
**Hypothesis:** Does the direction of the 9:30–9:35 bar predict net return in the 10am–11am window?
**Method:** `scripts/mine_first_bar.py --all`; Mann-Whitney U test + Pearson r on up vs down first bars.
**Results (all three symbols, IS=2022-2023, OOS=2024-present):**

| Symbol | Period | n days | MW p-value | Cohen's d | Verdict |
|--------|--------|--------|------------|-----------|---------|
| IWM | OOS | 615 | 0.367 | +0.062 | NULL |
| QQQ | OOS | 611 | 0.203 | +0.071 | NULL |
| SPY | OOS | 618 | 0.173 | +0.059 | NULL |

**Conclusion:** First-bar direction carries zero predictive signal for the next hour's return. Mean differences are near zero in both directions. Effect sizes are trivially small (Cohen's d < 0.1 in all cases).
**Code:** `scripts/mine_first_bar.py` — kept for future hypothesis testing.

---

### H2 — Gap Size × VIX Band — TESTED 2026-07-23, ACTIONABLE FINDING
**Hypothesis:** Does gap fade success rate vary meaningfully by VIX regime and gap size?
**Method:** `scripts/backtest_gap_fade.py --all --sweep-vix`; 2022–2026 backtest data × vix_daily.jsonl.
**Results (2022-2026 combined):**

**SPY (285 trades):**
| VIX Band | Trades | Win% | PF | PnL |
|----------|--------|------|----|-----|
| VIX<15 | 43 | 58% | 0.918 | -1.65 |
| VIX 15-20 | 116 | 67% | 1.861 | +44.38 |
| VIX 20-25 | 70 | 40% | 0.490 | -28.58 |
| VIX>25 | 56 | 61% | 1.242 | +9.17 |

**QQQ (343 trades):**
| VIX Band | Trades | Win% | PF | PnL |
|----------|--------|------|----|-----|
| VIX<15 | 58 | 64% | 1.105 | +3.26 |
| VIX 15-20 | 150 | 65% | 1.289 | +24.06 |
| VIX 20-25 | 73 | 44% | 0.546 | -31.41 |
| VIX>25 | 62 | 61% | 1.067 | +2.78 |

**IWM (335 trades) — DIFFERENT PATTERN:**
| VIX Band | Trades | Win% | PF | PnL |
|----------|--------|------|----|-----|
| VIX<15 | 66 | 77% | 2.397 | +15.86 |
| VIX 15-20 | 151 | 69% | 1.579 | +20.50 |
| VIX 20-25 | 56 | 61% | 1.145 | +2.72 |
| VIX>25 | 62 | 56% | 1.213 | +4.66 |

**Key finding:** VIX 20–25 is the kill zone for SPY and QQQ gap fades. Win rate drops to 40–44% and PF collapses below 0.55. VIX>25 (extreme fear) is surprisingly OK — gaps become directional in a known direction. IWM is different: positive across all VIX bands, best at low VIX.
**OOS verification (2024+ only, 2026-07-23):**
- SPY VIX 20-25 OOS: PF 0.626 (-7.82), VIX>25 OOS: PF 0.898 (-0.98) → block at VIX>=20
- QQQ VIX 20-25 OOS: PF 0.655 (-11.34), VIX>25 OOS: PF 0.693 (-4.41) → block at VIX>=20
- IWM VIX 20-25 OOS: PF 2.285 (+7.79), VIX>25 OOS: PF 3.385 (+6.21) → no filter
**DEPLOYED 2026-07-23:** `GAP_VIX_MAX_OVERRIDES=US.SPY:20,US.QQQ:20` in `.env` and VPS.
`mm/evals.py::_eval_gap_fade` reads `cfg.gap_vix_max_overrides` + `_load_vix_today()` before entry.
**Code:** `scripts/backtest_gap_fade.py --sweep-vix [--start YYYY-MM-DD]`; VIX data in `logs/vix_daily.jsonl`.

---

### H3 — Lag-1 Autocorrelation by Hour Bucket — TESTED 2026-07-23, PARTIAL SIGNAL
**Hypothesis:** Is there serial correlation in 5-min returns for SPY/QQQ/IWM at different times of day?
**Method:** `scripts/mine_autocorrelation.py --all`; Pearson r between ret[t] and ret[t-1] by hour bucket.
**Results (OOS = 2024-present):**

**IWM 09:30-10:00: r=-0.185, p<0.0001, n=2461 bars — SIGNAL**
- Strongest finding. Strong mean-reversion in IWM opening 30 minutes. An up bar strongly predicts a down bar.
- Not present in IS (r=+0.049, IS p=0.030 — opposite sign, different regime). Emerged 2024+.
- Validates the BB+KDJ mean-reversion premise empirically for IWM in the opening window.
- NOT independently deployable without entry/exit mechanics — but supports the existing strategy rationale.

**SPY 13:00-14:00: r=+0.059, p<0.0001, n=7350 bars — SIGNAL (mild momentum)**
- Mild positive autocorrelation in SPY 1-2pm window. Small effect, but highly significant due to n.
- Suggests momentum strategies (not mean reversion) might have an edge in SPY 1-2pm.
- Not independently deployable at current effect size.

**QQQ: NULL** — no bucket met |r|>0.05 AND p<0.01 AND n≥200.
**IWM/SPY other buckets: NULL.**
**Code:** `scripts/mine_autocorrelation.py`

**Follow-up backtest — 2026-07-29 (`scripts/mine_autocorr_backtest.py`):**
Translated the r=-0.185 signal into a direct trade: fade each bar's direction in the 9:30-10:00
window, hold 1 bar. IS(2022-2023) PF=1.018 (near random), OOS(2024+) PF=2.550 avg_bps=+11.1.

**Verdict: NOT DEPLOYABLE — signal discovered in the OOS period itself.**
The IS r=+0.049 showed POSITIVE autocorrelation (opposite sign). The regime flipped in 2024+.
Since we found r=-0.185 in the 2024+ data and the backtest confirms PF=2.550 in the same data,
there is no truly held-out period to validate against. The PF=2.550 is real but it's an
in-sample confirmation of an in-sample discovery. Monitor: if the signal persists into 2027+
data it becomes deployable. For now, graveyard.

---

## Dead Strategies (tested, no deployable edge)

### VWAP Crossover (momentum)
**Entry:** Price crosses above VWAP, exit when it crosses back below.
**Why dead:** Avg hold = 5 bars. PF 0.877–1.024 across all combos. VWAP crossovers at 5-min are pure noise.
**Code:** `mm/vwap_strategy.py`, `mm/vwap_signals.py` — kept for reference, not imported by paper runner.

### VWAP Mean-Reversion (price below VWAP = buy)
**Entry:** Price drops below VWAP by N × ATR, target return to VWAP.
**Why dead:** 42% win rate, PF≈1.0 across 48 combos. Price below VWAP on 5-min is continuation, not reversion.
**Note:** VWAP Pullback (flush-and-reclaim) is different and IS deployed.

### EMA5/EMA20 Momentum Breakout
**Variants:** (1) EMA5 crosses EMA20 with ADX>N, (2) pullback to EMA5 while EMA5>EMA20.
**Why dead:**
- Cross entry: uniformly negative (PF 0.3–0.93 across 36 combos × 3 symbols). Trend-following at 5-min doesn't work.
- Pullback entry: stop_mult parameter completely inert — EMA20 break always triggers before ATR stop. Risk management broken.
- ADX=25 anomaly (worse than ADX=20 and ADX=30 simultaneously) — sample artifact.
**Code:** `mm/ema_momentum.py`, `scripts/backtest_ema_momentum.py`
**If revisiting:** Fix stop to ATR-only. Investigate ADX=25 anomaly on larger dataset.

### VIX Daily Regime Filter
**What it was:** Block BB+KDJ on high-volatility days (VIX > threshold).
**Backtested (2026-06-04):** `scripts/backtest_vix_filter.py --all` on SPY+QQQ+IWM combined CSVs.
**Why dead:**
- Combined OOS (2024+): Baseline PF=1.224. ALL filtered variants worse. Best: Block>=20 = 1.208.
- IWM destroyed: Baseline OOS=1.033 → Block>=20 OOS=0.800. High-VIX days are IWM's best entries.
- "Relax>30" mode: Combined OOS=1.193 — also worse than baseline.
**Code:** `scripts/backtest_vix_filter.py` kept for reference.

---

## Built & Deployed (live on VPS as of 2026-07-09)

| Feature | Code | Notes |
|---------|------|-------|
| BB+KDJ mean reversion | `mm/strategy.py`, `mm/evals.py` | MIN_SCORE=2. PF=1.843 is the w=0 baseline (60 trades); live deployed config (SPY w=0, QQQ/IWM w=3) is PF=1.195 combined, 434 trades — see "KDJ Day-Boundary Signal Leak" below for the corrected w=3 numbers. |
| BB+KDJ Loose | `mm/evals.py` (`_eval_bb_kdj_loose`) | Research lane. No bonus gate, no ADX filter. Live 2026-07-04. Tests: `tests/test_bb_kdj_loose.py`. |
| ORB long + short (SPY only) | `mm/orb_strategy.py`, `mm/evals.py` | 30-min IWM, 15-min SPY/QQQ. Shorts SPY-only as of 2026-07-09 (see ORB Short config entry below). |
| VWAP Pullback | `mm/vwap_pullback.py`, `mm/evals.py` | All three symbols (IWM added 2026-07-12). Backtest OOS PF=1.655 SPY, 1.072 QQQ, 1.332 IWM. Live SPY has diverged badly — see "VWAP PB on SPY has no right tail" under On Hold. |
| Fractional sizing | `mm/risk.py` (_qty, _slot_dollars) | TOTAL_CAPITAL / (symbols × strategies) per slot. **Not currently active** — VPS runs TOTAL_CAPITAL=0 + FRACTIONAL_SHARES=false, so sizing falls through to MAX_POSITION_DOLLARS at 1 whole share minimum. |
| JSONL event logging | `mm/events.py` (PaperEventLog) | bar_eval, signal_skip, position_open/close, slippage_bps |
| Web dashboard | `scripts/web_dashboard.py` | Flask :8080 — Market Conditions card, slippage column |
| TUI dashboard | `scripts/dashboard.py` | Textual, past session replay |
| diagnose_logs.py | `scripts/diagnose_logs.py` | 5-section session health report |
| verify.sh | `scripts/verify.sh` | pytest + sync + diagnose + compare in one command |
| compare_paper_vs_backtest | `scripts/compare_paper_vs_backtest.py` | BB+KDJ signal engine agreement check |
| Startup config validation | `mm/config.py` (validate_config) | Fails fast on bad .env before touching broker |
| Broker position reconciliation | `mm/execution.py` (_reconcile_positions) | On restart, clears stale local state if broker disagrees |
| Per-strategy trade limits | `mm/risk.py` (DailyTracker) | MAX_TRADES_PER_STRATEGY config, prevents ORB starving BB+KDJ |
| Order price rounding | `mm/execution.py` (_place_buy/sell/short/cover) | round(price, 2) — Moomoo rejects >2 dp (caught June 4, 8) |
| Entry retry dedup | `mm/evals.py` (_entry_attempted dict) | One attempt per candle per (symbol, strategy) — prevents storm |
| Fractional qty fallback | `mm/risk.py` (_qty()) | qty < 1 → whole-share fallback instead of silently rejecting |
| Daily loss limit | `mm/config.py`, `mm/risk.py` | MAX_DAILY_LOSS raised to $20 — $5 killed full day after 1 VWAP PB loss |

---

## Bugs Found & Fixed (correctness corrections to historical research)

### Stale cfg in mm/data.py poisoned the live research archive — FOUND & FIXED 2026-08-24
**What it was:** `mm/data.py` imported config as `from .config import cfg`, binding the singleton
at import time — the exact anti-pattern CLAUDE.md documents and that was fixed in
`mm/strategy.py` / `mm/backtest.py` / `mm/research.py` on 2026-06-18. `mm/data.py` was missed in
that sweep. Once any test reloaded config (the replay tests do), `_config.cfg` became a *new*
object while `data.py` kept writing through the *old* one. So `tests/test_data.py` setting
`_config.cfg.logs_dir = tmp_path` had no effect on `update_combined_csv`, and the test fixtures
were appended to the **real** `logs/US_IWM_K_5M_combined.csv` instead of a temp dir.

**What it cost:** four fabricated bars in the never-pruned IWM research archive:

| File | time_key | OHLC |
|---|---|---|
| `US_IWM_K_5M_combined.csv` | 2026-06-16 04:05 | 100.0 |
| `US_IWM_K_5M_combined.csv` | 2026-06-16 09:35 | **999.0** |
| `US_IWM_K_5M_combined.csv` | 2026-06-16 09:40 | 101.0 |
| `US_IWM_K_5M_EXT_combined.csv` | 2026-06-16 04:05 | 100.0 |

IWM trades ~$292. A 999.0 close inside the archive corrupts every rolling indicator whose window
spans 2026-06-16 — ATR, Bollinger width, VWAP — so **any IWM backtest or sweep covering that date
produced wrong numbers**, silently, every time anyone ran `pytest` and then a backtest. Every real
row carries `code=US.IWM`; the injected rows have `code=NaN`, which is how they were identified.

**Why it hid for ~2 months:** the symptom presented as "3 pre-existing test_data.py failures that
pass in isolation" and was written off in ARCHITECTURE.md as a test-isolation quirk. The failure
message (`assert 86725 == 1`) actually *named* the real archive's row count — the bug was
announcing itself in the assertion and was read as noise.

**Fix:** `mm/data.py` now uses `from . import config as _config` + `cfg = _config.cfg` re-fetched
inside `fetch_candles`, `save_candles`, `update_combined_csv`, `fetch_and_save`. Archive rows
removed. Full suite went 252 passed / 3 failed → **255 passed / 0 failed**, and a checksum on the
archive confirms the suite no longer writes to it.

**Lesson (added to Bug-Hunting Methodology below):** a test that "fails only in the full run" is a
claim that some other test mutates shared state — that is a bug report, not a known-quirk. Do not
document a persistent failure as acceptable without first identifying what state is being shared.

### ORB Scorer signal_skip TypeError — FOUND & FIXED 2026-07-25
**What it was:** `mm/evals.py::_eval_orb` called `elog.signal_skip("orb_claude_score", ..., reason=scored["reason"])`. The first positional argument to `signal_skip` is already named `reason`, so `reason=` was passed both positionally and as a keyword — a Python TypeError on every scorer block. The exception was swallowed by the paper runner's main loop (`except Exception as e`), logged as an error event, and the entry was blocked by crash rather than by the intended gate. Result: ~90 error events on 7/24, zero `orb_claude_score` skip events in JSONL despite the scorer running and returning low confidence scores. Entries were silently prevented for the 2 days the scorer was live before discovery.

**Why it was hard to see:** The scorer was making real API calls and logging them to `api_usage.jsonl` with confidence values. From the outside it looked like the scorer was working. The only tell was 90 error events and zero scorer skip events in the same session — an unusual ratio that only became visible when auditing the full event log.

**Fix:** Renamed kwarg from `reason=scored["reason"]` to `claude_reason=scored["reason"]` in `mm/evals.py:703`. Added regression test `test_low_confidence_emits_skip_not_error` in `tests/test_orb_scorer.py`. VPS restarted 2026-07-25.

### KDJ Day-Boundary Signal Leak — FOUND & FIXED 2026-06-17/18
**What it was:** `mm/strategy.py`'s and `mm/evals.py`'s KDJ_WINDOW_BARS lookback
(`.rolling(window=N+1)` / `.iloc[-window:]`) operated on a multi-day candle frame with
no calendar-day grouping. The first 1-3 bars of a new trading day could see a KDJ
golden cross from the tail end of the PREVIOUS day's close and fire an entry believing
it was reacting to a fresh same-session signal. Found via a systematic adversarial code
audit (not incidental discovery), then verified against real data before fixing.

**Why it mattered more than "a few bars a day" sounds like it should:** BB-touch
conditions (the strategy's other entry requirement) cluster disproportionately at the
session open, because overnight gaps frequently push price below the lower band right
at 9:30-9:40 ET. That's exactly the window the leak lived in. Verified contamination
rate on real combined CSVs at KDJ_WINDOW_BARS=3, MIN_SIGNAL_SCORE=2: **SPY 30%, QQQ 38%,
IWM 39%** of all historical entry signals were contaminated.

**Fix:** Both the backtester (`mm/strategy.py::compute_signals`) and the live runner
(`mm/evals.py::_eval_bb_kdj`) now group the lookback by calendar day, so the window
can never see across a session boundary.

**Does the w=0 foundational finding (60 trades, PF=1.843, documented throughout this
project) still hold?** Yes, completely unaffected. That finding was always a `w=0`
backtest — at w=0 there's no rolling window at all (`kdj_met = bool(last["sig_kdj_cross"])`,
same-bar check only), so the bug could not have touched it. Re-ran it post-fix on the
exact original data window (thru 2025-05-30) to confirm: **60 trades, 51.7% win,
PF=1.843, +$19.12 — identical to the documented figure to every decimal.**

**Does the LIVE DEPLOYED config (SPY w=0, QQQ/IWM w=3) change?** Yes — and it gets
*better*, not worse. Ran old-buggy-code vs new-fixed-code on the full current dataset
(thru 2026-06, not just the original 2025-05-30 snapshot), MIN_SIGNAL_SCORE=2:

| Symbol | Trades (buggy) | Trades (fixed) | Win% (buggy→fixed) | PF (buggy→fixed) |
|--------|----------------|-----------------|---------------------|---------------------|
| SPY (w=0) | 26 | 26 | 53.8% → 53.8% | 1.999 → 1.999 (unaffected, as expected) |
| QQQ (w=3) | 292 | 199 | 40.1% → 42.7% | 1.038 → 1.064 |
| IWM (w=3) | 309 | 209 | 42.4% → 45.0% | 1.279 → 1.390 |
| **Combined** | **627** | **434** | **41.8% → 44.5%** | **1.136 → 1.195** |

The leaked trades were genuinely lower-quality (stale-signal noise), not a wash —
removing them shrank trade count ~31% but raised win rate and PF on every w>0 symbol.
Total $ PnL dropped slightly (+$47.33 → +$45.35) purely because there are fewer trades,
not because per-trade performance worsened. **The KDJ_WINDOW_BARS=3 "10× more signals"
claim (previously documented in docs/PROJECT_MAP.md) is also corrected by this fix** —
post-fix the multiplier on the full dataset is closer to 6.7-7.7× (IWM 209/31≈6.7×,
QQQ 199/26≈7.7×), not 10×; the original 10× figure was computed on the buggy signal set.

**Bottom line:** no strategy knob changed, no live config touched. The BB+KDJ edge
survives this fix at every tested configuration and is slightly more favorable
post-fix, not less. Treat any pre-2026-06-17 backtest number that used KDJ_WINDOW_BARS>0
as superseded by this entry; w=0 numbers throughout the rest of this project's history
remain valid as documented.

### Partial Exit Fill PnL/Orphan Bug — FOUND & FIXED 2026-06-17
**What it was:** `mm/execution.py::_execute_exit()` detected partial fills (`dealt <
position.qty`) but only logged a warning — it returned just the fill price, never the
actual dealt quantity. All 4 strategy exit paths in `mm/evals.py` then computed PnL
using the full original `position.qty` and unconditionally cleared the position
regardless of fill size. A real partial fill (e.g. 2 of 3 shares) would book PnL as if
the whole position exited, then leave the unfilled remainder as an orphaned share at
the broker with zero local tracking forever — the same failure class already fixed once
on the entry side (see "Execution layer rebuilt" below) but never closed on the exit
side. No live occurrence found in the JSONL history audited, but the code path existed
and was untested (zero test coverage for this exact scenario before the fix).

**Fix:** `_execute_exit()` now returns `(fill_price, dealt_qty)`. All 4 callers use
`dealt_qty` for PnL and, on a partial fill, reduce `position.qty` and keep the position
open for the remainder to retry next poll instead of clearing it. Added
`tests/test_paper.py::TestExecuteExit::test_partial_fill_returns_actual_dealt_qty`.

### clock.today() Wrong Date Basis — FOUND & FIXED 2026-06-17
**What it was:** `mm/clock.py::today()` returned `date.today()` (local system date)
instead of the ET trading-day date, despite every caller (`DailyTracker`'s daily
loss/trade-limit reset, ORB's once-per-day guard, session-rollover detection, the
EOD-summary date) being keyed to the ET trading day. Same bug class as the KDJ leak —
day-sensitive state keyed to the wrong clock basis — just dormant in practice because
both the VPS (UTC) and local dev (America/Denver) happen to have midnight fall outside
ET market hours (9:30am-4pm ET). A timezone whose midnight falls inside that window
would have silently rolled the trading day at the wrong moment. Fixed: `today()` now
returns `now_et().date()`.

### PaperEventLog ts/Filename Server-Local Time — FOUND & FIXED 2026-06-18
**What it was:** `mm/events.py`'s `PaperEventLog` wrote the JSONL `ts` field and derived
the log filename's date from `clock.now()` (naive server-local time — UTC on the VPS),
not ET. Same bug class as `clock.today()` above, in a different module. A live ORB entry
at 13:30 ET was logged as `ts="...T17:30:02"` with no timezone label, looking like an
after-hours trade, and `diagnose_logs.py`'s market-hours staleness check (which compares
`ts.hour` against 9:30-16:00 assuming ET) was silently checking the wrong window on the
VPS. Fixed: `_path`/`_write` now use `clock.today()`/`clock.now_et()`.

Caught two follow-on regressions the same day: `scripts/web_dashboard.py`'s
`_runner_status()` compared the now-ET `ts` against `datetime.now()` (still server-local)
— would have shown a healthy runner as DEAD during market hours; `scripts/weekly_report.py`,
`scripts/diagnose_logs.py`, and `scripts/analyze_trades.py` had the same "today" default
mismatch. All fixed same day (commits `00d17b0`, `8244990`).

### Module-Ref Staleness — 6 more instances — FOUND & FIXED 2026-06-18
**What it was:** `mm/vwap_strategy.py`, `mm/health.py`, `mm/logger.py`,
`mm/notifications.py`, `mm/connection.py`, and (partially) `mm/risk.py` still used
`from .config import cfg` (binds once at import time) instead of the safe
`from . import config as _config` + runtime `_config.cfg.*` pattern documented in
CLAUDE.md. `mm/vwap_strategy.py` was not on the live path at the time (the plain VWAP
crossover strategy is dormant — `STRATEGIES` doesn't include it), so this wasn't an
active-trading risk, but `mm/risk.py`'s `DailyTracker`/`trading_allowed`/`calc_qty`
are squarely on the live path. Fixed all 6; added `tests/test_config_staleness.py`
which simulates a real `mm.config.cfg` reassignment (not just an attribute mutation)
and would have caught this directly.

### Reimplemented-Metric Drift — 3 more instances — FOUND & FIXED 2026-06-18
**What it was:** `scripts/sweep_session_filter.py` used a `999.0` no-losses sentinel
instead of the canonical `mm.backtest.profit_factor()`'s `float("inf")` (the exact
drift class described in that function's docstring, found again). `scripts/
research_premarket_gap.py` and `scripts/analyze_orb_hours.py` had their own
gross-win/gross-loss reimplementations (one used `pnl < 0` for losses instead of the
canonical `pnl <= 0`). Fixed all 3 to call `profit_factor()`; extended it to accept
plain pnl numbers (not just objects with `.pnl`) so dict/JSONL-derived callers don't
need their own wrapper. Added `tests/test_metric_consistency.py` pinning the canonical
definition.

---

## Bug-Hunting Methodology

Five categories have recurred enough times to be worth naming explicitly (see entries
above and earlier in this file): day-boundary leaks (rolling windows not grouped by
calendar day), clock-seam violations (raw `datetime.now()`/`date.today()` instead of
`mm.clock`), module-ref staleness (`from .config import cfg` instead of runtime
`_config.cfg.*`), partial-fill/fill-confirmation edge cases in `mm/execution.py`, and
reimplemented-metric drift (same calc, subtly different definition, in 2+ places).

**Static/regression tests now guard the first three categories directly**
(`tests/test_clock_seam.py`, `tests/test_config_staleness.py`,
`tests/test_config_import_pattern.py`, `tests/test_metric_consistency.py`, plus
`tests/test_execution.py`/`tests/test_events.py` for the fourth) — run them with the rest
of the suite, no special invocation needed.

**Prefer a static/grep guard over per-module behavioural tests for a whole bug category.**
`test_config_staleness.py` was behavioural — one hand-written case per module — so
`mm/data.py`, which nobody thought to add, was never checked and stayed broken for two
months (see the 2026-08-24 entry above). `test_config_import_pattern.py` was added to grep
the package instead, so the next module is covered the day it is written. A behavioural test
proves the modules you remembered work; a static test proves the ones you forgot do too.

**A test that fails only in the full suite is a bug report, not a known quirk.** It is a
claim that some other test mutates shared state. The `mm/data.py` failure was written off in
ARCHITECTURE.md as a "pre-existing test-isolation issue" for two months while its assertion
message (`assert 86725 == 1`) was literally printing the real archive's row count. Never
document a persistent failure as acceptable without first naming the shared state.

**For new instances of these (or new categories), use a fork-based parallel adversarial
audit** (multiple `Agent` calls with `subagent_type:"fork"`, each verifying findings
against real code/data before reporting — never trust a sub-agent's claim blindly).
Scope each fork **by category, not by module** — one fork sweeps the whole repo for
clock-seam violations, one for module-ref staleness, one for partial-fill edge cases,
one for day-boundary/rolling-window leaks, one for duplicated metric calculations. This
matches how these bugs actually surfaced (cross-cutting, not module-local) and is more
likely to catch the *next* instance of a known pattern than reviewing module-by-module.

Trigger an audit on: a refactor touching 3+ modules, before flipping any shadow-mode
feature to active (e.g. Gap Fade's `GAP_PREMARKET_FILTER_ENABLED`), or a ~4-6 week
backstop if neither has fired. Log findings as dated entries in this section, not as
new one-off audit docs — `docs/MASTER_AUDIT_JUNE.md`-style standalone docs tend to mix
real findings with unactionable "vision" scope creep.

Explicitly out of scope for this project (solo hobby research, not enterprise): a mypy
migration, property-based/fuzz testing as a first move, a CI/CD pipeline, or a 100%
test-coverage target. `ruff` is wired into `scripts/verify.sh` but informationally only
(reports a count, never fails the build) — the existing pre-ruff debt isn't worth a risky
bulk auto-fix (see `pyproject.toml`'s comment for why `--fix` broke a re-export pattern
on first attempt).

---

## Infrastructure & Security Hardening (VPS, not code — no commit/deploy needed for these)

These are config-only changes on the OVHcloud VPS itself, not in this repo. Logged here so
the reasoning survives a context reset, same as everything else in this file.

### VPS Security Pass — 2026-06-21

**Trigger:** OVHcloud's Anti-DDoS dashboard showed 1 detected/cleaned attack against the VPS's
public IP. Investigated and confirmed it was routine internet background noise (OVH's
network-layer scrubbing caught it before it reached the box) — no compromise: 19-day uptime,
all 3 moomoo services healthy, no unknown sessions. `auth.log` showed the expected constant
flood of failed SSH logins from random bot IPs (targeting `root`/`ubuntu`/random usernames),
all failed — this is normal background radiation for any public IP, not evidence of anything
targeted.

While checking, found and fixed three real (if unexploited) weaknesses:

1. **SSH password authentication was enabled VPS-wide.** Two conflicting cloud-init-managed
   config snippets existed (`/etc/ssh/sshd_config.d/50-cloud-init.conf` set `yes`,
   `60-cloudimg-settings.conf` set `no`) — sshd uses first-match-wins within `sshd_config.d/`,
   and `50-...` sorts first, so `yes` was actually in effect (confirmed via `sudo sshd -T`).
   Combined with the constant brute-force traffic, this was worth closing even though nothing
   had succeeded. **Fix:** added `/etc/ssh/sshd_config.d/01-hardening.conf` (sorts before both
   existing files, so it always wins) setting `PasswordAuthentication no` and
   `PermitRootLogin no`. Verified key-only login still works and password-only login is
   immediately rejected. Also installed and enabled `fail2ban` (sshd jail, 4 retries / 10 min
   window / 1hr ban) as defense-in-depth — it had already auto-banned 2 of the brute-force IPs
   within minutes of being enabled.
   Deliberately did NOT IP-allowlist port 22 in `ufw` — home/office IP stability unknown,
   too easy to lock yourself out from a new network. Disabling password auth closes the actual
   risk (brute-forcing becomes pointless regardless of source IP) without that lockout risk.

2. **The web dashboard was reachable two ways — one of them sent the password in cleartext.**
   `ufw` allowed port 8080 (the Flask dashboard, `scripts/web_dashboard.py`) from "Anywhere",
   so it was reachable both via `https://trading.flyboybyte.com` (TLS, through nginx) AND
   directly via `http://<VPS-IP>:8080` (plain HTTP, no TLS — confirmed reachable with `curl`).
   `DASHBOARD_PASSWORD` is set, so it wasn't wide open, but anyone using the direct-IP path
   would submit that password unencrypted — sniffable on any network path between them and the
   VPS. **Fix:** `sudo ufw delete allow 8080` + `sudo ufw allow from 127.0.0.1 to any port
   8080` — the only way in now is through nginx's TLS-terminated proxy (which still works,
   since nginx→Flask is loopback traffic, unaffected by the external-facing firewall rule).
   Verified the direct path now times out and the TLS path still returns 200.

3. **Same cleartext-bypass pattern on an unrelated app sharing the box** (`disc_tracker`,
   port 5757, proxied via `disc.flyboybyte.com`) — not part of this project, but the exact
   same exploit class, so fixed the same way: `ufw` restricted to `127.0.0.1`, verified direct
   path blocked and the nginx-proxied path still works.

**Also added:** nginx security headers (`Strict-Transport-Security`, `X-Frame-Options`,
`X-Content-Type-Options`, `Referrer-Policy`) via a shared snippet
(`/etc/nginx/snippets/security-headers.conf`) included in all three site configs
(`trading.flyboybyte.com`, `disc.flyboybyte.com`, `flyboybyte.com`). Backups of every edited
nginx config (`.bak` suffix) left next to the originals on the VPS.

**Confirmed NOT a bug, just a side-effect of an existing finding:** `trading.flyboybyte.com`'s
nginx block uses `disc.flyboybyte.com`'s SSL certificate. Looked like a copy-paste error at
first glance — verified via `certbot certificates` that it's actually a real multi-domain
cert (SANs cover both `disc.flyboybyte.com` and `trading.flyboybyte.com`), so this is correct,
not a mismatch.

**Not done, flagged for the user to handle directly (can't be done over SSH):** OVH account
2FA, VPS snapshots/backups. **Not done, explicitly out of scope:** IP-allowlisting SSH (risk
of lockout outweighs benefit once password auth is off); auditing nginx/headers on the two
fully-unrelated sites beyond the specific fixes above.

---

## On Hold (parked with a gate condition)

### Cross-strategy symbol effect: SPY negative everywhere, QQQ positive everywhere — observed 2026-08-24, gated at 50 trades/symbol
**What it is:** Every per-strategy analysis this project runs aggregates across symbols, which
structurally cannot see an effect that runs the other way. Slicing the 102 live trades
(2026-06-10 → 2026-08-24) by symbol *within* strategy shows a consistent pattern:

| Strategy | SPY | QQQ | IWM |
|---|---|---|---|
| bb_kdj | −1.07 (0/1) | +2.44 (3/3) | −0.45 (1/2) |
| bb_kdj_loose | −0.48 (1/2) | +7.37 (5/6) | −2.91 (1/3) |
| gap_fade | −1.05 (1/3) | +0.76 (1/1) | −4.23 (2/6) |
| orb | −0.83 (8/21, PF 0.94) | +7.99 (10/17, PF 1.43) | −5.29 (4/9, PF 0.61) |
| vwap_pb | −5.45 (2/13, PF 0.09) | +10.43 (7/10) | +2.34 (3/4) |
| **combined** | **−8.88 / 40 tr** | **+28.99 / 37 tr** | **−10.54 / 24 tr** |

SPY is net negative in 5 of 5 strategies. QQQ is net positive in 5 of 5. QQQ alone more than
accounts for the portfolio's entire +$12.92 — SPY and IWM together are −$19.
**Why parked, not acted on:** three competing explanations and the data cannot yet separate
them. (1) Real symbol effect — SPY's tighter intraday range means ATR/VWAP-based exits sit
inside the noise band. (2) Sizing artifact — `FRACTIONAL_SHARES=false` + `TOTAL_CAPITAL=0`
means position size is 1 whole share, so SPY (~$766) and QQQ (~$712) carry different notional
and therefore different PnL-per-move; PF is size-invariant but the raw PnL column is not.
(3) Coincidence at n=24–40 per symbol.
**Gate:** 50 trades on a symbol, per the new Symbol-level section in `evaluation_criteria.md`.
Post-mortem must check spread/slippage and per-strategy stop distances *before* considering a
change to `SYMBOLS`. Explicitly do **not** concentrate into QQQ if it keeps winning — that
would shrink the sample this project depends on.

### VWAP PB on SPY has no right tail — observed 2026-08-24, 2 trades short of gate
**What it is:** vwap_pb on SPY is 2 wins / 13 trades, PF 0.09, −$5.45 — while the same strategy
on QQQ is 7/10, PF 20.68, +$10.43. Cause is visible in the exit reasons: **all 13 SPY trades
exited `VWAP_LOST`.** Zero stops, zero targets, zero time stops. Median hold is ~5 min on both
symbols, but QQQ's *mean* hold is 47.7 min vs SPY's 12.5 — QQQ occasionally catches a runner
that holds above VWAP for the better part of an hour, and those few trades pay for all the
small chop losses. SPY never produces one; its largest win in 13 trades is +$0.32.
The `VWAP_LOST` exit gives no room by design, which is fine only if the winners are fat.
**Why parked:** SPY is at 13 trades against the pre-registered 15-trade per-symbol gate in
`evaluation_criteria.md` (the VWAP PB section). Two trades short. The existing gate is also
written for the *opposite* direction ("QQQ PF < 1.0 while SPY PF ≥ 1.2") — it anticipated SPY
as the strong symbol and QQQ as marginal, which is backwards from what happened. Left as-is
rather than rewritten mid-sample; note the inversion when it trips.

### Market Holiday Calendar for is_market_open() — parked 2026-06-19, low priority
**What it is:** `mm/clock.py::is_market_open()` only checks weekday + 9:30-16:00 ET — no
NYSE holiday calendar. Confirmed live on 2026-06-19 (Juneteenth): the runner correctly
thought the market should be open and polled normally, but the broker returned 0 candles
all day, producing a `Stale candles ... not enough candles (0)` loop in paper.log and no
JSONL event files for the day. Not a bug — fails safe (no candles → no eval → no trades),
just log noise and an empty session that looks alarming at a glance. NYSE has ~9 holidays/
year. Would need either a small hardcoded holiday list (simplest, needs annual upkeep) or
a calendar library (e.g. `pandas_market_calendars`, new dependency). Parked: low value for
a solo project (~9 days/year of harmless noise) versus the cost of a new dependency or an
upkeep burden. Revisit if the noise becomes annoying enough, or if holiday-day polling ever
turns out to cost something beyond log clutter (e.g. burns OpenD API quota).

### Gap Fade — BUILT 2026-06-16, pending live verification
**What it is:** Fade the overnight gap when the first 5-min bar (9:35 close) closes against
the gap direction. Gap up + red first bar → short; gap down + green first bar → long.
Target: 50% gap fill. Stop: first bar extreme + 0.1%. Time stop: 11:00 ET.
**Code:** `mm/gap_fade.py`, `scripts/backtest_gap_fade.py`
**Walk-forward (0.3% min gap, 50% fill target):**
| Symbol | Train 2022-23 | OOS 2024-25 | 2026 YTD |
|--------|---------|---------|---------|
| IWM | PF=1.031, 136 tr | PF=**1.938**, 164 tr, 72%WR | PF=2.163, 33 tr |
| SPY | PF=1.022, 147 tr | PF=1.326, 108 tr, 60%WR | — |
| QQQ | PF=1.029, 156 tr | PF=1.022, 143 tr (flat) | excluded |
**Why training is weak (PF≈1.02):** 2022-2023 was a bear market with large, meaningful overnight
gaps that don't fade. The OOS improvement is structural (low-volatility 2024-2025 = more
noise gaps). Regime risk if volatility returns to 2022 levels.
**Enablement gates:**
- ORB short must fire live at least once (same SELL_SHORT code path, currently unverified).
- 15 live paper trades before drawing conclusions.
- QQQ excluded (flat OOS). SPY optional (PF=1.326 OOS is marginal).
- Deploy IWM first (strongest and most consistent across parameter sweep).

### Risk-Normalized Position Sizing — BUILT DARK 2026-06-12
**What it is:** `share_qty = RISK_DOLLARS_PER_TRADE / (entry − stop)`, capped by the dollar cap.
Every trade risks the same dollars regardless of volatility. Generalizes the original ATR-sizing
design to actual stop distance (covers ORB's range-based stops too).
**Status:** Implemented (`mm/risk.py` calc_qty_risk, all 5 entry blocks in `mm/evals.py`),
7 tests, validated end-to-end via the replay harness. DISABLED by default
(RISK_DOLLARS_PER_TRADE=0 → byte-identical legacy behavior).
**Enablement gate (unchanged):** 2+ weeks of live fill data, then set RISK_DOLLARS_PER_TRADE
in .env.
**Replay A/B (2026 YTD, touch fills, RISK_DOLLARS_PER_TRADE=5 vs dollar-cap baseline):**
total +$65.97 vs +$30.34. ORB PF 1.04→1.16 (+$14→+$45): tight-range days get more shares,
and trades whose stop distance exceeds the $5 risk budget at 1 share are refused outright
(13 fewer ORB trades — the widest/choppiest setups). bb_kdj loss halved; vwap_pb unchanged
(already 1-share). Mechanism is risk discipline, not signal change. Caveats: one 5.5-month
window; SIMULATE fills are optimistic and slippage scales with qty.

### IWM-Weighted Position Sizing
**What it is:** `SYMBOL_SIZE_OVERRIDES=US.IWM:300,US.SPY:600,US.QQQ:500` — more capital to IWM given superior edge (61.9% win, 38% stop vs 50–58% for SPY/QQQ).
**Why parked:** Superseded by ATR sizing. If done right, ATR sizing naturally gives IWM larger positions when stops are tight. Do ATR sizing first.

### Session Filter (BLOCKED_HOURS) for BB+KDJ
**What it is:** Suppress BB+KDJ entries during specified ET hours. Exits always fire.
**Research (1,108 trading days):**
- Block 10-11: +$3.83 IWM, +$5.31 QQQ, −$0.80 SPY — no universal improvement
- Block 15-16: −$21.92 IWM, −$21.75 QQQ, −$33.61 SPY — catastrophic
- Block 9 (open): −$14.57 IWM, −$11.00 SPY — open entries are productive
**Why parked:** No hour is universally safe to block. Small sample makes per-hour deltas unreliable.
**Code ready:** `strategy.py` has `blocked_hours` param. Wire `BLOCKED_HOURS=10,11` in config to activate.

### Gap Fade Pre-Market Features — BUILT 2026-06-16, unvalidated
**What it is:** `mm/premarket.py` + `scripts/research_premarket_gap.py` derive pre-market
fill % (how much of the overnight gap was already retraced by ~9:25 ET) and pre-market
volume ratio (today's premarket volume vs trailing 20-day avg) from Moomoo's
`extended_time=True` candle fetch (`mm/data.py::fetch_candles`), joined onto existing Gap
Fade trades. Three independent deep-research passes (Codex/ChatGPT ×2, Claude online — see
docs/deep/) converged on this as the highest-ROI next step: current `gap_pct` in
`mm/gap_fade.py` is computed purely from RTH candles, blind to 4:00-9:30am activity, and
pre-market volume/fill state is the best informational-vs-noise gap discriminator per the
research, ahead of gap size alone.
**Status:** Code built, NOT validated — could not test against live OpenD in the building
session (`moomoo_OpenD.service` was not running). `GAP_PREMARKET_FILTER_ENABLED` config knob
ships dark (false) in `mm/config.py`; not read anywhere yet — pure scaffolding.
**Enablement gate:** Run `scripts/research_premarket_gap.py` once OpenD is up, confirm
extended-hours bars actually return for the 4:00-9:30 window (Moomoo's docs say extended-hours
history "may be less than 2 years" and don't publish exact session boundaries — unverified).
If the win-rate/PF breakdown by volume-ratio and fill-% tier shows a clean split on ≥30
trades, wire the filter into `mm/gap_fade.py::run_gap_fade()` as a new pre-registered rule.

### Gap Fade Feature Deep-Dive — 2026-07-29 mechanical analysis
**What was tested:** Full backtest dataset (963 trades, 2022–2026) broken down by gap
direction, gap size, and symbol. IS=2022-2023, OOS=2024+. Goal: find deployable filters
beyond the existing premarket-fill% shadow gate.

**Key findings (OOS 2024+):**
- Overall: 963 trades, 61.7% win, PF=1.137 (IS=1.135 — consistent)
- SPY: PF=1.259 OOS — solid
- IWM: PF=1.500 OOS (IS=1.031) — large IS/OOS gap; edge there but not isolated from market structure
- QQQ: PF=0.994 OOS — dead weight; directional edge absent

**Large gap-up short filter (DEPLOYABLE):**
- Short trades where gap_pct > 1.0%: IS PF=0.939 (N=49), OOS PF=0.519 (N=58)
- Consistent degradation IS→OOS; sample size above 50-trade deployment threshold both periods
- This is a structurally bad entry: large gaps attract continuation buyers, not fade candidates
- **Action taken:** `GAP_MAX_SHORT_PCT=0.01` added to `mm/gap_fade.py` as shadow-mode knob
  (`GAP_LARGE_SHORT_FILTER_ENABLED=false` by default). Flip to `true` in `.env` once gap_fade
  accumulates enough live trades to verify the filter isn't eliminating profitable outliers.

**Large gaps overall (>1.0%):** IS PF=1.006, OOS PF=0.856 — both sides weaker in large gaps
  but the asymmetry is entirely on the short side (longs with large gaps are roughly neutral).

**What was NOT acted on:**
- QQQ performance: 1 live trade, no live split possible yet. Research suggests removing QQQ
  from gap_fade SYMBOLS, but evaluation_criteria.md gate requires live OOS data. Parked.
- IWM outperformance: 2x IS/OOS gap (1.031→1.500) suggests regime-dependent rather than robust.
  Not enough evidence to isolate IWM and short QQQ. Monitor over next 3 months.

**Code:** `scripts/backtest_gap_fade.py --all` then pandas groupby in-session analysis.

### Inferred Features — NOT BUILT, parked (2026-06-16 deep research pass)
Five ideas surfaced by the same three research reports that are plausible but premature,
speculative, or high-effort relative to current trade volume. Logged so future sessions don't
re-litigate from scratch:

| Idea | Why parked |
|---|---|
| Self-computed GEX/regime tag from Moomoo's free option-chain greeks (Σgamma×OI per strike) | Real and free, but only useful after ~100+ live trades across strategies to test whether mean-reversion outperforms in positive-GEX regimes. Premature at current trade count. |
| Futures pre-open premium (ES/NQ) as gap-fade confirmation | Research itself flags this as small-sample practitioner-only evidence (~30 cases), not peer-reviewed. Moomoo US accounts are quote-only on futures (no trading); exact ES/NQ/RTY quote-symbol strings were never verified by any of the 3 reports. |
| Order book / tick-data aggressor-side pressure during pre-market | `get_rt_ticker` exposes trade direction but is real-time-only — no historical tick endpoint exists per research. Would need weeks of live data collection before any backtest is possible. See expanded note below. |
| OpEx calendar regime tag (vol-compressed mornings, "gamma cliff" the following Monday) | Plausible and documented (Ni/Pearson/Poteshman pinning effect), but orthogonal to Gap Fade — touches ORB/BB+KDJ regime logic instead. Separate research track. |
| External vendor backfill (FirstRate Data / Databento) for pre-market history beyond Moomoo's <2yr retention | Not needed yet — test against whatever window Moomoo actually returns first. Revisit only if that window proves too short for a meaningful sample (<30 gap-fade-eligible days). |

### Tick Data Collection — time-gated, not dead

**What Moomoo exposes:** `get_rt_ticker()` returns real-time tick-level trade data per quote
subscription: timestamp, price, volume, direction (buy/sell), and whether it was aggressor-side.
This is richer than candles — you can see intra-bar pressure, large-lot clustering, and tape
absorption patterns that 5-minute OHLCV completely hides.

**The blocker:** No historical tick endpoint exists in the Moomoo API. You cannot backfill.
Every other data source in this project (candles, VIX, premarket volume) has a history endpoint.
Ticks do not. This means zero historical sample to research against until you've collected it live.

**Why it's interesting anyway:**
- Stop accuracy: our backtest assumes stops are only checked at 5-min bar closes. A tick stream
  would let you detect intra-bar stop touches and make backtests more realistic.
- Entry confirmation: a BB touch with heavy sell-aggressor ticks is a weaker mean-reversion
  signal than a BB touch with buy-aggressor absorption. Candles can't see this.
- ORB breakout quality: a breakout bar with 80% buy-aggressor ticks is more convincing than one
  with mixed tape. Haiku could classify tape character cheaply on each setup.

**How to build it when ready:**

1. New script `scripts/collect_ticks.py` — subscribes to `get_rt_ticker()` during market hours
   (9:30–16:00 ET), appends each tick to `logs/ticks/US_SPY_YYYY-MM-DD.jsonl` (one file per
   symbol per day). Runs alongside the paper runner, separate process.

2. Schema per record:
   ```json
   {"ts": "2026-09-15T09:31:04.123", "price": 551.23, "volume": 300,
    "direction": "buy", "type": "auto_match", "sequence": 12345678}
   ```

3. After ~3 months of collection (≈60 trading days), run `scripts/mine_ticks.py`:
   - For each bb_kdj signal bar: compute buy_aggressor_pct in the 5 min before entry
   - Bucket by aggressor% (0-40% / 40-60% / 60-100%) and compare PF + win%
   - Gate: OOS PF ≥ 1.2 with ≥ 50 trades per bucket before deploying

4. If edge found: add `tick_pressure` field to signal dict in `mm/evals._eval_bb_kdj()`,
   gate on `buy_aggressor_pct > threshold` before entry.

**Revisit when:** paper runner has been stable for 3+ months and disk space allows ~50MB/day
of tick JSONL. Not hard to build — purely time-gated on collection.

### ORB Short Live Verification — kill switch REMOVED 2026-06-17, awaiting first live fill
**Status (2026-06-17):** `STOP_SHORTS.txt` deleted from the VPS. ORB shorts can now fire live in
SIMULATE the next time conditions line up. No live short has filled yet as of removal.
**History:** The file existed from 2026-06-05 to 2026-06-17, blocking every qualifying ORB short
setup at runtime (`mm/evals.py`, `signal_skip` reason `orb_shorts_kill_switch`). On 2026-06-17
alone, before removal, SPY/QQQ logged 99/49 such blocked-setup polling ticks (not 99/49 distinct
trades — the same setup persists bar-to-bar while it's live). The original reason the file was
created is still unknown — the "Moomoo blocks shorting on this account" theory was raised and
disproven via `OpenSecTradeContext.acctradinginfo_query()` (2026-06-16): `max_sell_short: 5705.0`
for US.IWM, real short-sell capacity available. SIMULATE account is also a MARGIN account, which
is the actual mechanical requirement for shorting — confirmed via `get_acc_list()`. So nothing
account-side ever justified the block; it was switched on for an unrecorded reason and left in
place out of caution.
**Why removed now:** User wants a real shorting proof-of-concept on paper trades before
considering shorting in any future live/real-money context — that requires actual live fills,
which the kill switch was preventing entirely.
**Downstream effect:** Gap Fade's short side (gap up → short) was also gated behind ORB short
verification — that gate can now be pursued too, though it's a separate, not-yet-wired-into-live
module (`mm/gap_fade.py`, research-only).
**To revisit:** Watch for the first live ORB short fill (`position_open` with `direction: short`
in the symbol's JSONL log). Treat it with the same scrutiny as any other strategy's gate sample —
see `docs/evaluation_criteria.md` for sample-size discipline before drawing conclusions.

### Push Architecture (WebSocket exits)
**What it is:** Replace 60s polling with `StockQuoteHandlerBase` WebSocket. Intra-bar exits instead of end-of-bar.
**Gate:** Live trades show consistent exit slippage > 0.1% per trade. Current `slippage_bps` field is 0.0 in SIMULATE — need real fill data before this is justified.
**Revisit when:** slippage_bps readings from live fills show the 60s poll costs real edge.

### paper.py Refactor (Split into Smaller Modules) — COMPLETE 2026-06-16

**What was done:** mm/paper.py (1,200 lines / ~45 defs) split into 4 new modules + mm/risk.py gains.
6 commits on master, 173/173 tests pass, cert-diffed (byte-identical replay before/after).

**Final layout:**
| Module | Contents |
|---|---|
| `mm/clock.py` | now(), now_et(), today(), sleep(), is_market_open(), seconds_until_open() |
| `mm/events.py` | PaperEventLog, PaperPosition, position/ORB file I/O |
| `mm/execution.py` | _place_buy/sell/short/cover, _confirm_fill, _execute_entry/exit, _reconcile_positions |
| `mm/evals.py` | _eval_bb_kdj, _eval_vwap, _eval_vwap_pb, _eval_orb, _entry_attempted |
| `mm/risk.py` (gains) | _qty, _position_cap, _slot_dollars (sizing helpers; avoids evals→paper cycle) |
| `mm/paper.py` (trimmed) | loop + _latest_closed_candles + run_multi + back-compat re-exports (~340 lines) |

**Key architectural invariants discovered:**
- Use `from . import config as _config` + `_config.cfg.*` at runtime in any module replay might
  reload — `from .config import cfg` goes stale after `_reload_paper` replaces mm.config.cfg.
- `_slot_dollars` is a float; tests must set `mm.risk._slot_dollars` not `paper._slot_dollars`.
- `_reload_paper` must reload `mm.evals` so `_entry_attempted` resets between tests.
- `TestMarketHoursGuard` must use `monkeypatch.setattr(mm.clock, ...)` not direct assignment.

**Deploy:** `./deploy.sh` after market close. Refactor is behavior-identical (cert-diffed).

---

### From docs/codex-grand-audit-2026-06-19.md — external review, parked ideas

An external AI review (`docs/codex-grand-audit-2026-06-19.md`, kept as a historical record —
not a living doc, don't edit it) raised several ideas. The headline engineering claim was
spot-checked before trusting the rest: verified via `strace` that `import moomoo` does write
a log file outside the workspace (`~/.com.moomoo.OpenD/Log/py_YYYY_MM_DD.log`, hardcoded in
the vendor SDK's `ft_logger.py`, fired at module level). The audit's specific symptom claim
("pytest can fail during collection") did NOT reproduce here — 210/210 tests pass cleanly,
because `$HOME` happens to be writable on this machine. Root cause real, failure mode
environment-dependent. The file/line-count stats in the audit were independently verified
accurate, so the rest of its groundwork is reasonably trustworthy — but its strategic opinions
below are an outside impression, not validated by data, and don't override the actual decision
mechanism (`docs/evaluation_criteria.md`'s pre-registered gates).

#### Test Hermeticity — moomoo import writes logs outside the workspace
**What it is:** `mm/connection.py`, `mm/data.py`, `mm/execution.py` import `moomoo` at module
level, which triggers the vendor SDK's `logger = FTLog()` side effect (see above) — a write to
`$HOME`, not the repo workspace. Harmless today (verified), but would crash any pytest
collection in a sandbox/CI/container without a writable `$HOME`. **Action if revisited:**
redirect `$HOME` (or monkeypatch the log path) in `tests/conftest.py` before any test imports
an `mm` module that pulls in `moomoo`, making the suite hermetic regardless of environment.

#### Machine-Readable Project State Snapshot
**What it is:** a generated `scripts/snapshot.py` producing a small `STATE.json` — active
strategies, research-only strategies, current gate progress, latest test count, latest audit
date, highest-risk modules — to counter "too many truth surfaces" (truth is currently spread
across code, `.env`, `PROJECT_MAP.md`, `strategy_graveyard.md`, `evaluation_criteria.md`).
Cheap, low-risk, no live-behavior change. **Parked because:** not urgent — the docs are still
navigable by hand. **Revisit when:** doc-reconciliation starts costing real time, or a future
session gets confused by stale cross-doc numbers again.

#### Portfolio Governor (entry-time constraints)
**What it is:** a runtime layer enforcing same-direction symbol clustering limits, max
concurrent exposure, and cross-strategy overlap risk AT THE POINT OF ENTRY, not just
after-the-fact via `scripts/analyze_portfolio.py`. **Parked because:** premature while
strategies are still sample-starved against their own gates (12 combined trades as of
2026-06-18) — building governance for a portfolio that hasn't proven its individual pieces
work yet solves a problem with no evidence behind it. **Revisit when:** at least one strategy
clears its gate and live overlap actually shows up as a real cost in the data.

#### Strategy Promotion Pipeline (formalized)
**What it is:** an explicit staged path for new strategies — research → replay → shadow
logging → regime attribution → overlap scoring → promotion to live paper — instead of the
current implicit version (which is already working, e.g. Gap Fade's shadow-mode wiring this
session). **Parked because:** the implicit version works fine at the current scale (4
strategies); formalizing it into tooling is process overhead before a second/third strategy
is actually queued up needing it. **Revisit when:** ≥2 new strategies are in the research
pipeline simultaneously.

#### Discrepancy-Focused "Truth Dashboard"
**What it is:** a dashboard view centered on replay-vs-live divergence, stale-config usage,
broker/local mismatch events, and execution anomalies — distinct from the existing PnL-first
dashboards (`scripts/dashboard.py`, `scripts/web_dashboard.py`). **Parked because:** the
underlying checks already exist as separate scripts (`scripts/replay_vs_live.py`,
`scripts/diagnose_logs.py`) — a unified view is a nice-to-have UI consolidation, not a missing
capability. **Revisit when:** those scripts are being run often enough that switching between
them is actually annoying.

#### Deeper Strategy-Only Audit Checklist
**What it is:** a future pass examining regime concentration (is the edge concentrated in
specific vol/trend regimes), symbol dependency (genuine SPY/QQQ/IWM diversification vs
correlated triplication), live-vs-replay degradation by strategy family, PnL distribution
shape (consistent base hits vs outlier-carried), and cross-strategy overlap cost. **Parked
because:** needs a much bigger live sample than exists today (12 trades total) to produce
anything but noise. **Revisit when:** any individual strategy gate trips, or a few months of
live data accumulate either way.

#### Large Mixed-Purpose File Refactor Candidates
**What it is:** `scripts/web_dashboard.py` (967 lines), `scripts/analyze_trades.py` (628),
`mm/research.py` (618), `mm/evals.py` (576) flagged as broad enough in role to be "heavy
context nodes" for both human and AI readers — not buggy, just large+mixed-purpose. **Parked
because:** splitting these now is a speculative refactor without a concrete pain point (CLAUDE.md
explicitly warns against premature abstraction). **Revisit when:** actually editing one of these
becomes noticeably harder in practice — not on line-count alone.

#### External Audit's Strategy-Hierarchy Impression (informational only)
The audit's subjective ranking, captured for reference, NOT a decision: **ORB** = strongest
backbone candidate (simple, falsifiable, but execution-sensitive); **VWAP PB** = useful
selective complement (narrower, symbol-selection-sensitive); **BB+KDJ** = the most
epistemically fragile of the active strategies (most parameterized, most room for subtle
signal contamination — the KDJ day-boundary bug is cited as reinforcing this concern, though
that bug is already found and fixed); **Gap Fade** = the most promising non-redundant next
promotion candidate (structurally distinct thesis, not a decorated duplicate of what's already
live). This is an outside opinion to weigh, not a gate — the actual promotion/suspension
decisions still run entirely through `docs/evaluation_criteria.md`.

---

## Decided Against (with data/reasoning)

### ORB Afternoon Entry Cutoff (ORB_CUTOFF_HOUR)
**What it was:** Block ORB entries after 12:00 ET. Motivated by 2026 YTD replay through the
real runner: hours 12+ = 75 trades, −$93, PF 0.23–0.71, 76% TIME_STOP deaths, while hours
9–11 = 191 trades, +$107. A noon cutoff would have flipped YTD ORB from +$14 to +$107.
**Why no (2026-06-12):** Fails OOS cross-validation. 2022–2025 (backtest engine, same
symbols/windows): hours 12+ = 698 trades, +$64.68, PF 1.16 — profitable, barely below
mornings (PF 1.22). Hours 13–14 actually outperform (PF 1.32/1.46). The 2026 afternoon
bleed is this year's regime or 75-trade variance, not structure.
**If the live ORB gate trips:** slice live trades by entry hour first (scripts/
analyze_orb_hours.py logs/) — if live matches the 2026 replay pattern rather than the
2022–2025 pattern, the cutoff becomes a legitimate pre-registered amendment candidate.

### VIX 3-Tier Strategy Switching
**What it was:** ORB when VIX<15, VWAP PB when VIX 15-28, BB+KDJ when VIX>30.
**Why no:** Unvalidated assumption. VIX filter backtest showed VIX is not predictive. Regime-strategy mapping needs per-cell backtesting before trusting.

### Symbol Scaling (DIA / TLT / XLK / XLF)
**Why no:** Every new symbol needs full backtest + OOS cycle. SPY/QQQ/IWM already cover the liquid ETF space. Add only with a specific edge hypothesis.

### Dynamic ATR Trailing Stops
**Why no:** BB-middle is a clean, interpretable target with proven OOS edge. Trailing stop adds a parameter and potential for premature exit. Needs isolated backtest first.

### Economic Event Gating (STOP_FOR_NEWS.txt)
**Why no:** Over-engineering. STOP_TRADING.txt handles manual pauses. 1-min ATR spike filter requires a separate data feed. Cost > benefit at this stage.

---

## Config Knobs Researched and Settled

| Knob | Optimal | Tested Range | Why |
|------|---------|-------------|-----|
| ATR_STOP_MULT | 1.0 | 0.5–2.0 | Best PF + 56% walk-forward consistency |
| MIN_SIGNAL_SCORE | 2 | 0–3 | Flips exit split to target-dominant |
| KDJ_WINDOW_BARS | 3 | 0–5 | ~6.7-7.7× signals on IWM/QQQ vs w=0; SPY excluded or kept at 0 (corrected 2026-06-18 after a day-boundary leak bug fix — see "KDJ Day-Boundary Signal Leak" above; was documented as "10×" on the buggy signal set). 2026 YTD check: SPY w=3 (18t, 38.9%, -$10.46) vs w=0 (3t, 33.3%, -$1.67) — both negative in current regime; SPY bb_kdj broken in 2026 regardless of window. IWM 2024+ OOS: w=3 (119t, 45.4%, +$13.98, +5.4 bps) vs w=0 (18t, 72.2%, +$9.97, +24.1 bps) — w=0 dramatically better per-trade. KDJ_WINDOW_OVERRIDES=US.SPY:0,US.IWM:0 deployed 2026-07-21. |
| EXIT_ON_KDJ_DEATH | false | — | Re-enabling flips SPY PnL from +$2.34 → −$0.83 |
| ORB_TARGET_MULT | 1.5 global | 1.0–3.0 | Global default 1.5. Per-symbol OOS (2024+) sweep at vol=1.5: QQQ 2.0× PF 1.309→1.352 (+4.3%), IWM 1.0× PF 1.210→1.270 (+6%), SPY flat (marginal gain at 2.5×). Per-symbol overrides deployed 2026-07-12 via ORB_TARGET_MULT_OVERRIDES. Full exit-reason sweep 2026-07-21 confirmed: high TIME_STOP rate is expected (58% QQQ, 51% SPY, 65% IWM) — TIME_STOP exits are net positive in backtest; live -$14 on TIME_STOPs is 34-trade noise. |
| ORB_VOL_MULT | 1.5 global | 0.0–2.0 | OOS (2024+): QQQ PF 1.162→1.309 (+13%), SPY 1.122→1.156. Full exit-reason sweep 2026-07-21: SPY 2.0× is clearly better (PF 1.156→1.300, PnL $65→$83 on 490 vs 570 trades). QQQ 2.0× loses total PnL ($182→$147 at 468 trades) — stays at 1.5. IWM 2.0× flat ($40→$31) — stays at 1.5. ORB_VOL_MULT_OVERRIDES=US.SPY:2.0 deployed 2026-07-21. |
| ORB TIME_STOP exits | exits are correct | — | 2026-07-25 post-exit analysis (`--analyze-exits`, OOS 2024+, N=880 TIME_STOP trades across SPY/QQQ/IWM): only 2–6% of TIME_STOP exits would have hit target if held longer (IWM 2%, QQQ 4%, SPY 6%). 57–65% of TIME_STOP trades continued moving against entry after exit. Avg max favorable move after exit: +0.01–0.06%. Conclusion: the 15:45 cutoff is not the problem — entries are wrong, not exits too early. |
| ORB entry timing | no filter | — | 2026-07-25 entry-lag analysis (`--entry-timing`, OOS 2024+): entries fired <15min after OR close have worst PF (IWM 0.727, SPY 0.648, QQQ 1.442). The 15–45min window has best PF per bucket (IWM 30-45min: PF 2.636, SPY 15-30min: PF 1.494). The >45min bucket holds 70–75% of all trades at marginal PF (1.051–1.315) with 55–72% TIME_STOP rate. Parked: early-entry filter would require a new config knob and re-validation; the PF difference may not survive a clean OOS split given the bucket imbalance. **2026-07-29 live fill quality check (N=49 trades, gate triggered at PF=0.76/39 trades):** Execution clean — entry slippage -2.5 bps mean (favorable), max 9.5 bps, candle age normal (one-bar lag ~310s). Structural timing problem confirmed live: entries >180min post-open (after 12:30 PM) = PF=0.49, 88% TIME_STOP rate, 25/49 trades. Entries 30-60min post-open = PF=3.28 (N=4, tiny). Live 2026 consistently shows afternoon ORB entries are drag — consistent with graveyard 2026-06-12 note (-$93/75 afternoon trades). `ORB_LATEST_ENTRY=12:30` exists in code (evals.py:682), commented out in .env. Still parked: IS 2022-25 showed afternoon entries profitable (PF 1.16), live contradicts. Need 50+ live trades per timing bucket before deploying cutoff. |
| ORB_ENTRY_MIN_CONFIDENCE | 0.50 | 0.65→0.50 | 2026-07-25 offline calibration (`scripts/calibrate_orb_scorer.py`, OOS 2024+, N=1,654 trades across SPY/QQQ/IWM): confidence distribution min=0.32 median=0.58 max=0.72 — model almost never scores above 0.65 (22/1654 = 1.3%). At 0.65 gate the scorer would block 98.7% of entries. Bucket analysis: 0.3–0.5 (N=722, PF 1.119), 0.5–0.65 (N=910, PF 1.224), 0.65–0.8 (N=22, PF 10.269 — too few trades). Threshold 0.50 maximizes PF with ≥50 trades: above=932 trades PF 1.274, below=722 trades PF 1.119. Lowered from 0.65 → 0.50 2026-07-25. Results cached in logs/orb_calibration.jsonl. **2026-07-26 re-calibration attempted with claude-sonnet-5 but aborted:** (1) Haiku calibration data is incompatible — scores not on same scale as Sonnet; Haiku cache backed up to logs/orb_calibration_haiku_backup.jsonl. (2) ThinkingBlock bug found and fixed: `_extract_text()` added to `mm/morning_regime.py` — Sonnet returns thinking blocks before text blocks, `content[0].text` was raising AttributeError on every call silently. Bug was affecting live regime gate and ORB scorer since ANTHROPIC_MODEL switched to sonnet. Fix deployed 2026-07-26. (3) Re-calibration parked: requires ~1000 Sonnet API calls (~$3–5). Run `python scripts/calibrate_orb_scorer.py --start 2025-01-01 --model sonnet --quiet` when ready. Current threshold 0.50 is in shadow mode only — scorer logs would_skip but never blocks. **(4) 2026-07-29 in-session mechanical analysis (N=2,924 backtest trades 2022–2026, no API calls):** Edge drivers are mechanical, not LLM-discriminable. OR range <0.5% gives PF=1.256 vs baseline 1.216. Entry ≤120min post-OR gives PF=1.303. Combined gives PF=1.394 but 2024 OOS=0.988 (same IS/OOS inconsistency that killed timing filter in graveyard). Key finding: scorer features (VIX, regime, direction) are not the features driving the actual edge (OR range size, entry timing). Sonnet re-calibration unlikely to find a clean gate threshold. Scorer stays shadow-mode; accumulate live trades per timing/range bucket before deploying any mechanical filter. OR range filter finding is new — not previously tested. |
| bb_kdj peer divergence filter (cross-asset) | not deployed — hypothesis disproved | — | 2026-07-26 `scripts/mine_cross_asset.py` (IS=2022-2023, OOS=2024+, 260K bars, SPY/QQQ/IWM). Categorized every bb_kdj signal bar by what peers were doing: **isolated** (peers above bb_middle), **confirmed** (peers also at bb_lower), **neutral** (peers between bands). Hypothesis was isolated=strongest. Result: isolated IS PF=0.924 → OOS PF=0.967 (consistently worst, below 1). Confirmed IS PF=1.133 → OOS PF=1.173 (most consistent, modest edge). Neutral IS PF=0.960 → OOS PF=1.477 (strong OOS but IS/OOS inconsistency is a red flag — likely 2022 bear market regime artifact; IWM neutral OOS=1.754 driving it). No clean deployment: isolated clearly harmful, confirmed doesn't clear 1.2, neutral IS/OOS gap unexplained. Script kept at `scripts/mine_cross_asset.py`. **2026-07-29 re-run with IS=2023-only (`--is-start 2023-01-01`):** Bear-market hypothesis partially confirmed. Isolated: IS 0.924→1.057, OOS 0.967→1.937 — 2022 was dragging IS down, but IS→OOS gap now nearly 2x (suspicious, regime-dependent). Confirmed: IS 1.133→1.213, OOS 1.173→1.173 — most stable across all splits, still doesn't clear 1.2. Neutral: IS 0.960→1.066, OOS 1.477→0.936 — prior high OOS was entirely 2022 artifact, now confirmed dead. Final verdict: still no deployment. Isolated is regime-dependent (bear=momentum, bull=mean-reverting), not a robust gate. Confirmed is most consistent but sub-1.2. |
| REGIME_GATE_ENABLED (bb_kdj) | true, SKIP=trending_up,trending_down | orig: choppy,risk_off → flipped 2026-07-26 | 2026-07-26 batch validation (`scripts/validate_regime.py`, OOS 2024+, N=618 trading days, 356 bb_kdj trades): label distribution: neutral=315d, trending_up=143d, choppy=105d, risk_off=54d, trending_down=1d. Per-label avg PF: trending_up=0.513 (worst — trend continuation kills mean reversion), risk_off=0.743, neutral=0.880, choppy=0.928 (best — ranging markets are where bb_kdj edge lives). Original skip labels (choppy,risk_off) were backwards. **Flipped to REGIME_SKIP_LABELS=trending_up,trending_down 2026-07-26.** ~23% of days gated out. Note: per-day PF noisy (avg 0.6 trades/day, N=32 skip-label days with usable PF) — directional finding is solid but statistical confidence is low; accumulate live data. Validation saves logs/regime_YYYY-MM-DD.json for all 618 classified dates; re-run with `--from-cache` to avoid re-scoring. |
| VWAP_PB_MAX_CROSSES | 1 | 0–3 | Critical no-chop filter for VWAP PB edge |
| Timeframe | K_5M | 5M/15M/60M | K_15M produces MORE stops, not fewer |
| Regime filter | ADX < 25 | 7 alternatives | Confirmed best vs BB width, volume variants |
| ORB window IWM | 30-min | 15/30-min | 15-min PF=1.017 → 30-min PF=1.217 |
| ORB_SHORT_SYMBOLS | US.SPY | all vs per-symbol | Live data 2026-06-17→2026-07-09: QQQ shorts 0% win/24 trades (−$80), IWM shorts 0% win/12 trades (−$40), SPY shorts 100% win/20 trades (+$36). QQQ+IWM disabled. |
| mm/vwap_strategy.py + mm/vwap_signals.py | Candidate for removal | Still imported by mm/paper.py and mm/evals.py for the deprecated 'vwap' strategy path. No live STRATEGIES entry uses them. Safe to delete once the import sites are cleaned up. |

## Filter Tightness Review — 2026-07-31

Flags raised after a 2-day audit (Jul 30–31) showed only 3 trades fired and several
active filters visibly blocking. This section documents which filters might be over-tight
and what evidence would justify loosening each. Nothing changed without data.

### GAP_VIX_MAX for SPY/QQQ — possibly too tight at 20

**Current:** `GAP_VIX_MAX_OVERRIDES=US.SPY:20,US.QQQ:20`. Jul 30 VIX=20.66 blocked both symbols.
**Concern:** The H2 backtest showed VIX 20-25 hurts gap fades on SPY/QQQ, but the threshold
boundary at exactly 20 is arbitrary. VIX=20.5 and VIX=24 are very different environments.
**IWM has no cap** (confirmed positive at all VIX bands in research) — so the asymmetry is intentional.
**Gate to loosen:** Re-run `scripts/backtest_gap_fade.py --all` with SPY/QQQ split at VIX 20/21/22
and check OOS PF at each boundary. If VIX 20-21 band shows OOS PF ≥ 0.9, bump to 21. Current
data too thin to justify moving without a backtest check first (2 live gap-fade longs only).

### ORB scorer (orb_claude_score) at 0.50 — blocking real trades without validation

**RESOLVED 2026-08-14:** `ORB_ENTRY_MIN_CONFIDENCE=0.0` — scorer gate disabled. Features (VIX,
regime, direction) don't discriminate outcomes; mechanical analysis confirmed OR range + entry timing
are the real edge drivers. Scorer still logs confidence for research but never blocks.

**Prior state:** `ORB_ENTRY_MIN_CONFIDENCE=0.50`. Was supposed to be "shadow mode never blocks", but
Sonnet returns scores below 0.50 on some setups — 228 blocks since Jun 10, 89 blocks in just
Jul 30–31. No outcome data on what those blocked setups would have done.
**Concern:** The Haiku calibration that set 0.50 is useless (Haiku flat 0.72 on everything).
The Sonnet re-calibration was parked at ~$3–5 cost. We're blocking real setups against a
threshold we haven't validated with the live model.
**Gate to loosen:** Either run the Sonnet re-calibration (`calibrate_orb_scorer.py --model sonnet
--quiet`, ~$3) and set the threshold from real data, or temporarily set `ORB_ENTRY_MIN_CONFIDENCE=0.0`
to stop blocking until calibration is done. The scorer can stay live in shadow/log-only mode.

### bb_kdj trade frequency — 3 trades in 7+ weeks

**Current:** bb_kdj strict (ADX<25 + bonus≥2 + MIN_SIGNAL_SCORE=2 + KDJ window + regime gate).
**Observation:** bb_kdj_loose (same signal, no bonus/score gate) fired 5 trades in the same window
at PF=1.50. The strict variant at PF=0.97 and 3 trades suggests the bonus/score gate is filtering
out more edge than it's protecting. This isn't a new filter to relax — it's a flag that bb_kdj_loose
may be the better strategy at current sample sizes.
**Gate:** At 20+ bb_kdj_loose trades, compare PF and win% vs bb_kdj strict. If loose consistently
outperforms, consider retiring the strict gating or merging the strategies.

### ORB vol filter (ORB_VOL_MULT) — 88% block rate but ORB is still PF=0.78

**Current:** SPY vol_mult=2.0, others=1.5. 15,722 skips since Jun 10.
**Observation:** The filter was backtest-optimized (OOS: SPY 2.0× PF 1.156→1.300). But ORB is
live PF=0.78 at 41 trades, dragging the whole portfolio. Heavy filtering hasn't fixed the problem.
The late-entry structural issue (afternoon entries PF=0.49) is the real drag, not volume.
**Note:** Loosening vol_mult is NOT the right call — it would add more low-quality setups on top
of an already-losing strategy. The note is here to flag that 88% block rate + PF=0.78 is not a
contradiction: the strategy has structural problems that vol filtering can't fix. The right lever
is `ORB_LATEST_ENTRY=12:30` — **activated 2026-08-14** (executive decision: live data consistently
shows afternoon entries are drag; backtest IS/OOS inconsistency noted but overruled).

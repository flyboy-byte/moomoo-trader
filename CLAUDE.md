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
- docs/research-reset.md    — **START HERE (as of 2026-08-29).** The current top-priority plan:
  measurement rebuild (Goal A) then universe expansion (Goal B). Contains the live-verified API
  scoping numbers (history_kl_quota=100 hard cap, engine throughput, history depth) — do not
  re-derive them. Supersedes Route 2b Phases 2-6 as the priority.
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
  mm/backtest.py       — run_backtest(), walk_forward(), print_summary(), profit_factor() (CANONICAL PF —
                         never reimplement it, see tests/test_metric_consistency.py)
  mm/costs.py          — transaction cost model: round_trip_bps(), net_pnl(), net_bps() (added 2026-08-29,
                         docs/research-reset.md Goal A1). Self-contained constants, no cfg import — costs are
                         not a strategy knob and must not become tunable-until-profitable.
  mm/stats.py          — bootstrap CIs: bootstrap_pf_ci(), bootstrap_mean_ci(), prob_positive(), summarize().
                         Re-exports mm.backtest.profit_factor; does NOT define its own.
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
- **TOP PRIORITY as of 2026-08-29: docs/research-reset.md.** The 2026-08-29 audit found the
  portfolio's measured edge (+1.31 bps weighted across 106 live trades) sits *inside* the project's
  own 1-3 bps cost band, on frictionless fills — i.e. no demonstrated edge, and the reporting layer
  (per-share PnL, no benchmark, no CIs, no cost model) can't show it. Goal A rebuilds measurement;
  Goal B expands the replay universe (97 free API quota slots) so strategies can reach significance
  in days instead of the ~26 weeks the current 3-symbol/1.8-trades-a-day design implies.
  Route 2b Phases 2-6 are PARKED behind this, not cancelled (Phase 1 keeps logging for free).
- Six live strategies: bb_kdj, bb_kdj_loose (live 2026-07-04, research lane), orb (SPY shorts only
  as of 2026-07-09 — QQQ+IWM shorts disabled after 0% win rate on 36 trades), vwap_pb,
  gap_fade (live 2026-07-12).
- Accumulate live data — most "what does the data say" questions need more samples.
  See docs/evaluation_criteria.md for the actual pre-registered sample-size gates per strategy.
- docs/expand_plan.md is the original 5-option roadmap — all 5 options are done or explored.
  Next phase is in docs/expansions/ — start at docs/expansions/FRAMEWORK.md (it has an explicit
  "Current status" section — read that first, it's the authoritative "where are we").
  Two primary routes: Route 1 (data mining, scripts/mine_*.py, COMPLETE) and
  Route 2 (LLM regime gate, mm/morning_regime.py + mm/evals.py, live and gating).
  Route 2b (docs/expansions/route-2b-volatility-engine.md, started 2026-08-25) is a 6-phase
  extension — deterministic volatility term-structure engine (mm/vol_engine.py, shadow-only,
  Phase 1+3 done) feeding richer context into the regime gate, eventually a bounded
  ALLOW/TIGHTEN/BLOCK policy. Phase 2 needs a few sessions of real logs/vol_state.jsonl data
  before it can start — don't skip ahead to it on synthetic data.
- Gap Fade (mm/gap_fade.py) is LIVE as of 2026-07-12. Fires once per day at 9:35 ET.
  GAP_LARGE_SHORT_FILTER_ENABLED=true on VPS (blocks gap-up shorts >1.0% — IS/OOS confirmed bad edge).
  GAP_PREMARKET_FILTER_ENABLED=false (shadow mode only, logs would_filter_skip).
  Knobs are self-contained module constants in mm/gap_fade.py (file deliberately doesn't import cfg).
- docs/codex-ai-size.md / codex-ai-size-remedies.md — repo doc-hierarchy analysis, explicitly
  parked for a future dedicated session, not in progress.

Do not ask before every small change. Make reasonable implementation decisions.
After changes, explain what was built, how to run it, and what remains.

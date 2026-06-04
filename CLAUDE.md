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

Current build state (as of 2026-06-04):
All core infrastructure complete. Multi-strategy paper runner live on VPS (bb_kdj + orb + vwap_pb on SPY/QQQ/IWM).
First live trades fired 2026-06-04: SPY ORB +$2.92 (TARGET), QQQ ORB +$2.52 (TIME_STOP). Signal engines validated.
See docs/ARCHITECTURE.md for system map. Run ./scripts/verify.sh for one-command session health check.

Package layout:
  mm/config.py         — .env loading, cfg singleton (all config lives here)
  mm/logger.py         — file + console logging (TimedRotatingFileHandler, midnight rotation, 30-day retention)
  mm/connection.py     — quote_context() context manager for OpenD
  mm/health.py         — run_health_check() (socket + quote ping)
  mm/data.py           — fetch_candles(), fetch_and_save()
  mm/indicators.py     — bollinger_bands(), atr(), kdj(), rsi(), adx(), vwap(), ema(), add_all()
  mm/signals.py        — score_df(), snapshot() — BB+KDJ signal scoring
  mm/strategy.py       — compute_signals(), run_signals(), Trade, Signal
  mm/backtest.py       — run_backtest(), walk_forward(), print_summary()
  mm/research.py       — compare_variants(), sweep_parameters(), analyze_stop_exits(), sweep_signal_filter()
  mm/risk.py           — trading_allowed(), calc_qty(), DailyTracker
  mm/paper.py          — multi-strategy paper trading loop (bb_kdj, orb, vwap_pb, vwap)
  mm/orb_strategy.py   — ORB backtest engine, _build_opening_ranges() (supports per-symbol orb_minutes)
  mm/vwap_pullback.py  — VWAP Pullback (flush-and-reclaim) backtest engine
  mm/vwap_strategy.py  — VWAP crossover strategy (deprecated, PF≈1.0)
  mm/vwap_signals.py   — VWAP signal scoring (used by vwap crossover strategy)
  mm/ema_momentum.py   — EMA5/EMA20 momentum breakout backtest engine (research only, not deployed)
  mm/notifications.py  — Discord webhook (no-ops if URL not set)

Scripts (all run from project root with venv active):
  python scripts/health_check.py
  python scripts/fetch_candles.py [--symbol US.SPY] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--ktype K_5M]
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
  python scripts/dashboard.py                                                  # live TUI dashboard
  python scripts/dashboard.py --date YYYY-MM-DD                               # review past session
  python scripts/diagnose_logs.py [--date YYYY-MM-DD] [--all] [--symbol US.SPY]
  ./scripts/verify.sh [--date YYYY-MM-DD] [--no-sync]                         # pytest + sync + diagnose + compare
  ./start.sh                                                                   # start OpenD + paper runner
  ./stop.sh                                                                    # stop paper runner
  ./sync_logs.sh                                                               # rsync VPS logs → local logs/

Safety rules (never violate):
- TRD_ENV=SIMULATE always. Never change to REAL.
- LIVE_TRADING_ENABLED=false always. Code checks this before placing any order.
- STOP_TRADING.txt in project root pauses the paper runner without killing the process.
- live_trade_runner.py.DISABLED is intentionally never executed.
- Do not store secrets in code.

Strategy (BB + KDJ mean reversion, 5-min candles):
- Entry: close <= BB lower(20,2) AND KDJ(9,3) golden cross on the same bar
- Exit target: close >= BB middle
- Exit stop: close < entry_price - ATR_STOP_MULT * ATR(14)
- KDJ death cross exit is DISABLED by default (EXIT_ON_KDJ_DEATH=false in .env)
- All signals use closed candles only

Backtest findings — do not re-derive, but treat as directional not definitive.
Sample sizes are small (60–77 trades over 3.5 years). Walk-forward validation adds
out-of-sample character but does not constitute live proof. All findings survive
until forward paper testing shows otherwise:
1. Removing KDJ death cross exit: flips PnL from -$0.83 to +$2.34 over 2022-2025 SPY 5-min.
   The death cross was cutting mean-reversion trades before they recovered to BB middle.
2. ATR stop multiplier: 1.0 is optimal. Best profit factor (1.474) and tied-best walk-forward
   consistency (22/39=56%) confirmed on 77 trades across SPY+QQQ+IWM. Not a small-sample artifact.
3. Entry tolerance (allowing close slightly above BB lower): completely inert. Zero new signals.
4. Stop recovery: 47% of stop-loss exits recovered within 48 bars (premature), but the stops that held
   prevented large losses (worst case $8.25 gap to BB middle).
5. Multi-symbol validation (SPY+QQQ+IWM, 5-min, 2022-2025, 77 trades total):
   - SPY:  29 trades, 41.4% win, +$2.34 total PnL
   - QQQ:  21 trades, 42.9% win, +$4.21 total PnL
   - IWM:  27 trades, 59.3% win, +$8.95 total PnL  ← significantly better
   - Combined: 77 trades, 48.1% win, +$15.49 total PnL, exit split: 52% stop / 48% target
   - Strategy edge is consistent across all three symbols. IWM outperforms — worth investigating why.
6. Signal confluence engine (bonus signals beyond BB+KDJ core, SPY+QQQ+IWM, 2022-2025):
   Bonus signals: rsi_oversold (RSI<35), ranging (ADX<25), volume_spike (vol>1.5× MA).
   Core BB+KDJ always required. MIN_SIGNAL_SCORE=2 is optimal:
   - Score 0 (BB+KDJ only): 77 trades, 48.1% win, +$15.49, PF=1.474, 40stop/37tgt
   - Score 1 (need 1 bonus): 74 trades, 50.0% win, +$17.56, PF=1.573, 37stop/37tgt
   - Score 2 (need 2 bonus): 60 trades, 51.7% win, +$19.12, PF=1.843, 29stop/31tgt ← BEST
   - Score 3 (all 3 bonus):  11 trades — too few
   Score 2 flips exit split to target-dominant. Current default: MIN_SIGNAL_SCORE=2.
7. Timeframe comparison (SPY+QQQ+IWM, 2022-2025):
   - K_5M:  77 trades, 48.1% win, +$15.49, 52% stops — BEST. Use this.
   - K_15M: 27 trades, 40.7% win, +$5.61,  59% stops — worse on all metrics, more stops not fewer
   - K_60M: 5 trades, 80.0% win, +$16.76, 20% stops — too sparse (SPY=0 signals), statistically meaningless
   - Conclusion: K_5M is the right timeframe. Hypothesis that longer TF reduces stop-out noise is FALSE.

Historical data on disk:
  logs/US_SPY_K_5M_combined.csv    — 86,100 candles, 2022-01-03 to 2026-06-03 (primary backtest file)
  logs/US_QQQ_K_5M_combined.csv    — 86,100 candles, 2022-01-03 to 2026-06-03
  logs/US_IWM_K_5M_combined.csv    — 86,100 candles, 2022-01-03 to 2026-06-03
  logs/US_SPY_K_15M_2026-05-31.csv — 22,158 candles, 2022-01-03 to 2025-05-30
  logs/US_QQQ_K_15M_2026-05-31.csv — 22,158 candles, 2022-01-03 to 2025-05-30
  logs/US_IWM_K_15M_2026-05-31.csv — 22,158 candles, 2022-01-03 to 2025-05-30
  logs/US_SPY_K_60M_2026-05-31.csv — 5,967 candles, 2022-01-03 to 2025-05-30
  logs/US_QQQ_K_60M_2026-05-31.csv — 5,967 candles, 2022-01-03 to 2025-05-30
  logs/US_IWM_K_60M_2026-05-31.csv — 5,967 candles, 2022-01-03 to 2025-05-30
  Combined CSVs created by merging old (2022-2025) + fresh fetch (2025-05-31 to 2026-06-03), deduped on time_key.

Tests:
  python -m pytest tests/           — 89 tests: risk (22), indicators/signals (47), strategy (18), orb (2)
  python -m pytest tests/ -q        — quiet mode

Signal distribution (60 trades at bonus>=2, SPY+QQQ+IWM):
  rsi_oversold fires on 97% of trades, volume_spike on 88%, ranging (ADX<25) on 33%.
  Dominant combo: rsi_oversold + volume_spike (40/60 trades, 52.5% win).

8. Signal filter sweep (SPY+QQQ+IWM, 2022-2025) — ADX ranging vs BB width percentile alternatives:
   Tested 7 regime filters × 4 min_bonus levels via scripts/sweep_signals.py.
   bb_width_pct added to indicators.py (rolling percentile rank of BB width, window=50).
   Combined results (total_pnl sorted):
   - adx_ranging,      min_bonus=2: 60 trades, 51.7% win, +$19.12 ← BEST (current default confirmed)
   - bb_expanding_60,  min_bonus=2: 69 trades, 49.2% win, +$17.86
   - adx_ranging,      min_bonus=1: 74 trades, 50.0% win, +$17.56
   - bb_contracted_30, min_bonus=2: 53 trades, 52.8% win, +$15.96 (fewer trades than ADX)
   Conclusion: ADX ranging (ADX < 25) is confirmed optimal regime filter. BB width contracted
   filter does not co-occur with entry bars well (entries happen during band expansion, not
   contraction). bb_expanding variants fire more trades but reduce win rate. Do not change
   the ranging signal. ADX < 25 stays.

9. Pipeline validation (2026-05-31): bonus_score bug fixed in paper.py.
   Previous bug: paper.py called score_df() which doesn't add bonus_score — paper runner
   silently never fired entries at MIN_SIGNAL_SCORE >= 1. Fixed: now calls compute_signals()
   which adds bonus_score correctly.
   Validation via simulate_paper.py: signal engines agree on SPY (3/3) and IWM (10/10)
   signals across tested windows. All entries blocked by price_exceeds_max_position
   (MAX_POSITION_DOLLARS=50 is too low for any of SPY/QQQ/IWM single shares).
   Raise MAX_POSITION_DOLLARS to ≥ price of one share before live paper trading.

10. VWAP Pullback (flush-and-reclaim) strategy (2026-06): implemented and deployed.
    Entry: 5-min candle wicks below VWAP (low < vwap) but closes above it.
    Filter: session VWAP cross count ≤ 1 (no-chop filter — critical for edge).
            quiet bar (volume < volume_ma), no entry before 9:45.
    Exit: close < vwap (level lost), ATR stop, 15:45 time stop.
    Sweep on SPY+QQQ 2022-2025 (IWM excluded — fails OOS):
    - SPY: PF=1.655 OOS (train 2022-23, test 2024-25)
    - QQQ: PF=1.072 OOS
    - IWM: negative OOS — excluded via VWAP_PB_SYMBOLS=US.SPY,US.QQQ in config
    Optimal: stop_mult=1.0, max_crosses=1. Deployed to VPS.

11. ORB per-symbol window (2026-06): bug fix + per-symbol override implemented.
    IWM ORB: 15-min OR → PF=1.017. 30-min OR → PF=1.217. Override via ORB_MINUTES_OVERRIDES.
    Bug fixed: _build_opening_ranges() was always using global ORB_MINUTES constant even when
    per-symbol override was set. OR range (and thus stops/targets) was computed from wrong window.
    Fixed: _build_opening_ranges() now accepts orb_minutes parameter; paper runner passes
    cfg.orb_minutes_overrides.get(symbol, cfg.orb_minutes) per symbol.

12. KDJ_WINDOW_BARS (2026-06): lookahead window for KDJ cross vs BB touch timing mismatch.
    w=0 (same-bar only): ~1 trade/month per symbol. w=3 (KDJ cross within 3 prior bars): 10x
    more signals, OOS PF>1.1 on IWM+QQQ. SPY fails at any w>0 — keep SPY at w=0 or exclude.
    Both backtester (strategy.py) and paper runner (paper.py) use same rolling window logic.
    Deployed: KDJ_WINDOW_BARS=3 on VPS.

14. Session filter sweep (2026-06-03): BB+KDJ intraday hour analysis across 1,108 trading days.
    Tested 12 blocked-hour combinations via scripts/sweep_session_filter.py on combined CSVs.
    Key findings (delta vs baseline, all 3 symbols):
    - Block 10-11: +$3.83 IWM, +$5.31 QQQ, −$0.80 SPY — only universally non-negative filter
    - Block 14: +$7.26 SPY, +$1.97 IWM, −$2.08 QQQ — symbol-specific, not universal
    - Block 15-16: −$21.92 IWM, −$21.75 QQQ, −$33.61 SPY — NEVER block the close hours
    - Block open (9): −$14.57 IWM, −$11.00 SPY — open entries are productive, don't block
    Decision: NOT implemented. BB+KDJ already has aggressive multi-condition filtering.
    Adding a time blackout on top further suppresses a low-frequency strategy. Small sample
    (300 trades/4yr per symbol) makes per-hour improvement unreliable. Session filter code
    exists in strategy.py (blocked_hours param) and sweep script for future reference.

13. EMA5/EMA20 momentum breakout research (2026-06): tested, no deployable edge found.
    Tested: cross entry (EMA5 crosses EMA20) and pullback entry (close retraces to EMA5
    while EMA5>EMA20), with ADX filter [20/25/30] and ATR target [0.5/1.0/1.5/2.0×].
    Cross entry: uniformly negative across all 36 parameter combos × 3 symbols (PF 0.3–0.93).
    Pullback entry: stop_mult parameter inert (EMA20_BREAK always triggers before ATR stop —
    stop parameter does nothing). ADX=25 performs worse than both ADX=20 and ADX=30 on all
    3 symbols simultaneously — suspicious sample artifact. ADX=20 shows weak positive PF
    (1.06–1.20) but without a functioning stop parameter the risk management is broken.
    Verdict: do not deploy. Code in mm/ema_momentum.py for reference.

IWM outperformance root cause: lower stop rate (38% vs 50-58% for SPY/QQQ) and faster
  reversals (132 min avg hold vs 309/507). Not about volatility ratios — those are equal
  across symbols. IWM's BB+KDJ signal is simply more predictive.

VPS deployment (as of 2026-06-03):
  STRATEGIES=bb_kdj,orb,vwap_pb
  SYMBOLS=US.IWM,US.SPY,US.QQQ
  KDJ_WINDOW_BARS=3
  ORB_MINUTES=15, ORB_MINUTES_OVERRIDES=US.IWM:30
  VWAP_PB_SYMBOLS=US.SPY,US.QQQ  (IWM excluded)
  MAX_POSITION_DOLLARS=900
  Services: moomoo-paper.service + moomoo-dashboard.service (Restart=always)
  Sync logs: ./sync_logs.sh (rsync VPS → local)

What to build next (in priority order):
1. Wait for first live trades — no trades have fired yet (choppy market, VWAP crosses=6-9).
   Once trades appear: run compare_paper_vs_backtest.py to validate signal engines agree.
2. VIX daily regime filter — block BB+KDJ entries on high-volatility days (VIX > 25).
   Approach: download CBOE VIX daily CSV (free), join on date, backtest on combined CSVs.
   Use yfinance for daily VIX pull at session start. No intraday alignment needed.
3. EMA momentum stop fix: if revisiting, fix stop to be ATR-only (not min(ema20, atr)).
   Investigate ADX=25 anomaly before considering deployment.

Do not ask before every small change. Make reasonable implementation decisions.
After changes, explain what was built, how to run it, and what remains.

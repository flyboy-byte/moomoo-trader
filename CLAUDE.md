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

Current build state (as of 2026-05-31):
Core complete. Signal engine, safety tests, JSONL export, position persistence, simulation validation all done.
Terminal dashboard added (scripts/dashboard.py) — live Textual TUI for monitoring paper sessions.

Package layout:
  mm/config.py         — .env loading, cfg singleton (all config lives here)
  mm/logger.py         — file + console logging
  mm/connection.py     — quote_context() context manager for OpenD
  mm/health.py         — run_health_check() (socket + quote ping)
  mm/data.py           — fetch_candles(), fetch_and_save()
  mm/indicators.py     — bollinger_bands(), atr(), kdj(), add_all()
  mm/strategy.py       — run_signals(), Trade, Signal (entry/exit logic)
  mm/backtest.py       — run_backtest(), walk_forward(), print_summary()
  mm/research.py       — compare_variants(), sweep_parameters(), analyze_stop_exits(), sweep_signal_filter()
  mm/risk.py           — trading_allowed(), calc_qty(), DailyTracker
  mm/paper.py          — paper trading loop with SIMULATE orders
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
  python scripts/dashboard.py                                                  # live TUI dashboard
  python scripts/dashboard.py --date YYYY-MM-DD                               # review past session

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
  logs/US_SPY_K_5M_2026-05-30.csv  — 66,474 candles, 2022-01-01 to 2025-05-30
  logs/US_QQQ_K_5M_2026-05-31.csv  — 66,474 candles, 2022-01-01 to 2025-05-30
  logs/US_IWM_K_5M_2026-05-31.csv  — 66,474 candles, 2022-01-01 to 2025-05-30
  logs/US_SPY_K_15M_2026-05-31.csv — 22,158 candles, 2022-01-03 to 2025-05-30
  logs/US_QQQ_K_15M_2026-05-31.csv — 22,158 candles, 2022-01-03 to 2025-05-30
  logs/US_IWM_K_15M_2026-05-31.csv — 22,158 candles, 2022-01-03 to 2025-05-30
  logs/US_SPY_K_60M_2026-05-31.csv — 5,967 candles, 2022-01-03 to 2025-05-30
  logs/US_QQQ_K_60M_2026-05-31.csv — 5,967 candles, 2022-01-03 to 2025-05-30
  logs/US_IWM_K_60M_2026-05-31.csv — 5,967 candles, 2022-01-03 to 2025-05-30

Tests:
  python -m pytest tests/           — 87 tests: risk (22), indicators/signals (47), strategy (18)
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

IWM outperformance root cause: lower stop rate (38% vs 50-58% for SPY/QQQ) and faster
  reversals (132 min avg hold vs 309/507). Not about volatility ratios — those are equal
  across symbols. IWM's BB+KDJ signal is simply more predictive.

What to build next (in priority order):
1. Raise MAX_POSITION_DOLLARS to a real value (e.g. $300 for IWM, $600 for SPY) and run the
   paper runner live during market hours to collect real JSONL, then compare_paper_vs_backtest.py
2. Consider IWM-only or IWM-weighted portfolio given its edge (61.9% win at score>=2, 38% stops)
3. Terminal dashboard — real-time view of paper positions and daily P&L (rich library)
4. README.md for GitHub — strategy summary, architecture, how to run, research findings

Do not ask before every small change. Make reasonable implementation decisions.
After changes, explain what was built, how to run it, and what remains.

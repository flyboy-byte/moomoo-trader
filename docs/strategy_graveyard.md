# Strategy Graveyard & Feature Log

Everything tested, built, abandoned, or parked. Nothing is lost — code exists, findings are
documented. This file keeps sessions context-efficient by recording the "why" behind every decision.

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
| VWAP Pullback | `mm/vwap_pullback.py`, `mm/evals.py` | SPY/QQQ only. PF=1.655 SPY, 1.072 QQQ OOS. |
| Fractional sizing | `mm/risk.py` (_qty, _slot_dollars) | TOTAL_CAPITAL / (symbols × strategies) per slot |
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
`tests/test_metric_consistency.py`, plus `tests/test_execution.py`/`tests/test_events.py`
for the fourth) — run them with the rest of the suite, no special invocation needed.

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

### Inferred Features — NOT BUILT, parked (2026-06-16 deep research pass)
Five ideas surfaced by the same three research reports that are plausible but premature,
speculative, or high-effort relative to current trade volume. Logged so future sessions don't
re-litigate from scratch:

| Idea | Why parked |
|---|---|
| Self-computed GEX/regime tag from Moomoo's free option-chain greeks (Σgamma×OI per strike) | Real and free, but only useful after ~100+ live trades across strategies to test whether mean-reversion outperforms in positive-GEX regimes. Premature at current trade count. |
| Futures pre-open premium (ES/NQ) as gap-fade confirmation | Research itself flags this as small-sample practitioner-only evidence (~30 cases), not peer-reviewed. Moomoo US accounts are quote-only on futures (no trading); exact ES/NQ/RTY quote-symbol strings were never verified by any of the 3 reports. |
| Order book / tick-data aggressor-side pressure during pre-market | `get_rt_ticker` exposes trade direction but is real-time-only — no historical tick endpoint exists per research. Would need weeks of live data collection before any backtest is possible. |
| OpEx calendar regime tag (vol-compressed mornings, "gamma cliff" the following Monday) | Plausible and documented (Ni/Pearson/Poteshman pinning effect), but orthogonal to Gap Fade — touches ORB/BB+KDJ regime logic instead. Separate research track. |
| External vendor backfill (FirstRate Data / Databento) for pre-market history beyond Moomoo's <2yr retention | Not needed yet — test against whatever window Moomoo actually returns first. Revisit only if that window proves too short for a meaningful sample (<30 gap-fade-eligible days). |

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
| KDJ_WINDOW_BARS | 3 | 0–5 | ~6.7-7.7× signals on IWM/QQQ vs w=0; SPY excluded or kept at 0 (corrected 2026-06-18 after a day-boundary leak bug fix — see "KDJ Day-Boundary Signal Leak" above; was documented as "10×" on the buggy signal set) |
| EXIT_ON_KDJ_DEATH | false | — | Re-enabling flips SPY PnL from +$2.34 → −$0.83 |
| ORB_TARGET_MULT | 1.5 | 1.0–2.0 | Best combined PF |
| ORB_VOL_MULT | 1.5 | 0.0–2.0 | OOS (2024+): QQQ PF 1.162→1.309 (+13%), SPY 1.122→1.156. IWM unaffected (PF flat 1.216→1.210 — high-vol filtering hurts IWM in recent data; skip per-symbol override for now). Deployed 2026-07-12. |
| VWAP_PB_MAX_CROSSES | 1 | 0–3 | Critical no-chop filter for VWAP PB edge |
| Timeframe | K_5M | 5M/15M/60M | K_15M produces MORE stops, not fewer |
| Regime filter | ADX < 25 | 7 alternatives | Confirmed best vs BB width, volume variants |
| ORB window IWM | 30-min | 15/30-min | 15-min PF=1.017 → 30-min PF=1.217 |
| ORB_SHORT_SYMBOLS | US.SPY | all vs per-symbol | Live data 2026-06-17→2026-07-09: QQQ shorts 0% win/24 trades (−$80), IWM shorts 0% win/12 trades (−$40), SPY shorts 100% win/20 trades (+$36). QQQ+IWM disabled. |
| mm/vwap_strategy.py + mm/vwap_signals.py | Candidate for removal | Still imported by mm/paper.py and mm/evals.py for the deprecated 'vwap' strategy path. No live STRATEGIES entry uses them. Safe to delete once the import sites are cleaned up. |

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

### External audit round (ChatGPT + Deep Research, 2026-08-25) — 2 bugs confirmed and fixed same-day
**Context:** handed `docs/deep/moomoo-audit-bundle-2026-08-24.md` to ChatGPT for review, then to a
Deep Research pass with an adversarial-methodology brief. Both flagged real code-level bugs
(verified by reading the actual source before acting, per this project's own "input to verify,
not fact" rule for cross-model audits) plus a substantial epistemic critique of the evaluation
methodology (data-snooping on the reused 2024+ "OOS" period, DIA/correlated-symbol independence,
gate N as operational-minimum vs statistical-sufficiency, LLM regime label reproducibility). The
epistemic critique is tracked separately (see "Evaluation methodology critique" below) — it's a
process/framing decision, not a bug. Five code-level claims were checked against source; two were
fixed immediately as clear, surgical, no-knob-change bugs (below); three more (execution
reconciliation state model, archive corruption-recovery policy, regime cache versioning) are real
and tracked as pending, not yet fixed — see the entries following.

### validate_regime.py averaged daily PF ratios instead of pooling trades — FOUND & FIXED 2026-08-25
**What it was:** `scripts/validate_regime.py` computed `profit_factor(day_trades)` independently
for each trading day, dropped days with infinite PF (zero gross losses), and averaged the
remaining daily PF values — then printed that average as "Avg PF" per regime label and used it to
declare "GATE CONFIRMED" for the live `REGIME_SKIP_LABELS=trending_up,trending_down` config.
**Why it's wrong:** averaging ratios is not the same statistic as profit factor. Two days — one
gross_win=10/gross_loss=1 (PF=10), one gross_win=1/gross_loss=10 (PF=0.1) — average to
`(10+0.1)/2=5.05`, while the actual pooled PF across both days is `(10+1)/(1+10)=1.00`, i.e.
exactly breakeven. A regime label could look "extraordinarily beneficial" on the old statistic
while its underlying trades are flat on the correct one. Dropping infinite-PF days before
averaging compounds the distortion rather than fixing it.
**Fix:** pool every trade belonging to a label (across all its days) and call the project's
canonical `profit_factor()` once on the pooled list — the same calc every other PF number in the
project already uses (see the 2026-06-18 "reimplemented-metric drift" fix in `mm/backtest.py`).
Applied to both the per-label summary table and the skip-vs-keep overall verdict.
**Consequence:** the historical evidence previously cited for the `trending_up`/`trending_down`
regime-gate flip (`evaluation_criteria.md` amendment log, 2026-07-26) was computed with the buggy
statistic. **Re-run `python scripts/validate_regime.py --from-cache` before treating that flip as
confirmed** — this does not mean the flip is wrong, it means the number that "confirmed" it needs
to be recomputed. Not yet re-run as of this entry.
**Tests:** `tests/test_validate_regime_pf.py` — pins the PF=10/PF=0.1→pooled=1.00 example directly
(asserts the naive average would give 5.05, the wrong answer) plus a zero-loss-day pooling case.

### _kdj_cross_age() leaked yesterday's KDJ cross into the first bars of a new session — FOUND & FIXED 2026-08-25
**What it was:** `mm/evals.py::_kdj_cross_age()` scanned `df_signals["kdj_golden_cross"].tail(50)`
with no day-boundary check — a cousin of the exact bug `mm/strategy.py`'s entry gate was fixed for
on 2026-06-17 (KDJ Day-Boundary Signal Leak, see below). The entry *gate* was fixed; this
*telemetry* function, which logs cross age on every bb_kdj bar_eval/position_open, was missed.
**Why it matters:** `kdj_cross_age` exists specifically to let `evaluation_criteria.md`'s BB+KDJ
gate compare same-bar (w=0, `kdj_cross_age=0`) trades against diluted window (w>0) trades without
a parallel runner. A cross late on day 1 mislabeled as "age 2" on day 2's first bar corrupts
exactly the subset comparison that gate depends on — the execution logic (entries) was correct
the whole time; only the evidence used to evaluate a *future* strategy change was wrong.
**Fix:** bound the lookback to the current calendar day before scanning for the most recent
cross, mirroring `mm/strategy.py`'s existing `groupby(day_key)` pattern exactly.
**Tests:** `tests/test_kdj_cross_age.py` — a cross late on day 1 followed by day-2 bars must
return `None`, not a leaked age; same-day crosses still resolve correctly.

### _reconcile_positions()'s "offsetting positions" check didn't verify quantity or direction — FOUND & FIXED 2026-08-25
**What it was:** when the broker showed zero net for a symbol but local state had a position, the
code checked whether *any other strategy* on that symbol had a FILLED order (`other_filled`) and,
if so, assumed the positions were legitimately offsetting (e.g. BB+KDJ long SPY + ORB short SPY
netting to zero) and kept both — without ever summing signed local quantities and comparing to the
broker's actual net. Two same-direction FILLED positions on the same symbol (e.g. bb_kdj long 10 +
vwap_pb long 5) satisfied `other_filled=True` even though they cannot possibly explain a broker net
of zero. In SIMULATE this can't lose real money, but it could preserve fictional positions
indefinitely and corrupt the exact execution-quality evidence `evaluation_criteria.md`'s ORB gate
depends on ("check slippage/fill quality FIRST").
**Fix:** sum signed local quantities (`+qty` long, `-qty` short) across this position and any other
FILLED positions on the same symbol; only take the offset shortcut if that sum actually nets to the
broker's reported zero. Otherwise fall through to the existing per-order status/grace-period
mismatch logic — unchanged for the genuine offsetting case (BB+KDJ long + ORB short still nets to 0
and is kept), only closes the case where it doesn't.
**Tests:** `tests/test_execution.py::test_reconcile_does_not_treat_same_direction_fills_as_valid_offset`
— existing `test_reconcile_keeps_offsetting_positions_netting_to_zero` still passes unchanged.

### update_combined_csv()'s corruption-recovery policy destroyed history instead of failing closed — FOUND & FIXED 2026-08-25
**What it was:** if `pd.read_csv()` on the existing archive raised *any* exception, `mm/data.py`
logged "rebuilding from this fetch" and set `combined = df_new` — replacing the entire never-pruned
multi-year archive with whatever the current small cron fetch contained, then atomically committing
that truncated version over the real file. The 2026-06-18 atomic-write fix (temp file +
`os.replace()`) prevents a *partial* write from corrupting the file on a mid-write crash, but did
nothing to prevent this — a full-history wipe on any read exception, committed atomically and
irreversibly. Same never-pruned archive the 2026-08-24 stale-cfg bug (above) already proved is
fragile.
**Fix:** on a read exception, quarantine the unreadable file (rename to
`{name}.corrupt-{timestamp}{suffix}` via `os.replace()`) and re-raise instead of silently
overwriting — a human has to look at it once instead of the evidence being erased automatically.
`scripts/fetch_daily_archive.py` (the only caller) already catches per-symbol, so one corrupt
archive raising doesn't block the rest of that cron run from updating other symbols.
**Tests:** `tests/test_data.py::test_update_combined_csv_quarantines_corrupt_archive_instead_of_wiping`.

### load_regime_today() didn't validate prompt_version against the current experiment — FOUND & FIXED 2026-08-25
**What it was:** `mm/morning_regime.py::load_regime_today()` read `logs/regime_YYYY-MM-DD.json` by
date filename only, checked the label was a valid enum, and returned it — it never compared the
file's stored `model`/`prompt_version` fields (both already logged by `classify_regime()`) against
the currently configured model/prompt. Consequence: after any model or prompt change (e.g. the
Haiku→Sonnet split, or Phase 2 of the volatility-engine plan adding vol_state context to the
prompt), a cached file from the old classifier would be silently reused as if the current one
produced it — mixing two different classifiers' outputs into what's treated as one evaluation
cohort in `validate_regime.py --from-cache`.
**Fix:** `load_regime_today()` now compares the cached file's `prompt_version` against the module's
`PROMPT_VERSION` constant; a mismatch (including a missing field, for pre-versioning files) falls
back to `"neutral"`, same fail-open behavior as a missing/malformed file, rather than trusting
stale-version output.
**Why this is a hard prerequisite for the volatility-engine plan's Phase 2** (feeding `vol_state`
into the regime prompt): without this check, Phase 2's new prompt would silently blend with old
labels in any future validation run. `PROMPT_VERSION` must be bumped (`"v1"` → `"v2"`) when Phase 2
ships.
**Tests:** `tests/test_regime_gate.py::TestLoadRegimeToday` —
`test_stale_prompt_version_falls_back_to_neutral`,
`test_missing_prompt_version_field_falls_back_to_neutral`.

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

### Reimplemented-Metric Drift — 4th instance, written and caught in-session 2026-08-29
**What it was:** while building `mm/stats.py` (bootstrap CIs, Goal A4 of
`docs/research-reset.md`), a fresh `profit_factor()` was written with a `pnl < 0` loss
convention — against the canonical `mm.backtest.profit_factor()`'s `pnl <= 0` — plus a
`nan` empty-sentinel instead of `inf`. This is the same drift class as the three above,
recurring 2.5 months after the consolidation that was supposed to end it, which is worth
recording precisely *because* the guard existed and the mistake still got made.

**Why the existing guard didn't stop it:** `tests/test_metric_consistency.py` pins the
behaviour of `mm.backtest.profit_factor`, but nothing prevents a *new* module from
defining its own function of the same name and never calling the canonical one. A static
guard on the canonical definition doesn't cover "someone wrote a second one."

**Fix:** deleted the local implementation; `mm/stats.py` now re-exports
`mm.backtest.profit_factor`. The bootstrap resampler was also corrected to use the same
`<= 0` convention — a CI built on a different loss convention than the point estimate it
brackets is not guaranteed to contain it. Two new tests:
`test_stats_reexports_the_canonical_profit_factor_not_a_copy` (asserts function
*identity*, so a future reimplementation fails immediately rather than drifting) and
`test_bootstrap_ci_uses_the_same_loss_convention_as_the_point_estimate`.

**Standing lesson:** the category is not fully guarded. A repo-wide grep test for
`def profit_factor` outside `mm/backtest.py` would close it properly. Not built yet —
recorded here so the next occurrence isn't diagnosed from scratch a fifth time.

### np.percentile silently returned nan for bootstrap CIs on mostly-winning samples — FOUND & FIXED 2026-08-29
**What it was:** `mm/stats.py::bootstrap_pf_ci()` resamples trades and computes a profit
factor per resample. Resamples containing no losses correctly give `PF = inf`. But
`np.percentile`'s default linear interpolation computes `(b - a)` between neighbouring
order statistics, and `inf - inf` is `nan`. On a small, mostly-winning sample, enough
resamples are `inf` that the upper percentile lands in that region — so the *entire
interval* came back `(nan, nan)` with only a `RuntimeWarning` on stderr. A confidence
interval that silently evaporates on exactly the samples most likely to look impressive
is the worst possible failure direction for this module.

**Found by:** a unit test asserting `pf_ci[0] <= pf <= pf_ci[1]`, written before the bug
was suspected. It failed on the first run with `nan` as the upper bound.

**Fix:** `method="nearest"` on both percentile calls, which selects an actual order
statistic instead of interpolating and therefore returns `inf` — the truthful answer
("unbounded above at this sample size"). Pinned by
`test_pf_ci_upper_bound_is_inf_not_nan_when_resamples_have_no_losses`.

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

### Evaluation methodology critique — external audit round 2026-08-25, under consideration
Full writeup: `docs/deep/deepresearch-output-2026-08-25.md` (Deep Research, adversarial-methodology brief) and
the ChatGPT review that preceded it. This is a framing/process critique, not a bug — recorded here
so the reasoning isn't lost, not yet acted on except where noted.

**Core claim:** the project's fixed trade-count gates (10/15/20/30/50) are *operational minimums*
("don't even review this lane yet"), not evidence that uncertainty has become small enough to
call a strategy "validated." At N=20 with an observed win rate near 50%, the audit computes a
Wilson-interval half-width of roughly ±20 points — i.e. a nominal 50% result at 20 trades is
compatible with a true win probability anywhere from ~30% to ~70%. The 2026-08-24 gate-ETA fix
(above, "gate ETAs" amendment) was directionally right — it caught an N that would take 13+
months to reach — but the audit argues the *causal direction* should reverse: decide what
uncertainty is tolerable first, derive N from that, then accept whatever ETA falls out, rather
than picking N to fit a comfortable calendar window.

**Second claim — the regime-PF bug (fixed above) understates a bigger problem:** the project's
2024+ backtest window has been repeatedly re-examined across many strategy/parameter decisions
(ATR stop selection, signal-score selection, KDJ window, ORB cutoff, symbol exclusions, regime
filter). Per Halbert White's data-snooping framework, reusing one dataset across many rounds of
model selection means each individual "OOS" claim can look valid in isolation while the aggregate
selection process still overfits. The audit's suggested reframe: treat everything examined through
2026-08-24 as **development data**, not confirmation data, and start a frozen forward-only paper
cohort on a fixed date for any strategy whose current config is meant to be evaluated cleanly.

**Third claim — DIA (or any added symbol) is not "faster independent evidence."** Directly
contradicts the "more symbols legitimately speeds up gates" framing floated earlier in this
project's own reasoning (2026-08-24 session). Broad-market ETFs share common factor exposure, so
same-day trades across SPY/QQQ/IWM/DIA are correlated observations, not independent ones — a
same-day cluster of 4 trades carries meaningfully less than 4 trades' worth of information. The
audit's suggested design-effect approximation (`DE ≈ 1+(m-1)ρ`) at ρ=0.5, m=4 gives DE=2.5, i.e.
4 same-day observations ≈ 1.6 independent-equivalents. Recommendation: if a new symbol is added,
freeze the strategy and pre-register the symbol as a *replication* test before looking at its
results, and cluster-bootstrap by trading date (not by raw trade count) when reporting combined
uncertainty — this directly changes how the "50 trades/symbol" cross-strategy gate (added
2026-08-24) should eventually be interpreted, though the gate itself wasn't rewritten this session.

**Not acted on this session** — these are project-philosophy decisions (what "validated" means,
whether/when to declare a frozen confirmation cohort, whether to add strategy/policy versioning to
every trade event) that deserve a deliberate call rather than a unilateral doc rewrite mid-audit.
Tracked here so the reasoning survives to whenever that call gets made.

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

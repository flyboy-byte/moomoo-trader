# Route 2b — Volatility Term-Structure Engine + Bounded AI Triggers

**Status:** Phase 1 + Phase 3 done (2026-08-25). Phase 2 next, blocked on accumulating real
`vol_state.jsonl` observations first (cron started 2026-08-25, first market-hours run ~13:30 UTC).
**Priority:** High — extends Route 2's regime gate, the one AI call that already demonstrably
affects live trades.

This is an extension of [route-2-llm-signals.md](route-2-llm-signals.md), tracked separately
because it's a distinct, multi-phase build with its own gates. Ported here 2026-08-25 from a
Claude Code plan-mode session file (which lives outside the git repo and would not survive to a
future session) — this is now the authoritative copy.

---

## Context

The project's only volatility signal before this work was yesterday's settled `VIX` close
(`scripts/fetch_vix_morning.py` → `logs/vix_daily.jsonl`), read by three separate live gates:
`mm/evals.py::_load_vix_today()` (ORB + gap_fade VIX caps) and `mm/morning_regime.py::_load_vix()`
(one input to the Claude regime classifier). A single prior-day number collapses a lot of distinct
information — term structure, vol-of-vol, cross-asset divergence — into one scalar, and treats
SPY/QQQ/IWM as if they share one volatility regime despite the project's own data already showing
they don't (per-symbol VIX overrides exist precisely because they diverge).

Goal: a deterministic volatility engine feeding richer context to the existing AI regime
classifier, event-driven refresh instead of fixed 9:20/9:35 ET calls, a bounded ALLOW/TIGHTEN/BLOCK
policy schema replacing the binary regime gate, and a new, narrower AI catalyst classifier
specifically for `gap_fade` (worst performer at build time, PF 0.29).

**Feasibility verified 2026-08-25 (do not re-derive):**
- Free via yfinance (same dependency `fetch_vix_morning.py` already uses): `^VIX`, `^VIX1D`,
  `^VIX9D`, `^VIX3M`, `^VIX6M`, `^VVIX`, `^VXN`, `^COR1M`, `^COR3M`.
- `^RVX` (Russell 2000 vol, the natural IWM-specific index) does **not** resolve via yfinance —
  tried `RVX`, `^RVX`, `RUTVIX`, all empty/404.
- OpenD **cannot** supply any of this — tested live against the VPS's OpenD connection:
  `get_market_snapshot(['US..VIX'])` → "US stock indices are not supported". `get_future_info
  (['US.VXmain'])` → needs a paid quote card. `get_option_expiration_date('US.IWM')` → needs a paid
  US ETF/options quote upgrade.
- yfinance has zero historical backfill for `^VIX1D/^VIX9D/^VIX3M/^VIX6M/^COR1M/^COR3M` — only the
  single latest day via both `download(period="5y")` and `Ticker.history(start=...)`. Only
  `^VIX/^VVIX/^VXN` have real 5-year history to calibrate thresholds from.
- yfinance is an unofficial Yahoo interface, not a paid feed with an SLA — can silently return
  stale/frozen data without raising (verified: this is literally how the backfill gap above was
  discovered). `mm/vol_engine.py::fetch_vol_levels()` therefore tracks per-ticker freshness/error
  as first-class metadata (`as_of`, `stale`, `error`), not just the levels.
- **Conclusion: 100% of new volatility data comes from yfinance. IWM gets no RVX-equivalent —
  shares the VIX-family signal, no small-cap-specific index, unless the user buys Moomoo
  option-quote entitlements later (out of scope now).**

**Methodological guardrails this plan must respect** (from the 2026-08-25 external audit,
`docs/strategy_graveyard.md`): every new AI/gate mechanism needs (a) a pre-registered evaluation
gate in `evaluation_criteria.md` *before* it can ever move from shadow to live-blocking, (b) a
policy/model/prompt version tag so historical evidence isn't silently mixed across versions, (c)
shadow-mode-first + counterfactual logging so "with AI" vs "without AI" can be computed later. No
unrestricted AI powers — bounded to ALLOW/TIGHTEN/BLOCK only (user's explicit constraint: "No
position sizing. No arbitrary entry prices. No arbitrary stops.").

## Existing patterns to reuse (do not reinvent)

- **Per-symbol override config parsing**: `mm/config.py` — `"US.IWM:300,US.SPY:600"` → dict, e.g.
  `ORB_VIX_MAX_OVERRIDES`, `GAP_VIX_MAX_OVERRIDES`. Use identical shape for new per-symbol vol
  thresholds.
- **Shadow-mode gate pattern**: `mm/evals.py::_regime_gate()` — when `*_GATE_ENABLED=false`, logs
  `signal_skip("regime_gate_shadow", ..., would_block=True, gate_enabled=False)` instead of
  blocking.
- **`PaperEventLog`**: `signal_skip(reason, score, bonus, min_score, strategy="", **extra)` and
  `position_open`/`position_close` pass `**extra` straight to the JSONL record. `bar_eval` does
  NOT take `**extra` — extra detail goes in the `signals={...}` dict argument instead.
- **LLM call caching**: `mm/morning_regime.py` — `_orb_score_cache` keyed by `f"{symbol}:{bar_ts}"`,
  `_regime_cache`/`_regime_confidence_cache` keyed by date string, with `clear_*_cache()` test
  helpers.
- **Model split** (done 2026-08-25): `cfg.anthropic_model` (Sonnet, `classify_regime()` only —
  load-bearing) vs `cfg.anthropic_model_cheap` (Haiku, `score_orb_setup()` + `weekly_synthesis()`).
  New shadow-mode/summarization-class AI calls default to `anthropic_model_cheap`.
- **ORB scorer gate insertion point** (`mm/evals.py`, in `_eval_orb`) is the direct template for
  the gap_fade catalyst gate: runs after the mechanical setup is determined, before qty/risk
  checks, fail-open on any API error, logs confidence/reason via `**extra`.
- `mm/gap_fade.py` deliberately does NOT import `cfg` (module-level `os.getenv` constants) — any
  catalyst classifier gate belongs in `mm/evals.py::_eval_gap_fade()` (which does use `cfg`), NOT
  inside `mm/gap_fade.py` itself.

## Phases

### Phase 1 — Deterministic volatility engine (no new AI calls) ✅ DONE 2026-08-25
`mm/vol_engine.py` + `scripts/fetch_vol_state.py`, wired into `scripts/install_cron.sh` (every
15min market hours, `*/15 13-20 * * 1-5` UTC). 12 passing tests (`tests/test_vol_engine.py`).

Level bucket thresholds (real percentiles p25/p75/p90) calibrated for `vix`/`vvix`/`vxn` only —
the six term-structure tickers with no yfinance backfill are logged as raw ratios, not bucketed,
until enough forward snapshots accumulate. `fetch_vol_levels()` returns `(levels, meta)` — meta
carries `as_of` date, `stale` flag (close >4 days old), `error` string per ticker; logged as
`fetch_meta` in every `vol_state.jsonl` record (added 2026-08-25 after external feedback flagged
yfinance's no-SLA reliability as under-addressed).

Deployed shadow-only: writes `logs/vol_state.jsonl`, **nothing reads it yet**. Deployed to VPS and
cron installed 2026-08-25; first market-hours run ~13:30 UTC 2026-08-25.

**Verification still needed before Phase 2 starts writing the prompt against it:** let a few
sessions of real `vol_state.jsonl` accumulate, confirm values look sane against known
volatile/calm days, confirm `stale`/`error` metadata isn't constantly firing (would mean the
yfinance fetch itself is unreliable at this poll frequency, not just the term-structure backfill
gap).

### Phase 2 — Feed vol_state into the existing regime classifier — NOT STARTED
**Changed:** `mm/morning_regime.py::classify_regime()` prompt gains a new structured block (the
vol_state dict from Phase 1, for SPY/QQQ/IWM). Still one Sonnet call at 9:20 ET — this phase adds
*context*, not a new call. Output schema stays the same 5-label regime classification for now
(don't change the schema and the input in the same step — isolate variables). **Must bump
`PROMPT_VERSION` "v1" → "v2" in the same change** — Phase 3's versioning check only protects
against stale reuse if the constant is actually incremented alongside the prompt.

**Verification**: compare regime labels before/after on the same dates isn't meaningful once the
prompt changes (genuinely a new classifier version) — need new data, not a re-read of old data.

**Blocked on:** Phase 1 producing enough real `vol_state.jsonl` snapshots to write the prompt
block against actual observed value ranges/staleness behavior, not synthetic data.

### Phase 3 — Regime cache/experiment versioning (prerequisite for Phase 2) ✅ DONE 2026-08-25
`load_regime_today()` now compares the cached file's `prompt_version` against the module's
`PROMPT_VERSION` constant; mismatch (or missing field) falls back to `"neutral"`, same fail-open
behavior as a missing/malformed file. Full writeup: `docs/strategy_graveyard.md` "Fixed Bugs" —
`load_regime_today() didn't validate prompt_version...`. Tests in
`tests/test_regime_gate.py::TestLoadRegimeToday`.

### Phase 4 — Event-driven refresh — NOT STARTED
**Changed:** `mm/paper.py`'s main loop (60s poll) gains a check: after the fixed 9:20 ET
classification, re-run `classify_regime()` only when `vol_state` (polled each loop iteration —
cheap, no API call) crosses a material-change threshold (e.g. `vix1d/vix` ratio moves into a
different bucket, or `vix` itself jumps >X% intraday). Rate-limit (e.g. minimum 30 min between
re-classifications). Every re-classification writes a new dated+timestamped regime file (not
overwriting the 9:20 one) so the day's regime history is fully reconstructable, logs which
trigger fired.

**Verification**: run for several sessions, confirm re-classification fires only on genuine
vol_state shifts and Sonnet call volume stays low (~1-3 calls/day, not 100s).

### Phase 5 — Bounded ALLOW/TIGHTEN/BLOCK policy (replaces binary regime gate) — NOT STARTED
**Changed:** `mm/evals.py::_regime_gate()` and downstream `_eval_bb_kdj`/`_eval_bb_kdj_loose`.
Regime classifier output schema gains fields (`shock_state`, `event_risk`, `trend_quality`), but
the action space stays exactly three values — `ALLOW` (normal), `TIGHTEN` (a defined,
deterministic effect — e.g. `bonus_score` one point higher, tighter ATR stop multiplier; NOT
sizing, NOT arbitrary price levels), `BLOCK` (current behavior). The mapping from regime+vol_state
to ALLOW/TIGHTEN/BLOCK is a deterministic, versioned lookup table — the LLM outputs descriptive
state, a deterministic function maps state → policy. This preserves "AI never touches
sizing/stops directly."

**Pre-registration required before this ships live**: add a section to `evaluation_criteria.md`
(pattern already established for gap_fade/bb_kdj_loose) defining the gate — sample size,
comparison, confirm/disconfirm criteria — *before* TIGHTEN can affect a live trade. Shadow-mode
first, exactly like every other gate in this codebase.

### Phase 6 — Gap Fade catalyst classifier (concrete, targeted experiment) — NOT STARTED
**New:** `classify_gap_catalyst(symbol, date_str, gap_pct, premarket_vol, vol_state) -> dict` in
`mm/morning_regime.py` (same shape as `score_orb_setup`), called once per gap_fade entry
evaluation (max once/symbol/day). Defaults to `anthropic_model_cheap`/Haiku. Output schema:
```json
{"catalyst": "none|weak|moderate|strong", "catalyst_type": "macro|geopolitical|earnings|sector|unknown", "confidence": 0.0-1.0}
```
**Insertion point**: `mm/evals.py::_eval_gap_fade()`, immediately after direction is determined and
before qty/risk checks — same slot pattern as the ORB scorer. New config:
`GAP_CATALYST_FILTER_ENABLED=false` (shadow-mode-first), logs `signal_skip("gap_catalyst_shadow",
..., catalyst=..., would_skip=(catalyst in ("moderate","strong")))`.

**Pre-registration required**: add a Gap Fade catalyst section to `evaluation_criteria.md` — e.g.
"after N shadow-logged gap days, compare PF/expectancy on catalyst∈{none,weak} vs
catalyst∈{moderate,strong}; only flip `GAP_CATALYST_FILTER_ENABLED=true` if strong-catalyst days
show a materially worse PF with enough sample to trust it" — using the ETA-aware gate-sizing
discipline (compute expected trades/week before picking N).

## What this plan deliberately does NOT do
- Does not touch position sizing, entry price, or stop distance via AI, anywhere.
- Does not attempt an IWM RVX-equivalent via paid option-IV entitlements — a future, separate,
  budget-gated decision if the user wants it later.
- Does not flip any new gate to live-blocking as part of this plan — every new mechanism ships
  shadow-mode-first. Flipping to live is a separate, later, data-gated decision per strategy.

## Files touched (representative, see phase sections above for exact locations)
- New (done): `mm/vol_engine.py`, `scripts/fetch_vol_state.py`
- Changed (done): `mm/morning_regime.py` (`load_regime_today()` versioning)
- Still to change: `mm/morning_regime.py` (prompt, `classify_gap_catalyst()`), `mm/evals.py`
  (`_eval_gap_fade`, `_regime_gate`), `mm/config.py` (new config fields), `mm/paper.py`
  (event-driven refresh trigger)
- Docs still to update per-phase: `docs/evaluation_criteria.md` (new gate sections, pre-registered
  BEFORE each mechanism can go live), this file (status line + phase checkboxes)

## Verification (end to end, applies to every phase)
1. `pytest tests/` stays green after each phase.
2. Each phase ships shadow-mode-first; verify via counterfactual reporting ("N trades, what AI
   would have done, actual PF vs counterfactual PF") before any gate is proposed for live-blocking.
3. Deploy to VPS: `git pull` + `systemctl --user restart moomoo-paper` (only for changes touching
   the live paper-runner path — Phase 1/data-only changes don't need a restart), confirm clean
   startup via `journalctl --user -u moomoo-paper -n 20`.

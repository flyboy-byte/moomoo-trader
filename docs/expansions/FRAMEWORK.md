# Framework — Moomoo Next Expansions

> **Tier:** Meta (self-aware — this doc describes and tracks the project it's part of)
> **Audience:** you · **Use when:** you don't know what to do next, or you're checking
> in on progress after time away.

## What this is

This packet tracks the next major expansions for the moomoo paper-trading research
project. Two primary routes are in scope: Route 1 (data mining — find a real anomaly
in the candle archive) and Route 2 (LLM signal layer — use Claude API to classify
daily market regime and gate entries). Route 3 (real money) is parked. Each route
goes through this phase model independently — they are parallel tracks, not sequential.

Update the checkboxes below as things actually happen. This file is the honest answer
to "where are we" at any point in the future.

## Phase model

```
Phase 0        Phase 1        Phase 2         Phase 3      Phase 4       Phase 5
Capture   ──►   Scoping  ──►   Validation ──►  Build   ──►  Verify  ──►  Formalize
```

---

## Route 1 — Data Mining: Find a Real Anomaly

### Phase 0 — Capture

- [x] Source material captured — candidate hypotheses written in `route-1-data-mining.md`
- [x] Understood: have 2+ years of SPY/QQQ/IWM 5-min candle CSVs + VIX daily data

**Gate to Phase 1:** automatic — done.

### Phase 1 — Scoping

- [x] `docs/overview.md` (Route 1 section)
- [x] `docs/approach.md` (Route 1 section)
- [x] `docs/risks.md` (Route 1 section)
- [x] `docs/infrastructure.md` (Route 1 section)
- [x] `docs/notes.md` — open questions logged
- [x] `docs/research-handoff.md` — queue populated

**Gate to Phase 2:** done (no blocking condition — this is a documentation exercise).

### Phase 2 — Validation ✓

- [x] `scripts/mine_first_bar.py` run on all 3 symbols — H1 confirmed null (2026-07-23)
- [x] Research loop infrastructure working end-to-end

**Gate to Phase 3:** ✓ passed.

### Phase 3 — Build ✓ (all mining scripts complete 2026-07-23)

- [x] `scripts/mine_first_bar.py` (H1 — 9:30 bar predictive?) → **NULL** all 3 symbols
- [x] `scripts/mine_autocorrelation.py` (H3 — lag-1 autocorr by time-of-day)
      → **SIGNAL**: IWM 9:30-10:00 OOS r=-0.185 p<0.0001 (strong mean reversion)
      → **SIGNAL**: SPY 13:00-14:00 OOS r=+0.059 p<0.0001 (mild momentum)
      → **NULL**: QQQ across all buckets
- [x] `scripts/backtest_gap_fade.py --sweep-vix` (H2 — gap × VIX band)
      → **ACTIONABLE**: VIX 20-25 kills SPY (PF 0.490) and QQQ (PF 0.546) gap fades
      → **SAFE ZONE**: VIX 15-20 best for SPY (PF 1.861) / QQQ (PF 1.289)
      → **IWM DIFFERENT**: positive across all VIX bands (VIX<15: PF 2.397)
- [x] H2 finding deployed: `GAP_VIX_MAX_OVERRIDES=US.SPY:20,US.QQQ:20` (2026-07-23)
      OOS confirmed VIX>=20 negative for both; IWM unfiltered (positive at all VIX bands)

**Gate to Phase 4:** at least one non-trivial finding (positive or confirmed null).

### Phase 4 — Verify

- [ ] Finding validated OOS on held-out date range (not same data it was found in)
- [ ] Walk-forward stability confirmed (PF consistent across rolling 30-day windows)
- [ ] Any deployed `_eval_*` covered by a replay test in `tests/test_replay.py`

**Gate to Phase 5:** OOS-validated finding, or confirmed that all hypotheses are null.

### Phase 5 — Formalize

- [ ] Document what was found (or ruled out) in `docs/strategy_graveyard.md` or
      `docs/evaluation_criteria.md` as appropriate
- [ ] Update `docs/expansions/route-1-data-mining.md` with status and conclusion

---

## Route 2 — LLM Signal Layer (Claude API)

### Phase 0 — Capture

- [x] Source material captured — architecture sketched in `route-2-llm-signals.md`
- [x] Understood: evals.py _eval_* pattern, fail-open requirement, shadow-mode approach

**Gate to Phase 1:** automatic — done.

### Phase 1 — Scoping

- [x] `docs/overview.md` (Route 2 section)
- [x] `docs/approach.md` (Route 2 section)
- [x] `docs/risks.md` (Route 2 section)
- [x] `docs/infrastructure.md` (Route 2 section)
- [x] `docs/notes.md` — open questions logged
- [x] `docs/research-handoff.md` — queue populated

**Gate to Phase 2:** done.

### Phase 2 — Validation ✓

- [x] Anthropic API key obtained and tested
- [x] `scripts/classify_regime.py` returns a valid JSON label for today's date
- [x] Prompt produces sensible labels (first live label: choppy; daily labels since 2026-07-21)

**Gate to Phase 3:** ✓ passed.

### Phase 3 — Build ✓ (shadow mode live as of 2026-07-22)

- [x] `mm/morning_regime.py` — `classify_regime()` + `load_regime_today()` + `clear_regime_cache()`
- [x] `mm/config.py` — `anthropic_api_key`, `regime_gate_enabled`, `regime_gate_strategies`, `regime_skip_labels`
- [x] `mm/evals.py` — `_regime_gate()` helper wired into `_eval_bb_kdj` and `_eval_bb_kdj_loose`
- [x] `scripts/classify_regime.py` — standalone runner (`--dry-run`, `--date`)
- [x] Shadow mode running: classifies daily, never blocks entries, logs `regime_gate_shadow`
- [x] VPS `.env` updated with `ANTHROPIC_API_KEY` + `REGIME_GATE_ENABLED=true` (flipped 2026-07-26)
- [x] VPS cron: `20 13 * * 1-5` (9:20 ET Mon–Fri)

**Phase 3 additions (expanded plan — see route-2-llm-signals.md):**
- [x] **ORB setup scorer** — `score_orb_setup()` in `mm/morning_regime.py`, per-trade confidence gate in `_eval_orb`; live 2026-07-23 (fixed max_tokens bug + fail-open)
- [x] **Weekly synthesis** — `scripts/weekly_synthesis.py`, Monday 9:00 ET cron, posts to Discord; live 2026-07-23

**Gate to Phase 4:** shadow mode cleanly running ≥ 5 sessions (✓) + at least one of the Phase 3 additions built.

### Phase 4 — Verify (in progress 2026-07-29)

- [x] Shadow log reviewed: `validate_regime.py --from-cache` on 618 days — trending_up PF=0.513 (worst), neutral PF=0.880. Gate confirmed.
- [x] `REGIME_GATE_ENABLED=true` flipped 2026-07-26; skip labels corrected to `trending_up,trending_down`
- [ ] `tests/test_replay.py` covers: regime=trending_up → entry skipped; regime=neutral → entry fires (TODO)
- [x] ORB setup scorer: mechanical calibration (N=2924 trades) — scorer features not edge drivers (OR range + timing are). Stays shadow at 0.50 threshold.
- [ ] Gate confirmed live ≥ 10 sessions (only ~3 since 2026-07-26 flip — accumulating)

**Gate to Phase 5:** gate has been live for ≥ 10 trading sessions with no blocking incidents.

### Phase 5 — Formalize

- [ ] Regime label accuracy assessed (does choppy/trending_* predict anything?)
- [ ] Gate kept/removed/tuned based on evidence
- [ ] Decision documented in `docs/strategy_graveyard.md` or `docs/evaluation_criteria.md`
- [ ] Update `docs/expansions/route-2-llm-signals.md` with status and conclusion

---

## Current status (update this line as phases advance)

**Route 1 is in Phase 4 — mining complete (H1 null, H2 deployed VIX filter, H3 autocorr
signal found on IWM 9:30-10:00). Phase 4 OOS walk-forward validation pending.
Route 2 is in Phase 4 — regime gate live with corrected skip labels since 2026-07-26
(trending_up/trending_down block ~23% of days). Accumulating live sessions toward the 10-session
gate. ORB scorer stays shadow-mode. Next: replay test coverage + live data accumulation.**

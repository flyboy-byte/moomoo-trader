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

### Phase 4 — Verify ✓ (2026-08-09)

- [x] **H1 NULL** — no OOS validation needed; null is the finding.
- [x] **H2 deployed and OOS-confirmed** — `GAP_VIX_MAX_OVERRIDES=US.SPY:20,US.QQQ:20` live since
      2026-07-23. VIX filter doesn't live in `_eval_*` (it's in `mm/gap_fade.py` directly);
      gap_fade is not run through the replay pipeline, so no replay test applies.
      Walk-forward with rolling 30-day windows is blocked: `logs/vix_daily.jsonl` only covers
      ~39 recent days, insufficient for historical window analysis. Deployment considered complete.
- [x] **H3 PARKED** — IWM 9:30-10:00 r=-0.185 OOS signal found IN the OOS period (IS shows
      opposite sign, r=+0.049). Not independently validatable until 2027+ data provides a
      genuine held-out window. Graveyard entry complete. No replay test needed (not deployed).
- [x] No `_eval_*` functions modified by Route 1 findings (H2 filter lives in gap_fade.py, not evals.py).

**Gate to Phase 5:** ✓ OOS-validated finding (H2 deployed and confirmed).

### Phase 5 — Formalize ✓ (2026-08-09)

- [x] H1/H2/H3 all documented in `docs/strategy_graveyard.md` (Data Mining Results section)
- [x] H2 filter live and confirmed: `GAP_VIX_MAX_OVERRIDES=US.SPY:20,US.QQQ:20`
- [x] H3 graveyard entry written with explicit 2027+ reopen condition
- [ ] Update `docs/expansions/route-1-data-mining.md` with final status (low priority — graveyard is authoritative)

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

- [x] Shadow log reviewed: `validate_regime.py --from-cache` on 618 days.
  **Re-verified 2026-08-25 with the fixed pooled-PF methodology** (was previously computed with a
  since-fixed averaging bug — see `docs/strategy_graveyard.md`). Corrected numbers: skip-labels
  (`trending_up`+`trending_down`) pooled PF=0.813 (N=81 trades) vs keep-labels pooled PF=1.351
  (N=275 trades), delta +0.537. Per-label breakdown: neutral PF=1.184 (183 trades), trending_up
  PF=0.813 (81 trades, worst populated label), choppy PF=1.122 (52 trades), risk_off PF=2.494 (40
  trades), trending_down had 0 trades in this window (1 day only). **Verdict unchanged: gate
  confirmed** — the exact PF number moved (0.513 → 0.813) but the conclusion (skip labels
  meaningfully worse) held. `regime_validation.csv` regenerated.
- [x] `REGIME_GATE_ENABLED=true` flipped 2026-07-26; skip labels corrected to `trending_up,trending_down`
- [x] `tests/test_replay.py` covers: regime=trending_up → entry skipped; regime=neutral → entry fires (added 2026-08-09)
- [x] ORB setup scorer: mechanical calibration (N=2924 trades) — scorer features not edge drivers (OR range + timing are). Stays shadow at 0.50 threshold.
- [ ] Gate confirmed live ≥ 10 sessions (only ~3 since 2026-07-26 flip — accumulating)

**Gate to Phase 5:** gate has been live for ≥ 10 trading sessions with no blocking incidents.

### Phase 5 — Formalize

- [ ] Regime label accuracy assessed (does choppy/trending_* predict anything?)
- [ ] Gate kept/removed/tuned based on evidence
- [ ] Decision documented in `docs/strategy_graveyard.md` or `docs/evaluation_criteria.md`
- [ ] Update `docs/expansions/route-2-llm-signals.md` with status and conclusion

---

## Route 2b — Volatility Term-Structure Engine + Bounded AI Triggers

Extension of Route 2, tracked in full detail in
[route-2b-volatility-engine.md](route-2b-volatility-engine.md) (6 phases, its own gates) — not
duplicated here. Started 2026-08-25 after external feedback (ChatGPT + Deep Research audits)
prompted a broader look at volatility signal quality feeding the regime gate.

**Phase 1** (deterministic vol engine, no AI) ✅ DONE 2026-08-25 — `mm/vol_engine.py` +
`scripts/fetch_vol_state.py`, shadow-only, writes `logs/vol_state.jsonl`, nothing reads it yet.
**Phase 3** (regime cache versioning, a hard prerequisite for Phase 2) ✅ DONE 2026-08-25.
**Phase 2** (feed vol_state into the regime prompt) — blocked on accumulating real vol_state data
first; not started. **Phases 4-6** (event-driven refresh, ALLOW/TIGHTEN/BLOCK policy, gap_fade
catalyst classifier) — not started.

Same session also closed all 3 outstanding bugs from the 2026-08-25 external audit round
(`_reconcile_positions()` net-qty check, `update_combined_csv()` corruption quarantine,
`load_regime_today()` version check) — full writeups in `docs/strategy_graveyard.md` "Fixed Bugs".

---

## Current status (update this line as phases advance)

**⚠️ 2026-08-29 — BOTH ROUTES PARKED behind `docs/PLAN.md`** (the single active plan; the audit
that caused this is written up in `docs/research-reset.md`). An audit found the live
portfolio's weighted edge is +1.31 bps across 106 trades, inside the project's own 1–3 bps cost
band, on frictionless fills — no demonstrated edge, and the reporting layer can't reveal it (no
cost model, no dollar accounting, no benchmark, no CIs). Adding more strategy/AI surface (Route 2b
Phases 2–6) on that base was judged the wrong move. New priority: rebuild measurement (Goal A),
then expand the replay universe (Goal B) using the 97 free `history_kl_quota` slots so strategies
reach significance in days rather than the ~26 weeks the 3-symbol design implies. Route 2b Phase 1
keeps collecting `vol_state.jsonl` for free in the meantime. The status below remains accurate for
what was completed; it is just no longer what to work on next.

**Route 1 is COMPLETE (Phase 5 ✓ 2026-08-09) — H1 null, H2 VIX filter deployed+OOS confirmed,
H3 autocorr parked until 2027+ data. No further build work needed for Route 1.
Route 2 is in Phase 4 — regime gate live with corrected skip labels since 2026-07-26
(trending_up/trending_down block ~23% of days). Replay test coverage complete (2026-08-09).
Accumulating live sessions toward the 10-session gate. ORB scorer stays shadow-mode.
The Phase 4 PF evidence was re-verified 2026-08-25 after a PF-pooling bug fix in
`validate_regime.py` — number changed (0.513→0.813) but verdict held, gate stays enabled.
Route 2b (volatility engine) is a new, separate-but-related track started 2026-08-25 — see section
above and `route-2b-volatility-engine.md`. Phase 1 done, data accumulating, nothing live yet.**

**Next is NOT in this file.** Both routes are parked; `docs/PLAN.md` holds the ordered work.
Route 2b Phase 2 reopens after PLAN.md Step 12; Route 2 Phase 5 (the gate keep/remove/tune
decision) is behind PLAN.md Step 1, since it is a gate evaluation and the gates do not yet say
whether they mean gross or net PF.

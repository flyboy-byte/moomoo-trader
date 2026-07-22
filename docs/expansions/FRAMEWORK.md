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

### Phase 2 — Validation

- [ ] Run at least one `scripts/mine_*.py` script and get a non-trivial result
      (confirms the research loop infrastructure actually works end-to-end)
- [ ] At least one hypothesis tested with real data output — kill it or advance it

**Gate to Phase 3:** one working mining script producing interpretable results.

### Phase 3 — Build

- [ ] First mining script written: `scripts/mine_first_bar.py` (H1 — 9:30 bar predictive?)
- [ ] Second: `scripts/mine_autocorrelation.py` (H3 — lag-1 autocorr by time-of-day)
- [ ] Extend `scripts/backtest_gap_fade.py --sweep-vix` (H2 — gap × VIX band)
- [ ] Any finding with PF ≥ 1.2 + ≥ 100 OOS trades wired into a new `_eval_*` or filter

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

### Phase 2 — Validation

- [ ] Anthropic API key obtained and tested (one manual call to claude-haiku-4-5)
- [ ] `scripts/classify_regime.py` returns a valid JSON label for today's date
- [ ] Prompt produces stable, sensible labels across a range of synthetic inputs
      (e.g. high-VIX / low-VIX / futures-gap-up — do the labels make economic sense?)

**Gate to Phase 3:** at least one successful API call with a sensible structured output.

### Phase 3 — Build

- [ ] `mm/morning_regime.py` — `classify_regime()` + `_load_regime_today()`
- [ ] `mm/config.py` — `anthropic_api_key`, `regime_gate_enabled`, `regime_skip_labels`
- [ ] `mm/evals.py` — `_load_regime_today()` helper + regime gate in `_eval_bb_kdj`
- [ ] `scripts/classify_regime.py` — standalone runner
- [ ] Shadow mode running: classifies daily but never blocks entries (log-only)
- [ ] VPS `.env` updated with `ANTHROPIC_API_KEY` + `REGIME_GATE_ENABLED=false` (shadow)
- [ ] VPS cron: 9:20 ET daily call to `scripts/classify_regime.py`

**Gate to Phase 4:** shadow mode running cleanly for at least 5 trading sessions.

### Phase 4 — Verify

- [ ] 2-week shadow log reviewed: do regime labels correlate with actual session outcomes?
- [ ] `REGIME_GATE_ENABLED=true` flipped after shadow period, PF trend monitored
- [ ] `tests/test_replay.py` covers: regime=choppy → entry skipped; regime=neutral → entry fires
- [ ] Fail-open confirmed: delete regime file, confirm no trades are blocked

**Gate to Phase 5:** gate has been live for ≥ 10 trading sessions with no blocking incidents.

### Phase 5 — Formalize

- [ ] Regime label accuracy assessed (does choppy/trending_* predict anything?)
- [ ] Gate kept/removed/tuned based on evidence
- [ ] Decision documented in `docs/strategy_graveyard.md` or `docs/evaluation_criteria.md`
- [ ] Update `docs/expansions/route-2-llm-signals.md` with status and conclusion

---

## Current status (update this line as phases advance)

**Both routes are in Phase 1 (scoped, not yet built). Next single action: get an
Anthropic API key and run one test call — that's the fastest way to learn if Route 2
is a 1-hour build or a 1-day build. Route 1 can start in parallel by writing
`scripts/mine_first_bar.py` against the existing candle CSVs.**

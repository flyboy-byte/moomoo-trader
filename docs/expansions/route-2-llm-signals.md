# Route 2 — LLM Signal Layer (Claude API)

**Status:** Phase 3 — shadow mode live (as of 2026-07-22)
**Priority:** High (primary candidate)

---

## What's Built

### Phase 1: Morning Regime Gate (live, shadow mode)

`mm/morning_regime.py` — `classify_regime()` calls `claude-haiku-4-5` once per day at 9:20 ET
with prior-session stats + VIX. Writes `logs/regime_YYYY-MM-DD.json`.

Labels: `trending_up | trending_down | choppy | risk_off | neutral`

`mm/evals.py` — `_regime_gate()` checks the label before every bb_kdj / bb_kdj_loose entry.
Shadow mode (`REGIME_GATE_ENABLED=false`): logs `regime_gate_shadow` without blocking.

VPS cron: `20 13 * * 1-5` (9:20 ET Mon–Fri).

**Shadow period:** ~2 weeks. After observing labels vs actual session outcomes, flip
`REGIME_GATE_ENABLED=true` in VPS `.env`. No code change needed.

---

## Phase 2: ORB Setup Scorer (planned)

### What

Before entering an ORB trade, call Claude with the specific setup context and get a
confidence score. Only enter if confidence ≥ threshold. This runs **per trade**, not
once per day — Claude is in the direct entry decision path, not just an ambient label.

### Why this is different from the morning gate

The morning gate is session-level: "is today a good day for mean reversion?"
The ORB scorer is trade-level: "is THIS specific breakout worth taking?"

Input fed to Claude per entry:
```
Date: 2026-07-23
Symbol: US.SPY
VIX prior close: 16.64 (normal)
Prior session: SPY -0.12%, range 0.8%
Opening range: high=547.20 low=545.80 (range=1.40 = 0.26% of price)
Breakout direction: LONG (close 548.10 > OR high)
Volume ratio: 2.3× 20-bar MA (elevated)
Time since open: 32 min (cutoff=15 min)
Morning regime: neutral (confidence=0.72)
```

Output:
```json
{"confidence": 0.78, "reason": "Moderate-size OR with strong vol surge on calm VIX day, neutral regime — solid long setup."}
```

Gate: only enter if `confidence >= ORB_ENTRY_MIN_CONFIDENCE` (e.g. 0.65).

### Architecture

**`mm/morning_regime.py`** — add `score_orb_setup(setup_dict) -> dict`:
- Builds a short structured prompt from the setup dict
- Returns `{"confidence": float, "reason": str}` or `{"confidence": 0.5, "reason": "unavailable"}` on any failure (fail-open)
- Cached per (symbol, bar_ts) — never call twice for the same bar

**`mm/evals.py`** — `_eval_orb()` entry branch:
```python
if cfg.orb_setup_scorer_enabled:
    result = score_orb_setup(setup_dict)
    if result["confidence"] < cfg.orb_entry_min_confidence:
        elog.signal_skip("orb_claude_score", ..., confidence=result["confidence"], reason=result["reason"])
        return position
```

**`mm/config.py`**:
```python
orb_setup_scorer_enabled: bool = _bool("ORB_SETUP_SCORER_ENABLED", False)
orb_entry_min_confidence: float = float(_get("ORB_ENTRY_MIN_CONFIDENCE", "0.65"))
```

**Shadow mode first** — same pattern: `ORB_SETUP_SCORER_ENABLED=false` logs the score
without blocking. Review distributions before going live.

### Cost estimate
- ~300 tokens input + ~50 tokens output per call at haiku-4-5 pricing
- ~1–3 ORB setups per day across 3 symbols → trivial cost

### Evaluation
After 30+ scored entries in shadow mode:
- What's the score distribution? (Flat = the scorer isn't discriminating)
- Does confidence correlate with outcome? (Plot score vs pnl per trade)
- Set the threshold at the point where trades below it are net-negative

---

## Phase 3: Weekly Synthesis (planned)

### What

Every Monday morning at 9:00 ET, Claude reads last week's JSONL events and produces
a structured weekly assessment. This closes the feedback loop: the same model that
labels regimes can see what actually happened after each label.

### Why this matters

Right now the regime gate is one-way: Claude labels the day, and we can manually check
if the label was right. The weekly synthesis automates that: "here's what you predicted,
here's what happened — what do you notice?"

### Architecture

**`scripts/weekly_synthesis.py`** — runs Monday 9:00 ET:
1. Reads last week's JSONL events: trades, signal_skips, regime labels
2. Builds a compact summary (one row per trade: date, symbol, strategy, regime_label,
   outcome, pnl, hold_bars, exit_reason)
3. Calls Claude with that summary + a prompt asking for structured analysis
4. Writes `logs/synthesis_YYYY-WW.json` (ISO week number)
5. Posts to Discord via `mm/notifications.py`

**Prompt asks Claude to identify:**
- Strategies that worked vs didn't this week
- Which regime labels correlated with good/bad outcomes
- Whether any day had a regime label that looks wrong in hindsight
- One concrete recommendation (if it has enough data — otherwise "more data needed")

**Output:**
```json
{
  "week": "2026-W30",
  "summary": "ORB struggled all week (7 TIME_STOPs, -$8.81). bb_kdj_loose positive. Regime was 'neutral' all 5 days — labels may be too conservative; all VIX readings 16–18.",
  "recommendations": ["Consider lowering ORB VIX max threshold if VIX is consistently <20", "bb_kdj_loose is the bright spot — worth watching for 2 more weeks"],
  "flag_regime_labels": [],
  "data_quality": "5 days / 38 trades — early data, low confidence on any single conclusion"
}
```

**`install_cron.sh`** — add: `0 13 * * 1` (9:00 ET Monday)

### Value

This is the cheapest "analyst" that runs every week without being asked. The summaries
accumulate and become a research log of what was tried and what the model thought about it.

---

## Phase 4: Intraday Regime Refresh (low priority, future)

If morning confidence < 0.6 (borderline classification), re-classify at 12:00 ET using
the first 2.5 hours of actual price action as additional context. Only runs when confidence
was low, so API calls stay rare.

Hold off until Phase 2 and 3 are running and showing value.

---

## Execution Order

| Phase | What | Status | Effort |
|---|---|---|---|
| 1 | Morning regime gate (session-level) | Live, shadow mode | Done |
| 2 | ORB setup scorer (per-trade confidence) | Not started | ~2h |
| 3 | Weekly synthesis | Not started | ~1h |
| 4 | Intraday regime refresh | Future | — |

Do Phase 2 first — it's the highest-signal addition (Claude in the entry decision,
not just as background context). Phase 3 is an hour of work and closes the feedback loop.

---

## Config Reference

```
# Phase 1 (live)
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
REGIME_GATE_ENABLED=false              ← flip to true after shadow review
REGIME_GATE_STRATEGIES=bb_kdj,bb_kdj_loose
REGIME_SKIP_LABELS=choppy,risk_off

# Phase 2 (when built)
ORB_SETUP_SCORER_ENABLED=false         ← shadow mode first
ORB_ENTRY_MIN_CONFIDENCE=0.65
```

## Risks and Notes

- All Claude calls fail-open. Missing file or API error = proceed normally.
- API key in `.env` only. Never committed.
- `claude-haiku-4-5` is the right model here — fast, cheap, structured JSON output.
- Strip markdown fences before `json.loads()` — haiku wraps JSON in ` ```json ``` ` despite system prompt.

# Risks

> **Tier:** Mixed — scope/dependency/legal sections are high-level (decision-maker);
> technical/operational sections are low-level (implementer) · **Use when:** before
> committing to the approach (scope/legal), before scaling (operational), and as a
> running check during build (technical).

---

## Route 1 — Data Mining

### Scope / dependency risk

**All three hypotheses come back null.** The most likely outcome. If the 9:30 bar
isn't predictive, intraday autocorrelation is flat, and VIX bands don't segment gap
fade success — that's a valid scientific result. Mitigation: treat nulls as documented
findings in `strategy_graveyard.md`, then generate 3 more hypotheses from looking at
the data distributions directly (not from intuition).

**In-sample overfitting.** Finding an edge on the same data used to look for it is not
a finding. Every result needs OOS validation on a held-out date range. The OOS check
must happen before calling anything a finding — not as an afterthought.

**Candle coverage gaps.** The combined CSVs are built from rolling-archive merges.
There may be gaps (VPS only keeps a rolling archive; local has the long history). Any
mining script that relies on full daily coverage must handle missing days gracefully
and report coverage statistics.

### Legal / licensing risk

None. All data is self-fetched from Moomoo/OpenD (own account, own data). No
third-party data license at risk. Mining is offline; no redistribution of data.

### Technical risk

**Time-key alignment bugs.** The 5-min bars use Eastern Time, but the CSVs were
fetched with `extended_time=True` which includes pre-market bars starting at 4:00 ET.
A mining script that assumes "first bar of the day = 09:30" will silently pick the
4:00 bar on most days. Fix: always filter by `time_key.dt.time >= time(9, 30)` when
looking for RTH-open bars.

**Lookahead in feature computation.** If a mining script computes a "session return"
using the closing price of a bar that's in the same window being conditioned on,
the result will overstate predictiveness. Fix: use strictly sequential windows
(e.g. condition on 9:30–9:35 bar, measure 10:00–11:00 return with no overlap).

**Small-day-count problem.** 2 years of trading days ≈ 500 days. Some hypotheses
will produce small N (e.g. "days where gap > 1% AND VIX > 25" might be 20 days).
Report sample sizes in every output table. Don't call anything significant at N < 30.

### Operational risk

Low. Mining scripts run offline, don't affect live systems, and can be deleted if
they're wrong. The only operational commitment is: any deployed `_eval_*` must have
a replay test before going live (already the standard for all strategies).

---

## Route 2 — LLM Signal Layer

### Scope / dependency risk

**Anthropic API availability.** The morning classify call (9:20 ET) has a hard
dependency on `api.anthropic.com` being reachable from the VPS. The API has very
high uptime historically but isn't zero-downtime. **Mitigated by fail-open default:**
if the API call fails for any reason (network error, API error, malformed response),
`_load_regime_today()` returns "neutral" and all entries proceed as normal.

**Prompt drift.** The regime label depends on the exact prompt wording. Changing the
prompt changes what "choppy" means. This makes historical label comparisons
meaningless across prompt versions. Mitigation: stamp the prompt version (a hash or
date) in the output JSON file, so a prompt change is traceable.

**Scope creep.** Once a regime label exists, it's tempting to use it for more and more:
scale position size, change the ATR stop multiplier, pick symbols. Keep the gate narrow:
in the initial build, it only blocks entries for the strategies listed in
`REGIME_GATE_STRATEGIES`. Any expansion requires a new shadow-mode period.

### Legal / licensing risk

None. Sending pre-market macro context (VIX level, futures premium, prior close) to
the Anthropic API for classification is standard API usage. No market data redistribution
is involved. The VIX number and prior close are derived from self-fetched data.

*Note: Reasoning here is not legal advice. If the project were ever commercialized or
involved redistributing outputs derived from licensed data, that would need actual
legal review.*

### Technical risk

**Structured output reliability.** `claude-haiku-4-5` is highly capable but a
structured JSON prompt can still return malformed output under edge cases (very
unusual macro context, model updates). Mitigation: wrap the JSON parse in a
try/except; on any parse failure, log the raw response and return "neutral."

**Module-level config bind (the most common architectural bug in this codebase).**
Any new module that imports `from .config import cfg` at module level will get a
stale config after `_reload_paper()` runs in tests. `mm/morning_regime.py` and the
`_load_regime_today()` helper MUST use `from . import config as _config` + access
`_config.cfg.*` inside functions. This has bitten strategy.py, backtest.py, and
research.py already (fixed 2026-06-18).

**evals.py exit-branch ordering.** The regime check must NOT precede the exit branch.
Current structure in every `_eval_*` function:
```
1. if position is not None: [handle exits]  ← ALWAYS runs
2. elif not already_entered and [entry guard]: [entry logic]  ← regime gate goes here
```
A regime gate placed before step 1 would leave open positions unmanaged on
"skip" days. This is a correctness bug, not just a performance one.

**Replay test coverage gap.** The regime file needs to exist (or deliberately not
exist) for replay test runs to work correctly. The test harness must either:
a) write a synthetic regime file to the test's log directory before replaying, or
b) rely on the fail-open behavior (no file = neutral). Both paths must be tested.
See `docs/infrastructure.md` for the three required test cases.

### Operational risk

**Morning cron reliability.** The VPS cron (9:20 ET daily) must fire before market
open AND the paper runner's first eval cycle. If it fires late or fails silently,
the day runs without a regime file and falls back to "neutral" (acceptable, but the
gate doesn't engage). Mitigation: log the classify call result to the existing
`paper.log` or a dedicated `regime.log` so late/failed calls are visible in
`scripts/diagnose_logs.py` output.

**API cost creep.** At < $0.01/day, cost is currently irrelevant. If the prompt is
ever extended significantly (e.g. adding full macro calendar text), verify the token
count stays below 1000 tokens/call before deploying.

**Model version drift.** If `claude-haiku-4-5` is deprecated and a new model version
changes label behavior, shadow mode must be re-run before re-enabling the gate.
Pin the model ID in config (`ANTHROPIC_MODEL=claude-haiku-4-5`) so a model change
requires an explicit config edit, not just an API-side update.

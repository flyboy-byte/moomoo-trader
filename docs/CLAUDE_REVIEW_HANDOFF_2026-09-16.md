# Claude Review Handoff — 2026-09-16

This document is a handoff for the next Claude session reviewing the Moomoo project. It records
the current interpretation of the project, the recent review, and the work that should happen
next. It is advisory context; `docs/PLAN.md`, `docs/evaluation_criteria.md`, and the safety rules
remain authoritative.

## Executive summary

Moomoo is a personal, paper-only trading research laboratory built with substantial AI assistance.
It is not intended to be a real-money system, a general trading framework, or a publishable
research paper. Its purpose is to run strategies continuously, validate execution and data
plumbing, test hypotheses, and learn whether any measured edge survives realistic costs and honest
evaluation.

The engineering result is strong. The research result is still open. The runner has operated for
months and the project has found and fixed real bugs in fill confirmation, reconciliation,
timestamps, day-boundary handling, data preservation, duplicated metrics, reporting, and AI
integration. Those fixes materially improve the quality of future evidence.

The current live-paper sample does **not** demonstrate a trading edge. Local logs through
2026-08-24 contain 102 completed trades:

| Measure | Gross | Net under current model |
|---|---:|---:|
| Total PnL | +$12.92 | -$0.57 |
| Profit factor | 1.189 | 0.992 |
| Average PnL/trade | +$0.127 | -$0.006 |
| 95% PF interval | [0.663, 2.167] | [0.545, 1.782] |
| Bootstrap P(mean > 0) | 0.72 | 0.48 |

The correct interpretation is: the apparent profit disappears under the current cost assumptions,
and the sample is too small and uncertain to establish either success or failure. The phrase “the
profit was the transaction costs” is rhetorically strong; the more precise claim is “the apparent
profit disappears under the modeled costs.”

## What the project is doing well

- It has a real multi-strategy paper runner with persistent logs, position state, reconciliation,
  kill switches, risk limits, and Discord reporting.
- The replay harness exercises the real runner path, rather than only a separate simplified
  backtester.
- The project records failed ideas and null findings in `docs/strategy_graveyard.md`.
- Evaluation criteria and a knob-freeze process exist, so strategy changes are not supposed to be
  made merely because a short sample looks disappointing.
- The reporting layer now has one canonical trade reconstruction and displays gross and net views,
  confidence intervals, capital return, and benchmarks.
- External/adversarial audits have led to concrete fixes instead of only producing abstract advice.

The strongest honest portfolio/showcase claim is:

> Built and operated a multi-strategy paper-trading research system, then audited its execution,
> data, and measurement layers closely enough to expose and correct several hidden failure modes.

Do not describe the strategies as validated profitable systems yet.

## What remains uncertain

1. The live sample mixes configuration eras and historical tuning decisions. Months of uptime are
   not equivalent to months of testing one frozen hypothesis.
2. The proposed 2024+ untouched test window has already been examined during earlier tuning. It can
   be used for development/robustness work, but should not be called a clean untouched confirmation
   set.
3. More symbols will increase observations, but correlated same-day ETF trades are not independent
   evidence. Any wide scan needs day-clustered uncertainty and a pre-registered selection rule.
4. The AI regime gate is an interesting engineering experiment, but its value must be judged by a
   counterfactual comparison against the same opportunities without the gate and against a simple
   deterministic baseline.

Update after the original handoff: the VPS logs were subsequently pulled and reviewed, Steps 0/0b
were completed, net PF was adopted as the gate ruler, a forward cohort beginning 2026-09-17 was
declared, and PLAN.md Step 2 wired costs into all fast engines and replay. See the top of
`docs/strategy_graveyard.md` and the active plan for the current state. A later 2026-09-16 pass
also completed Step 3 and pulled Step 8 forward: the 97-symbol universe and return-independent
per-symbol cost table are frozen without spending OpenD quota. Step 4 then added day-blocked
uncertainty for pooled-symbol reports; the active plan now starts at Step 5 (fast-engine versus
replay cross-validation).

### Session update — paused Step 5 run

The next Codex pass implemented the first part of Step 5 and started the preregistered replay. The
run used the frozen local SPY/QQQ/IWM five-minute CSV snapshots from 2026-01-02 through 2026-06-09,
`fill_mode=instant`, and the four in-scope strategies: `bb_kdj`, `orb`, `vwap_pb`, and `gap_fade`.
It drove the real `mm.paper` evaluation path and wrote replay JSONL events under
`/tmp/moomoo_cross_replay`. It did not contact the VPS, change `.env`, restart services, or place
orders.

The run was stopped partway through (around 2026-03-09) because the real-path replay was taking
roughly an hour. Its partial output is not a valid cross-validation result and must not be used as
one. The reason it was slow is structural: each five-minute bar re-enters the full runner path,
including indicator windows, persistence, and risk bookkeeping.

Before rerunning, resolve three known semantic mismatches exposed by the setup:

1. The fast ORB engine does not model the live `ORB_LATEST_ENTRY=12:30` cutoff or the live SPY-only
   short-symbol allowlist.
2. Replay output does not currently seed the external VIX/regime context, so some gates fail open
   or behave differently from the fast pass.
3. Replay uses live quantity sizing while fast engines use one share. Comparison must normalize
   replay P&L to one share before applying the frozen per-symbol cost table.

`scripts/compare_engine_results.py` and `tests/test_compare_engine_results.py` were added locally;
the three tests pass. The script compares fast JSON with replay JSONL, performs one-share
normalization, applies the preregistered 2% trade-count and 0.05 net-PF gates, and reports aggregate
and per-symbol diagnostics. These two files are currently uncommitted because the automatic Git
approval layer rejected the elevated commit/push after the account hit its usage limit.

The existing fast-engine aggregate for the preregistered window is preserved at
`/tmp/moomoo_fast_results.json` for the current machine only. Its net PF values were: bb_kdj 1.022
(27 trades), orb 1.206 (241), vwap_pb 1.823 (80), and gap_fade 1.042 (92). These are development
results until the semantic alignment and replay comparison are complete.

## Recommended forward path

### Immediate: make the next review decision-oriented

Pull the current VPS logs when network access is available. Verify the deployed revision, active
strategies, configuration changes, uptime, reconciliation errors, unfilled orders, and latest
trade counts. Split the history at material behavior/configuration changes. Produce a one-page
table for each strategy with:

- current configuration/version and date range;
- completed trades, win rate, gross and net PnL/PF;
- cost sensitivity;
- execution quality and fill anomalies;
- whether an evaluation gate has actually been reached;
- the next action: continue, investigate execution, or review the strategy.

This is the missing output from the current “pull logs, fix bugs, keep running” cycle.

### Next engineering milestone: finish the measurement ruler

Continue the ordered work in `docs/PLAN.md` through the measurement/replay checkpoint. Cost-aware
engine and replay summaries are complete; remaining work begins with the wider-universe cost model,
then clustered uncertainty and engine cross-validation:

- make per-symbol cost assumptions explicit before a wide scan;
- use block/day-clustered bootstrap intervals for pooled cross-symbol reports;
- cross-validate fast engines against replay with a written tolerance;
- resolve the historical-data adjustment/seam behavior before spending quota.

Do not change live strategy knobs as part of this work. Do not expand the universe until the
measurement gate is genuinely complete.

### Then: freeze a clean research cohort

Choose and document a fixed configuration and a forward-only evaluation start date. Treat prior
data as development data because it has been repeatedly inspected. Keep the existing runner
running for execution validation, but identify a clearly labeled cohort whose results will answer a
specific question.

### Then: expand carefully, if still worthwhile

Use the available history quota only after the universe, cost method, date split, finalist count,
and multiple-testing rule are written down. Treat added symbols primarily as replication tests,
not automatically as independent samples. Report each symbol against its own buy-and-hold
benchmark and use clustered uncertainty when pooling.

### AI work

Keep the existing regime/volatility work in shadow or bounded mode until the baseline measurement
is trustworthy. The key test is incremental value: on identical opportunities, compare no gate,
the deterministic baseline, and the AI gate. Log enough counterfactual information to make that
comparison later. Do not grant the model arbitrary position sizing, prices, stops, or live-order
authority.

## Operating stance

Continue running the paper system. Continue fixing bugs that affect execution, data integrity,
safety, or the validity of conclusions. A clean health review is a successful review and does not
require a strategy change.

For strategy changes, preserve the current baseline and make the change an explicit experiment.
Record the hypothesis, date, configuration/version, affected data window, and decision rule before
looking at the result.

The project should optimize for learning per unit of attention, not for accumulating features or
keeping the dashboard busy.

## Constraints to preserve

- `TRD_ENV=SIMULATE` always.
- `LIVE_TRADING_ENABLED=false` always.
- Never add a live-order path.
- Do not store secrets in code or git.
- Do not restart or modify OpenD casually; the installed version is known to work.
- Do not silently retune existing strategy parameters.
- Do not treat gross PF as the primary result when net costs are available.
- Do not treat a short paper sample, a backtest winner, or plausible AI labels as proof of edge.

## Concrete brief for the next Claude session

Please review this handoff and the authoritative files it names. Then:

1. Pull and inspect the latest VPS logs if connectivity is available; otherwise state exactly what
   could not be verified.
2. Establish the current deployed state and split the data at material config/behavior changes.
3. Produce the one-page per-strategy decision table described above.
4. Review the “Session update — paused Step 5 run” section. Do not treat the partial replay output
   as a result. Inspect the two new comparison files and commit/push them if the Git approval limit
   has cleared.
5. Make the smallest coherent semantic-alignment fix for the fast/replay comparison, without
   changing live behavior. Prefer a targeted test or shortened validation window before another
   full replay.
6. Only after alignment, rerun the preregistered comparison and record pass/fail numbers in the
   graveyard. Do not relax the written 2% / 0.05 gates after seeing results.
7. Inspect the remaining `docs/PLAN.md` measurement steps and identify the smallest coherent batch
   that can be implemented and tested without changing live behavior.
8. Implement that batch only if the evidence supports it, run the relevant tests, and update the
   plan/graveyard with dated findings.
9. End with a recommendation about whether to keep accumulating, investigate execution, retire a
   lane, or begin a frozen research cohort.

Keep the review grounded in the project’s actual purpose: a serious personal learning and research
system that is allowed to discover a null result. The goal is a trustworthy answer, not a profitable
looking report.

## Files to read first

- `CLAUDE.md` — project orientation and safety constraints
- `docs/PLAN.md` — active ordered plan
- `docs/evaluation_criteria.md` — gates and knob freeze
- `docs/research-reset.md` — Goal A evidence archive and measured numbers
- `docs/strategy_graveyard.md` — findings, bugs, parked questions, and methodology
- `docs/ARCHITECTURE.md` — deployed strategies and runtime data flow
- `docs/expansions/FRAMEWORK.md` — status of mining, regime, and volatility routes

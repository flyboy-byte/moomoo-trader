# Codex Grand Audit

Date: 2026-06-19

Author: Codex

## What this file is

This is a read-only review of the repo as it exists today. It is not a rewrite plan,
not a demand list, and not a claim that everything below is equally urgent.

The goal is to capture:

- what looks stronger than before
- what still looks structurally weak
- what seems strategically promising
- what could become confusing as the repo grows
- what an AI coding workflow is likely to struggle with later if the project keeps scaling

This file intentionally mixes engineering audit, strategy review, documentation review,
and AI-context review, because those are now interacting with each other in a meaningful way.

## Overall read

The project is in a better state than a lot of trading repos reach.

It is no longer just "a bot with ideas." It is starting to look like a research system
with memory, bug history, and some discipline about evidence. That matters. Many of the
project's best qualities are no longer in the raw strategy code alone, but in the way the
repo now records mistakes, invalidates old conclusions, and preserves reasoning.

The strongest positive shift is not a single feature. It is that the repo has become more
intellectually honest:

- bugs are being written down instead of buried
- backtest expectations are being corrected when wrong
- strategy gates exist before enough live data arrives to tempt post-hoc rationalization
- the architecture is less monolithic than it was

The main caution is that the next failure mode is changing. Earlier, the repo's danger was
"wrong logic hidden in one big file." Now the larger danger is "too many truth surfaces,"
where code, docs, project maps, audit docs, and AI summaries all become partially authoritative
at once.

That is not a crisis yet. But it is the next thing to watch.

## Physical size of the codebase

At the time of this review:

- files across `docs/`, `mm/`, `scripts/`, and `tests/`: about 86
- total lines across those areas: about 21,826

That is not especially large in absolute terms. A good engineer or coding model can still
reason about a repo this size without needing industrial context machinery.

The project is not "too big for AI" yet.

What matters more than raw line count is where the weight sits.

Largest high-signal files observed:

- `scripts/web_dashboard.py` — 967 lines
- `scripts/analyze_trades.py` — 628 lines
- `mm/research.py` — 618 lines
- `mm/evals.py` — 576 lines
- `scripts/dashboard.py` — 571 lines
- `docs/PROJECT_MAP.md` — 459 lines
- `docs/strategy_graveyard.md` — 414 lines
- `mm/execution.py` — 409 lines
- `mm/replay.py` — 370 lines
- `mm/paper.py` — 340 lines
- `docs/codex-ai-size.md` — 389 lines
- `docs/codex-ai-size-remedies.md` — 316 lines

These are the places where human and AI context can start to thicken:

- large operational files
- large research files
- large narrative docs
- files that combine live behavior and historical explanation

## Abstract size vs physical size

The repo is still moderate in physical size, but its abstract size is larger than the line
count suggests.

Reasons:

- it has multiple strategies with different logic families
- it has both research and live-runner concerns
- it has a growing bug history that matters to interpretation
- it has several strong prose artifacts that shape how future readers think
- it has environment-sensitive behavior around Moomoo/OpenD

In other words: the project is not yet "big code," but it is becoming "thick context."

That is the point where AI coding quality can start to drift if the repo is handled with
large cloud summaries instead of sharp local grounding.

## What looks stronger now

### 1. The project is more self-correcting

`docs/strategy_graveyard.md` is one of the best things in the repo. Not because it is
dramatic, but because it records dead ends, contaminated conclusions, and post-mortems
without pretending the past was cleaner than it was.

That creates a real research memory.

### 2. Pre-registered evaluation discipline is a real strength

`docs/evaluation_criteria.md` is doing something valuable and uncommon: it tries to decide
in advance what evidence would matter, instead of letting results rewrite standards later.

That is strategically more important than another indicator or another entry filter.

### 3. The architecture is healthier than before

Breaking concerns into `mm/evals.py`, `mm/execution.py`, `mm/events.py`, and `mm/clock.py`
was the right move. The repo is no longer depending on one giant central runtime file to
hold all meaning.

### 4. Some earlier operational hazards appear improved

Observed examples:

- `start.sh` now respects `STOP_TRADING.txt` instead of bulldozing through it
- `/config` in the web dashboard is disabled if there is no dashboard password
- several known bug classes are now explicitly documented rather than only implicitly fixed

### 5. The repo has become more audit-friendly

There is enough logging, enough replay tooling, and enough written context that an outsider
can now reason about "what happened" without reverse-engineering everything from scratch.

That is a major maturity increase.

## Main open engineering concerns

### 1. Test hermeticity is still the biggest unresolved engineering weakness

This is the clearest structural problem still visible.

Core modules import `moomoo` at module import time, including:

- `mm/connection.py`
- `mm/data.py`
- `mm/execution.py`

In this environment, that vendor import path tries to write logs into a filesystem location
outside the workspace. That means `pytest` can fail during collection before meaningful tests
even run.

This is not just an inconvenience.

It weakens:

- trust in test gates
- trust in deploy verification
- speed of safe iteration
- ability to refactor internals confidently

If one issue deserves to be called "infrastructure debt with strategic consequences," this
is the one.

### 2. Dashboard exposure is improved but still worth scrutiny

The config editor is no longer casually exposed when no password is set. That is good.

But the broader dashboard still appears to be a live operational surface. Even if no config
editing is possible, observability itself can be a meaningful surface when the service is
sitting on a VPS.

This is less of a panic item than the test issue, but it still belongs in audit scope.

### 3. Runtime truth is still somewhat scattered

There is no single small factual machine-readable state artifact that says, for example:

- which strategies are active
- which are research-only
- current gate states
- known critical limitations
- latest verified test count
- highest-risk modules

Instead, the truth is spread across:

- code
- `.env`
- `PROJECT_MAP.md`
- `strategy_graveyard.md`
- `evaluation_criteria.md`
- audit docs

This works for now, but it is the beginning of context duplication risk.

### 4. Large mixed-purpose files still create context drag

Some files are not just long; they are broad in role:

- `scripts/web_dashboard.py`
- `scripts/analyze_trades.py`
- `mm/research.py`
- `mm/evals.py`

These are the kinds of files a coding model may partially understand, then overgeneralize
from. They are not necessarily bad files. They are just heavy context nodes.

## Documentation review

### What is good

The docs are unusually useful for a repo like this.

`docs/PROJECT_MAP.md` is strong as a broad orientation layer.

`docs/strategy_graveyard.md` is strong as research memory.

`docs/evaluation_criteria.md` is strong as anti-self-deception scaffolding.

Together, they make the project much more understandable than a code-only repo.

### What to watch

The docs are starting to form multiple overlapping narratives.

That is not automatically bad, but it can create these failure modes:

- a model trusts the most eloquent document instead of the freshest code
- an old metric survives in one doc after being corrected elsewhere
- "project truth" becomes prose-first rather than evidence-first
- future reviews spend time reconciling documents instead of inspecting behavior

`docs/MASTER_AUDIT_JUNE.md` is a good example of a useful but potentially heavy narrative
artifact. It contains strong claims, strong framing, and strategic imagination. That can be
helpful. It can also become gravitational if future sessions trust its framing too much.

The repo is now at the stage where documentation quality is no longer just "more docs good."
It becomes a curation problem.

## Strategy review

## General strategy impression

The project now has enough strategy surface area that the central question is no longer:

"Can this repo generate more ideas?"

It clearly can.

The better question is:

"Does this repo know which edge is real, which edge is fragile, which edge is execution-sensitive,
and which edge is redundant once portfolio overlap is considered?"

That distinction matters more than raw strategy count.

### ORB

Current impression: strongest backbone candidate.

Why:

- conceptually simple
- operationally legible
- easier to falsify than a heavily composite signal
- likely easier to monitor for execution degradation

Main caution:

- execution sensitivity is real
- slippage/fill quality matters more here than in a slower, mean-reversion-style idea

This looks like the strategy family most capable of being a foundation rather than just a
research curiosity.

### VWAP Pullback

Current impression: useful but narrower.

Why:

- it appears to have a cleaner niche
- it feels like a selective complementary strategy rather than a broad core framework

Main caution:

- it may be more fragile to market structure chop than its cleanest examples suggest
- symbol selection matters more here

This looks like a good satellite strategy if kept disciplined.

### BB+KDJ

Current impression: the most epistemically fragile active strategy.

That does not mean it is bad. It means it carries the highest risk of becoming a complicated
machine for explaining trades after the fact if not kept under strict audit.

Reasons for caution:

- more parameterized feel than ORB
- more room for subtle signal contamination or lookback mistakes
- easier to produce "plausible" but unstable explanations

The day-boundary KDJ-window issue reinforces this concern. The important lesson is not that
the strategy failed. The lesson is that this strategy family needs especially rigorous
boundary and interpretation checks.

### Gap Fade

Current impression: the most interesting next promotion candidate.

Not because it should automatically go live, but because it appears structurally different
from what is already deployed.

That matters.

New strategy value should not be judged only by stand-alone backtest appeal. It should also
be judged by whether it adds a distinct thesis to the portfolio instead of duplicating an
existing family with different decorations.

`mm/gap_fade.py` and `mm/premarket.py` suggest a line of work that is more than cosmetic.
It has its own structure, its own filters, and its own possible failure modes.

### General strategy hierarchy instinct

If forced into a rough hierarchy based on current repo shape:

- `orb` looks most like a backbone candidate
- `vwap_pb` looks like a selective complement
- `bb_kdj` looks worth keeping but under sharper scrutiny
- `gap_fade` looks like the most promising non-redundant next research promotion candidate

That is not a command. It is an audit impression.

## What is still worth auditing on strategy

If doing a deeper strategy-only pass later, these areas still matter:

### 1. Regime concentration

Not just whether a strategy is profitable overall, but whether most of the edge comes from:

- certain volatility regimes
- certain trend/range structures
- certain gap conditions
- certain times of day

If the edge is highly concentrated, the strategy is narrower than its aggregate metrics imply.

### 2. Symbol dependency

A strategy can look diversified across SPY, QQQ, and IWM while actually leaning on one market
behavior repeated three ways.

This is especially relevant for deciding whether multi-symbol deployment is genuine diversification
or just correlated duplication.

### 3. Live-vs-replay degradation by strategy family

These strategies should not be judged by one standard.

- ORB is highly execution-sensitive
- BB+KDJ is highly logic-sensitive
- VWAP PB is structurally/filter sensitive

The reason a strategy underperforms matters as much as the underperformance itself.

### 4. Distribution shape, not just average PnL

It is worth knowing whether a strategy wins because:

- many medium-quality trades behave consistently
- a small number of outsized winners carry the distribution
- losses cluster in identifiable conditions

### 5. Overlap cost

A strategy can be positive on its own and still not deserve a slot if it mostly activates
during the same bad windows as another strategy.

This is why portfolio analysis matters more now than idea generation.

## Portfolio-level review

This is probably the most important strategic layer that is still underbuilt relative to the
rest of the repo.

The project already has a decent amount of single-strategy reasoning. What it has less of is
live runtime portfolio governance.

The current analysis tooling is helpful:

- `scripts/analyze_portfolio.py` is already asking the right kinds of questions about overlap,
  correlation, drawdown, and combined daily behavior

But there is still a gap between:

- understanding portfolio effects after the fact
- enforcing portfolio constraints at the point of entry

That gap matters more with every additional strategy, every additional symbol, and every
additional layer of "good idea" complexity.

If the repo keeps growing, the portfolio layer is a higher-value system than a fourth or fifth
strategy.

## AI-coding and context-window review

The repo is not too large for vibe coding yet.

But there are clear future risks if context handling becomes lazy.

### What an AI is likely to get hung up on

#### Large mixed-role files

- `scripts/web_dashboard.py`
- `scripts/analyze_trades.py`
- `mm/research.py`
- `mm/evals.py`

These files contain enough logic and enough local conventions that a model can read them,
retain only the loudest themes, and miss edge cases.

#### Strong prose documents

- `docs/PROJECT_MAP.md`
- `docs/strategy_graveyard.md`
- `docs/MASTER_AUDIT_JUNE.md`
- this file and related Codex review files

These are useful, but they also create narrative gravity. Future models may over-trust them,
especially if the session relies on summary uploads instead of local repo inspection.

#### Environment-sensitive modules

- `mm/connection.py`
- `mm/data.py`
- `mm/execution.py`

These are dangerous in a different way: they do not just require understanding, they can
change behavior based on runtime environment and vendor integration.

### What would start making AI quality worse

- giant cloud summaries replacing local code reads
- duplicated truth across many docs
- no small factual state snapshot
- too many large files that mix research, runtime logic, and operational assumptions

### What would keep AI quality higher

- thin factual context artifacts rather than giant narrative summaries
- clearer separation between live code, research code, and archival explanation
- keeping the highest-risk operational files from growing indefinitely
- treating docs as indexed reference layers, not alternate realities

## Imaginative next-step ideas that still fit the project

These are not framed as instructions. They are possibilities that seem coherent with the repo's
current shape.

### 1. A portfolio governor

A runtime layer that evaluates:

- same-direction symbol clustering
- max concurrent exposure
- thesis concentration
- cross-strategy overlap risk

This feels more valuable than just adding another strategy.

### 2. A promotion pipeline for new strategies

Instead of treating strategy addition as mostly a research conclusion, create a path such as:

- research
- replay
- shadow logging
- regime attribution
- overlap scoring
- promotion to live paper

This would fit the repo's growing seriousness.

### 3. A truth dashboard focused on discrepancies

Not a PnL-first dashboard, but one centered on:

- replay vs live divergence
- stale config usage
- broker/local mismatch events
- suspicious signal boundary conditions
- execution anomalies

This would strengthen the "lab" aspect of the project.

### 4. A small machine-readable project snapshot

A generated file that states current facts:

- active strategies
- research-only strategies
- latest test count
- highest-risk open issues
- latest known audit date
- current key docs and their roles

This would help both humans and models without adding more prose weight.

### 5. Regime attribution before more alpha hunting

The project likely gets more value from learning exactly when each strategy works or fails
than from immediately adding another clever setup.

That is not anti-imagination. It is a better use of imagination.

## What feels most important now

If reducing today's review to a few high-signal impressions:

1. The repo is improving in the right ways.
2. The biggest unresolved engineering issue is still non-hermetic testability around Moomoo imports.
3. The biggest unresolved strategic issue is still portfolio-level governance.
4. The biggest future AI/workflow issue is not raw code size but context sprawl and narrative duplication.
5. The most interesting strategy direction is not "more of the same," but structurally distinct additions like Gap Fade, promoted carefully.

## Closing view

This project does not look stalled. It looks like it is crossing from "clever experimental bot"
into "small but serious research/trading system."

That transition changes what matters.

At the start of a repo like this, raw strategy ideas dominate.

At this stage, the more valuable assets are:

- testability
- truth discipline
- portfolio thinking
- strategy hierarchy
- context architecture

The project is not too large yet.

But it is large enough that the next gains probably come less from adding cleverness and more
from protecting clarity.

Signed,

Codex

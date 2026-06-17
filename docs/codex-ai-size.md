# Codex AI Size

Date: 2026-06-16

Author: Codex

## Purpose

This note describes the repo in two ways:

- physical size: file counts and line counts
- abstract size: how large and cognitively dense the project feels to an AI

It also calls out which files are most likely to confuse, overload, or mislead a vibe-coding AI.

## Executive Summary

This is a **mid-sized codebase** by raw implementation size, but it feels **denser than average** because it contains more than code.

It includes:

- strategy logic
- execution logic
- replay and diagnosis tooling
- operator workflow
- research history
- decision documentation

So the project is not huge, but it has more context weight than its line count alone suggests.

Short version:

- physical size: medium
- conceptual size: medium to medium-large
- emotional / attention weight to an AI: medium-high

## Physical Size

### Top-Line Counts

- `119` files across `mm/`, `scripts/`, `tests/`, and `docs/`
- about `20,297` total lines across those same areas
- `21` top-level files in the repo root

### By Area

| Area | Files | Approx. Lines |
|------|------:|--------------:|
| `mm/` | 50 | 6,477 |
| `scripts/` | 38 | 6,829 |
| `tests/` | 12 | 3,319 |
| `docs/` | 19 | 3,672 |

### Interpretation

This is not a tiny repo, but it is also not a giant system.

By raw implementation bulk, it sits in a practical middle zone:

- large enough that careless edits can cause real confusion
- small enough that one model can still understand the whole thing with discipline

## Largest Important Files

These are the largest files that matter most for context and behavior.

| File | Approx. Lines | Why It Matters |
|------|--------------:|----------------|
| `scripts/web_dashboard.py` | 957 | UI, auth, config editing, state rendering, runtime controls |
| `scripts/analyze_trades.py` | 626 | high-density research and post-trade analysis logic |
| `mm/research.py` | 599 | experiment and parameter exploration center |
| `mm/evals.py` | 537 | core strategy evaluation behavior |
| `scripts/dashboard.py` | 535 | terminal UI and session visibility |
| `tests/test_paper.py` | 444 | biggest behavioral test surface |
| `docs/PROJECT_MAP.md` | 428 | dense narrative source of truth / source of drift |
| `mm/execution.py` | 405 | fills, retries, reconciliation, order lifecycle |
| `mm/replay.py` | 369 | replay harness and truth-checking layer |
| `mm/paper.py` | 340 | runner orchestration hub and back-compat imports |

## Abstract Size

### How Big It Feels to an AI

The repo feels bigger than its raw line count because many files are carrying judgment, not just implementation.

Examples:

- strategy conclusions
- deployment assumptions
- failure history
- frozen evaluation criteria
- operator guidance

That gives the repo more **cognitive density** than a normal software project of similar size.

### AI-Scale Description

If I compress the feel into simple labels:

- raw code size: `medium`
- concept size: `medium to medium-large`
- attention weight: `medium-high`

### Why It Feels Larger Than 20k Lines

The answer is not “there is that much code.”

The answer is:

- the repo contains multiple kinds of truth
- the docs are important enough to affect decisions
- the code is tied to real operational behavior
- the strategy layer and the infrastructure layer both matter

So an AI is not just reading code. It is reading:

- software
- process
- research memory
- operational caution

That is why the repo feels denser than a generic 20k-line project.

## Where an AI Is Most Likely to Get Hung Up

These are the files most likely to overload or mislead an AI.

### 1. `scripts/web_dashboard.py`

Why:

- too many responsibilities in one place
- UI rendering
- login behavior
- config editing
- runtime controls
- state display

This is the kind of file where an AI can make a “small” change and accidentally affect security, runtime behavior, or operator workflow.

### 2. `mm/evals.py`

Why:

- it contains the live strategy decision logic
- it is branch-heavy
- multiple strategies live in the same file
- subtle changes can alter trade behavior without obvious errors

This is one of the easiest places for a shallow AI to break the real system while believing it is doing cleanup.

### 3. `mm/execution.py`

Why:

- broker-facing lifecycle logic
- order placement
- fill confirmation
- retries
- reconciliation

This is high-risk because the code can look straightforward while actually encoding painful live-paper lessons.

### 4. `mm/paper.py`

Why:

- it is still the orchestration hub
- it imports and re-exports a lot
- it looks smaller than its true influence

An AI may underestimate how many other files depend on its public surface.

### 5. `docs/PROJECT_MAP.md`

Why:

- it is dense
- it reads like source of truth
- it contains strong narrative framing

If the docs drift even slightly, an AI can anchor on an outdated explanation and then misunderstand the code.

## Files Most Likely to Mislead a Vibe-Coding AI

These are not always the biggest files. They are the files most likely to create false confidence.

### Dense Narrative Docs

- `docs/PROJECT_MAP.md`
- `docs/ARCHITECTURE.md`
- research-heavy markdown in general

Why:

- they summarize confidently
- they can lag behind implementation
- an AI may trust them too early

### Back-Compat Hubs

- `mm/paper.py`

Why:

- re-exports hide where canonical logic really lives
- an AI may patch the wrong file or misunderstand ownership boundaries

### Mixed-Responsibility Files

- `scripts/web_dashboard.py`
- `mm/evals.py`
- `mm/execution.py`

Why:

- too many concepts in one file
- local edits can have global consequences

### Research Files

- `mm/research.py`
- `scripts/analyze_trades.py`

Why:

- many paths
- many interpretations
- easy to overfit understanding to whichever experiment was read last

### Low-Signal Noise Files

Examples:

- `__pycache__`
- mirrored or deep-copy doc areas

Why:

- a naive scan may spend attention there
- they add volume without improving understanding

## What an AI Should Read First

If an AI wants to understand the repo cleanly, the best starting order is probably:

1. `README.md`
2. `docs/ARCHITECTURE.md`
3. `mm/paper.py`
4. `mm/evals.py`
5. `mm/execution.py`
6. `mm/risk.py`
7. `docs/evaluation_criteria.md`
8. `docs/PROJECT_MAP.md`

Why this order:

- start with broad intent
- then get the execution structure
- then get the strategy behavior
- then get risk logic
- then read the heavier narrative docs after the code shape is already grounded

## What Makes the Repo Feel Bigger Than It Is

The repo feels larger than normal because it is doing several jobs at once:

- strategy lab
- paper runner
- replay/diagnosis system
- operator manual
- research memory store

That is what drives the “AI size,” not raw code volume alone.

## Best Mental Model

The best simple description is:

**a focused, serious small trading lab with unusually high context density**

It is not:

- a toy repo
- a giant production platform
- a generic framework

It is a medium-sized system with a lot of embedded judgment.

## Final Take

If I reduce everything to one line:

**This repo is physically medium-sized, cognitively dense, and very manageable for an AI that reads carefully, but easy to misread for an AI that trusts docs too fast or edits mixed-responsibility files casually.**

## Vibe-Coding Risk

One important concern is not just repo size, but whether the repo is drifting into a state where AI coding quality depends on large cloud summaries instead of direct file understanding.

That concern is valid.

Once a repo starts needing giant context dumps just to stay coherent, vibe-coding quality usually drops. Not because the model is bad, but because the work shifts from:

- understanding local intent

to:

- juggling a compressed worldview that may already be stale

### Failure Modes

When that happens, a few things usually go wrong:

- the model starts trusting summaries over code
- old conclusions get repeated after the repo changed
- edits become more generic and less precise
- the model spends context budget remembering the system instead of solving the task
- every task starts paying a reload tax

### What Matters More Than Raw Size

For this repo, the main risk is not the raw `20k` lines of code.

The bigger risk is:

- too many overlapping summaries
- too much truth living in markdown
- mixed-responsibility files
- stale narrative docs that compete with live code
- loading global context when only local context is needed

The real failure mode is not “cloud summary upload” by itself.

The real failure mode is:

**the summaries become a parallel codebase in natural language**

That is when quality slips.

### Good Shape for AI Coding

What tends to work better:

- one short canonical project map
- one short operator/runtime note
- one strategy note per strategy if needed
- let code remain the source of truth for behavior
- load only the local area relevant to the task

### Bad Shape for AI Coding

What tends to reduce quality:

- huge monolithic project memory
- multiple docs saying similar things differently
- summaries that must be believed before touching code

### Threshold to Watch

This repo is not too big to vibe code yet.

But it is near the zone where **context architecture matters more than code size**.

The threshold I would watch is:

**a repo becomes hard to vibe code when understanding it depends more on memorized prose than on reading the files involved in the task**

That is the cleanest rule of thumb here.

### Practical Preservation Rules

If the goal is to preserve AI coding quality as the repo grows, these are the most useful habits:

1. Keep one canonical high-level map, not many competing ones.
2. Treat old summaries as disposable unless refreshed.
3. Prefer task-local reading over giant preload context.
4. Keep strategy conclusions separate from runner behavior.
5. Keep orchestration files from growing back into monsters.
6. Be suspicious whenever a model answers from repo memory instead of current file reads.

### My Read

This repo is still in a workable zone.

It does not feel “too big for AI.”

It feels like a repo where quality will be determined less by line count and more by whether the documentation stays disciplined enough that models can still rely on direct code reading instead of inherited narrative memory.

Reviewed by Codex

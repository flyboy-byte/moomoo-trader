# Codex AI Size Remedies

Date: 2026-06-16

Author: Codex

## What This Is

This is not an order.

It is a preventive design note: suggestions for how the repo could stay efficient, imaginative, and AI-friendly as it grows.

The point is not to force process onto the project.

The point is to avoid a very specific failure mode:

**the repo becomes small enough to edit, but too context-heavy to vibe code well**

That happens when code understanding depends more on giant summaries than on local file reading.

## Core Idea

The move is **not** to create bigger summaries.

The move is to make the repo so well-structured that an AI can stay local longer.

Said another way:

- do not scale understanding by increasing summary size
- scale understanding by reducing how much of the repo must be understood at once

That is the main idea in this document.

## What Seems to Be Wanted

Based on the repo and the concern expressed, the underlying goals seem to be:

- keep speed
- keep imagination
- keep vibe-coding useful
- avoid a prose-dependent monster
- avoid losing the project’s vision to context compression
- preserve room for creative development without making the repo chaotic

That means the project likely needs **context control systems**, not just more documentation.

## Main Risk

The main future risk is not raw line count.

It is that documentation and summaries become a parallel codebase in natural language.

When that happens:

- models trust prose over files
- stale conclusions linger
- the cost of starting any task rises
- edits become generic
- the repo starts feeling larger than it really is

That is the thing to prevent.

## Recommended Direction

### 1. Establish a Hard Source-of-Truth Hierarchy

Right now the repo has a lot of useful narrative. That is a strength, but only if each doc has a clear job.

Suggested hierarchy:

- `README.md`
  Public overview only.
  What the project is, how it works at a high level, and how to start.

- one canonical project map
  Current architecture and active facts only.
  No old research stories unless still operationally relevant.

- one operator/runtime note
  VPS, deploy, restart, kill-switch, and monitoring behavior only.

- strategy notes
  Why each strategy exists, what it is supposed to do, and what evidence currently supports it.

- archival / historical notes
  Graveyard ideas, old findings, post-mortems, exploratory reasoning.

Why:

This prevents multiple docs from competing to define “what is true now.”

### 2. Split Active Truth From Historical Memory

This repo has both:

- active system truth
- historical research memory

Those should stay separate.

Suggested rule:

- current behavior goes in active docs
- old experiments, invalidated assumptions, and dead ideas go in historical docs

Why:

AI gets confused when active instructions and historical explanation live in the same mental space.

### 3. Keep Modules Narrow

The strongest long-term AI aid is not better prompting.

It is better file boundaries.

Good direction already visible in the repo:

- strategy evaluation in `mm/evals.py`
- broker execution in `mm/execution.py`
- events/state in `mm/events.py`
- orchestration in `mm/paper.py`

Suggested rule:

- do not let orchestration files grow back into mixed-responsibility hubs
- do not let UI files quietly become full operator control planes
- do not mix research logic into runtime-critical modules

Why:

AI handles a project much better when each file means one thing.

### 4. Create Small Context Packs Instead of One Big Memory

Instead of one giant project summary, think in small packs:

- runner pack
- strategy pack
- dashboard pack
- replay / validation pack
- deployment / VPS pack

Each should be:

- short
- replaceable
- local to a task family

Why:

Most tasks do not need the whole repo worldview.

### 5. Watch for the “Too Big for Vibe Coding” Signals

The threshold is not file count alone.

The real warning signs are:

- more than 2-3 docs are needed just to start a task
- docs disagree often
- models answer from memory more than current file reads
- small changes require mentally reloading half the repo
- mixed-responsibility files keep regrowing
- summaries become mandatory instead of helpful

Once that starts happening, the repo is becoming too context-heavy, even if it is not huge.

### 6. Prefer Generated Facts Over Hand-Maintained Facts

Where possible, factual metadata should be generated rather than hand-kept in docs.

Examples:

- test counts
- file counts
- module counts
- largest files
- current strategy/config snapshots

Why:

Hand-maintained facts drift. Drift makes AI trust the wrong layer.

### 7. Add Lightweight Architecture Discipline

Not enterprise governance.

Just a few small rules that preserve clarity:

- no file should own both core behavior and presentation unless necessary
- new runtime behavior should have an obvious canonical home
- bug fixes should ideally update code, tests, and source-of-truth docs together
- long docs should either be split by role or demoted to archive/reference

Why:

This keeps the repo understandable without turning it into bureaucracy.

### 8. Separate Idea Space From Implementation Space

This matters if imagination is a concern.

The project should have one obvious place for:

- speculative strategy ideas
- future features
- weird experiments
- “maybe later” concepts

That place should not be the same place that defines active system truth.

Why:

If speculative ideas mix with current operational docs, AI starts treating ideas like commitments.

## What the Repo Seems to Need Most

Looking at the current codebase, the highest-value preventive systems appear to be:

### 1. Stronger doc hierarchy

The repo already has useful docs. The next step is to reduce role overlap between them.

### 2. Smaller canonical context surfaces

The project likely benefits more from a few short trusted maps than from large global summaries.

### 3. Generated fact surfaces

This would reduce narrative drift and lower the chance that AI trusts stale numbers.

### 4. Continued file-boundary discipline

The refactor direction is good. The main thing is not to undo it by convenience.

### 5. A clean archive/current split

This helps preserve both imagination and clarity.

### 6. Better test isolation from the real broker package

This matters because once tests are not trustworthy, both humans and AIs start compensating with story instead of proof.

## What Probably Matters Less Than It Feels Like

Some things are easy to worry about but are probably not the main threat yet:

- raw repo line count
- the existence of docs in general
- having multiple strategies
- having a research graveyard

Those are manageable.

The more important issue is whether the project can still be understood through local reads instead of summary dependence.

## Good Shape vs Bad Shape

### Good Shape

- one short canonical map
- one short runtime/operator note
- clear archive vs current split
- files with narrow responsibilities
- local task reading beats giant preloaded memory
- prose supports code instead of replacing it

### Bad Shape

- giant monolithic memory docs
- multiple overlapping “source of truth” files
- docs that must be believed before code is touched
- strategy history mixed into active operator docs
- orchestration files growing back into everything-files

## Practical Rules of Thumb

These are the simplest durable heuristics:

1. If a model can solve the task by reading 3-6 files, the repo is still in a good zone.
2. If a task needs 4 summaries before code reads start, the repo is drifting the wrong way.
3. If a doc explains current behavior better than the code reveals it, check for drift.
4. If a file is both important and mixed-responsibility, treat it as a future refactor candidate.
5. If a summary gets long, split it by role instead of making it broader.

## Best Preventive Principle

The single best principle to preserve AI coding quality here is:

**reduce required simultaneous understanding**

That means:

- smaller trust surfaces
- fewer overlapping narratives
- better module boundaries
- more task-local context

This is the most important design move.

## Final Take

This repo is not too big yet.

That is exactly why preventive structure is valuable now.

The best next move is not more memory. It is better context architecture:

- fewer competing truths
- smaller trusted maps
- stronger local module boundaries
- clearer separation of current behavior, historical research, and future ideas

If that happens, the repo can grow quite a bit further without losing speed or imagination in AI-assisted development.

Reviewed by Codex

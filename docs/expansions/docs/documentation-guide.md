# Documentation Guide

> **Tier:** Meta (about the docs themselves) · **Audience:** anyone new to this packet,
> including future-you after time away · **Use when:** you don't know which doc to open,
> or you're adding a new doc and need to decide where it fits.

This packet has two altitudes. Knowing which one you're reading prevents the failure
modes that hit planning docs specifically: vision docs with no path to build, and
build docs that bury the "is this worth doing" question under implementation detail.

## The two tiers

### High-level — the decision layer

**Question it answers:** *Should this exist, and is this the right way to build it?*  
**Written for:** the person deciding whether/how to pursue this.  
**Properties:** short enough to read in one sitting, states conclusions and open
questions plainly, doesn't require deep technical literacy to follow.

| Doc | What it's for |
| --- | --- |
| [`overview.md`](./overview.md) | What each route is, who/what it's for, why it exists |
| [`approach.md`](./approach.md) | Alternatives considered, tradeoffs, what to validate first |
| [`notes.md`](./notes.md) | Live scratchpad of open decisions |
| [`risks.md`](./risks.md) *(scope/legal sections)* | What could derail each route |

### Low-level — the build layer

**Question it answers:** *Given we're doing this, how does it actually get built?*  
**Written for:** whoever is implementing (currently: also you, same person).  
**Properties:** specific enough to act on directly — filenames, line-level guidance,
test cases spelled out.

| Doc | What it's for |
| --- | --- |
| [`infrastructure.md`](./infrastructure.md) | Tools, data sources, exact files to create/modify, test cases |
| [`risks.md`](./risks.md) *(technical/operational sections)* | What breaks in practice and the specific mitigations |

### Meta — the packet itself

| Doc | What it's for |
| --- | --- |
| [`FRAMEWORK.md`](../FRAMEWORK.md) | Phase-gated status tracker — the honest "where are we" |
| [`documentation-guide.md`](./documentation-guide.md) | This file — explains the tiers and how to add new docs |
| [`research-handoff.md`](./research-handoff.md) | Queue of unverified claims to send to deep research |

### Route files (adjacent, not part of the packet)

These live one level up in `docs/expansions/` and predate the packet:

| Doc | What it's for |
| --- | --- |
| [`../route-1-data-mining.md`](../route-1-data-mining.md) | Hypotheses, scripts to build, deployment criteria |
| [`../route-2-llm-signals.md`](../route-2-llm-signals.md) | Architecture sketch, shadow-mode rollout plan |
| [`../route-3-real-money.md`](../route-3-real-money.md) | Parked — prerequisites and safety notes |

## How the tiers relate

The route files (`route-1-*.md`, `route-2-*.md`) were written first as idea captures.
The packet (`overview.md`, `approach.md`, etc.) adds the structured go/no-go reasoning
and build-level detail on top. If you're already convinced an approach is right,
go straight to `infrastructure.md` and `FRAMEWORK.md`. If you're deciding whether
to do it at all, start with `overview.md` and `approach.md`.

## Who this packet is actually for

The sole developer of the moomoo project. None of this has been pressure-tested
against a real run yet — the packet was built from source material (the project
codebase and prior session reasoning) before any mining script or API call existed.
Phase 2 (Validation) in `FRAMEWORK.md` is the point where contact with reality happens.

## Adding a new doc

Before writing: decide which tier it belongs to (does it answer "should we" or "how
do we"), add it to the appropriate table above, and give it the same header block used
in the existing docs (`Tier / Audience / Use when`, at the top of the file). If a
section depends on facts nobody here actually knows yet, don't invent numbers — flag
it as a research-handoff candidate in `research-handoff.md` instead.

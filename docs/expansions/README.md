# Moomoo Next Expansions — Plan Packet

**Start at [`FRAMEWORK.md`](./FRAMEWORK.md)** — it tracks what phase each route is
in and what has to happen next. This README is the doc index.

Two primary routes for making this project more than "textbook strategies on a VPS":
Route 1 does real data science on the candle archive to find a non-textbook edge;
Route 2 wires in the Claude API as a morning regime gate to filter strategy entries by
macro context. Route 3 (real money) is parked until Routes 1/2 are explored.

## Route files (what, why, candidate implementation)

| File | Contents |
| --- | --- |
| [`route-1-data-mining.md`](./route-1-data-mining.md) | Hypotheses, scripts to build, decision criteria for deployment |
| [`route-2-llm-signals.md`](./route-2-llm-signals.md) | Architecture, module plan, shadow-mode rollout, API details |
| [`route-3-real-money.md`](./route-3-real-money.md) | Parked — prerequisites and safety notes |

## Plan packet (scoping + build guidance)

| Doc | Tier | Purpose |
| --- | --- | --- |
| [`FRAMEWORK.md`](./FRAMEWORK.md) | Meta | Phase-gated status tracker — where each route actually is and what's next |
| [`docs/documentation-guide.md`](./docs/documentation-guide.md) | Meta | Tier map, who reads what |
| [`docs/overview.md`](./docs/overview.md) | High-level | What each route is, why, what success looks like |
| [`docs/approach.md`](./docs/approach.md) | High-level | Alternatives considered, validation plan, time-to-signal |
| [`docs/infrastructure.md`](./docs/infrastructure.md) | Low-level | Stack, data, constraints, test plan |
| [`docs/risks.md`](./docs/risks.md) | Mixed | Scope, API dependency, architectural traps, operational burden |
| [`docs/notes.md`](./docs/notes.md) | High-level | Open questions, sequencing, unresolved calls |
| [`docs/research-handoff.md`](./docs/research-handoff.md) | Meta | Queue of claims to verify via deep research |
| [`research/`](./research/) | — | Raw deep-research output |

## How to use this packet

1. Read `FRAMEWORK.md` to see where each route is and what's blocking.
2. Read `docs/overview.md` for the "what and why" framing.
3. Read `docs/approach.md` and `docs/risks.md` together for the go/no-go inputs.
4. `docs/infrastructure.md` is the build-level detail — specific files, line-level guidance.
5. `docs/notes.md` is the live scratchpad of what's still undecided.

Everything in this packet is reasoning from the source material and project context —
not validated against a real run yet. Treat conclusions as hypotheses until Phase 2
(Validation) in `FRAMEWORK.md` is complete.

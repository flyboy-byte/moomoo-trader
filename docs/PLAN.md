# PLAN — the single active plan

> **Status: 2026-08-29.** This file replaces `docs/research-reset.md` as *the* plan. That file
> is now an evidence archive (the Goal A findings, the scoping measurements, the decisions log) —
> still worth reading once, no longer worth re-reading to find out what to do.
>
> **Everything to do next is in "The steps" below, in order.** Steps are sized to be finishable
> and testable one at a time. Each has a `Done when` line that is a command or a test name, not a
> feeling.
>
> **Right now: Step 0.**

## The one number that matters

The same 102 live trades: **gross +$12.92 / PF 1.189** → **net −$0.57 / PF 0.992**, CI
[0.545, 1.782], P(mean>0) = 0.48. The reported profit *was* the transaction costs. Every
per-strategy CI contains 1.0. There is no demonstrated edge, in either direction — the sample is
too small to say. Full evidence: `docs/research-reset.md` § "Goal A results".

Two goals follow from that, and they are strictly ordered:

- **Goal A — build a ruler.** Costs, dollars, benchmark, confidence intervals. *Mostly done:* the
  reporters are wired and agree; the engines are not.
- **Goal B — get a sample.** 3 correlated ETFs at ~1.8 trades/day cannot reach significance for
  months. 97 free `history_kl_quota` slots can, in days. Gated on A, because expanding first
  produces 15,000 trades measured with a broken ruler.

## How to use this file

- Do the steps in order. Where two steps are genuinely independent it says so.
- Every step is one commit (or a small handful), green tests, and a checkbox ticked here.
- A step that turns out to be wrong gets struck through with what was learned, not deleted.
- Findings, dead ends, and null results go to `docs/strategy_graveyard.md` — this file stays a
  plan, not a log.
- Nothing here changes a live strategy parameter, a gate threshold, or a `.env` value. If a step
  ever seems to require that, stop: it is a knob-freeze decision and belongs in
  `docs/evaluation_criteria.md` with a dated amendment.

**Evidence strength of the steps themselves.** Steps 0, 1, 2, 5, 8–12 restate work whose basis was
measured or run. **Steps 3, 4, and 7 were found by re-reading code and the plan on 2026-08-29 — they
are reasoning, not test results.** Step 7 especially: that a QFQ re-fetch splices two price bases
into an existing archive follows from what `mm/data.py` and `update_combined_csv()` do, but it has
never been observed, because none of SPY/QQQ/IWM has split. Each of those three steps is written to
*check* its premise first and is cheap to abandon if the premise is wrong. Do not treat them as
established the way the Goal A numbers are.

**Verify current state in one command each:**
```bash
git log --oneline -1
python -m pytest tests/ -q                 # expect 333 passed (~3m)
python scripts/analyze_trades.py --all     # sections 1, 1b, 1c show net-of-cost
```

---

## The steps

### Step 0 — Deploy the reporting fix to the VPS ☐
Five minutes, no code. The VPS runs the pre-2026-08-29 dashboard and is still publishing
gross-only numbers to a page that now has a net-of-costs design.

```bash
ssh <vps> 'cd ~/moomoo && git pull && systemctl --user restart moomoo-dashboard'
```

The **paper runner does not need restarting** — no runtime code changed on 2026-08-29.

**Done when:** the dashboard's P&L box shows a net headline with gross beneath it, and the
scorecard shows the net-PF CI column with every row dimmed (every live strategy is currently
consistent with zero edge).

---

### Step 1 — Decide: do the pre-registered gates mean gross or net? ☐
**Doc-only. Needs a human call — do not assume one.** *(was loose end §2)*

Every gate in `docs/evaluation_criteria.md` says "PF < 1.0 at N trades" without saying which PF.
Under the old frictionless ruler they meant gross. Several strategies pass gross and fail net —
ORB is 1.04 gross, 0.92 net, and it is 45% of all activity.

Recommendation: **gates become net**, since net is the only number that corresponds to money.
But changing the meaning of a pre-registered gate is exactly what that document exists to
prevent happening quietly, so it gets an amendment-log entry with a date and a reason.

**Done when:** `docs/evaluation_criteria.md` has a dated amendment stating which ruler every gate
uses, and the per-strategy gate sections say so inline.

**Blocks:** any gate evaluation. ORB and gap_fade are both near their gates.

---

### Step 2 — Wire `mm/costs.py` into the engines ☐
*(was B2a's remaining half, loose end §1)* The reporters go through `mm/trades.py` and agree.
The engines the wide scan actually runs through are still frictionless, so **B3 cannot produce a
cost-aware result until this is done.** Four small chunks, each independently testable:

- **2a ☐ `mm/backtest.py`** — the BB+KDJ engine and `print_summary()`. Every summary dict grows
  `net_pnl` / `net_pf` / `avg_bps_net` alongside the gross fields; gross is kept, never replaced.
  *Done when:* a test asserts net < gross on a winning synthetic run and that both appear in
  `print_summary()` output.
- **2b ☐ the four strategy engines** — `mm/orb_strategy.py`, `mm/vwap_pullback.py`,
  `mm/gap_fade.py`, `mm/ema_momentum.py`. Same shape as 2a. These already call the canonical
  `profit_factor`; costs go in at the same place.
  *Done when:* one parametrized test covers all four.
- **2c ☐ `mm/replay.py::summarize()`** (line ~305) — the real-code-path engine. Same fields.
  *Done when:* `scripts/replay_paper.py --latest` prints both rulers.
- **2d ☐ the guard** — a single test that walks every engine's summary output and fails if any
  one of them reports a PnL or PF without its net counterpart. This is the same shape of guard as
  `test_only_mm_backtest_defines_profit_factor`, and for the same reason: the failure mode here is
  a *new* engine being added later that quietly reports gross.

**Note on ordering:** this now comes before engine cross-validation (old B2), which the previous
plan had backwards. Comparing two engines under the frictionless ruler and then changing the
ruler means re-doing the comparison.

---

### Step 3 — Make the cost model credible for symbols it has never seen ☐
**A design hole found while re-reading the plan, not previously listed.**

`mm/costs.py` has measured-ish values for three symbols and a flat `DEFAULT_ROUND_TRIP_BPS = 5.0`
for everything else. Goal B's headline falsification test is "if the cost model is right, single
names show markedly worse net results than ETFs." With a flat 5.0 default applied to both the 60
new ETFs and the 25 mega-caps, **that test cannot fail** — the model has been told the answer.
It is circular as currently specified.

Fix: a documented per-symbol estimate for every symbol in the universe, derived from data the
project already has or can get cheaply, not from a single constant. Candidate basis: price level
plus median bar range plus dollar volume; the exact estimator matters less than that it is
*computed per symbol, written down, and frozen before any returns are looked at.*

Restate the falsification test so it can actually fail — e.g. "single names underperform ETFs net
by more than the cost differential the model assigns them," which is a claim about the residual,
not about the haircut.

**Done when:** `mm/costs.py` carries a per-symbol table covering the frozen universe, with the
estimator and its inputs documented in the module docstring, and the pre-registered expectation
in `docs/evaluation_criteria.md` is stated in a form that could come out either way.

**Blocks:** B0's universe decision is safe to keep, but the mega-cap slot allocation is only worth
25 quota slots if this step makes the test real.

---

### Step 4 — Block-bootstrap the CIs before pooling across symbols ☐
**Also a newly-found hole.**

`mm/stats.py` resamples trades i.i.d. That is defensible at n=102 on three symbols. It is wrong
for the wide scan: 85 symbols on the same day share one market regime, and most of the ETF
universe is a linear combination of SPY. Resampling trades independently across a correlated
cross-section **understates the interval**, sometimes badly, and the entire point of Goal A was to
stop reporting numbers that pretend to be evidence.

Fix: resample by **day** (all trades on a sampled day move together), keep the i.i.d. path for
single-symbol reporting, and report which was used.

**Done when:** `bootstrap_pf_ci` takes a block key, a test shows the block CI is wider than the
i.i.d. CI on synthetic same-day-correlated data, and every cross-symbol report uses the block
version.

---

### Step 5 — Cross-validate the two engines, net, with a number decided in advance ☐
*(was B2)* `mm/replay.py` and the fast engines are different code paths and are **already known to
disagree** — 2026-06-12, replay vwap_pb PF 1.89 against a different backtest expectation. If they
still disagree, the wide scan measures the engine, not the market.

The previous wording — "if it's large and unexplained, fix before proceeding" — has no threshold,
which makes it unfalsifiable after the fact. **Write the tolerance down before running it**:
propose trade-count within 2%, and net PF within 0.05, over SPY/QQQ/IWM on the same window.

**Done when:** the comparison is run, the numbers are in `docs/strategy_graveyard.md`, and either
they clear the tolerance or the disagreement is explained and the plan pauses here.

---

### Step 6 — Freeze the scan configuration, in writing, before any fetch ☐
**Partly new.** Three separate things get frozen, all before a single new symbol is pulled:

- **6a ☐ Parameters.** The live strategies carry per-symbol overrides (`ORB_VIX_MAX_OVERRIDES`,
  IWM's 30-minute OR, and so on) tuned on SPY/QQQ/IWM. Running SPY with tuned parameters and AAPL
  with defaults produces a comparison of tuning, not of symbols. **One symbol-agnostic parameter
  set for the whole scan**, written down here, with the tuned live values explicitly out of scope.
- **6b ☐ IS/OOS split.** Concrete dates, chosen now, never revisited. Suggest IS 2019–2023,
  OOS 2024–present, which keeps a genuinely untouched recent window.
- **6c ☐ Selection rule and finalist count.** 100 symbols × 5 strategies × sweeps is an
  overfitting machine and the plan currently answers it with culture rather than a rule. Fix a
  number of finalists (suggest ≤ 10) and a multiple-testing-aware threshold *before* seeing
  results. The best of 500 combinations looks excellent by luck alone; that is arithmetic, not
  pessimism.

**Done when:** all three are written into `docs/evaluation_criteria.md` under a dated
pre-registration heading.

---

### Step 7 — Verify what a re-fetch does to an existing archive ☐
**New — a data-corruption risk nobody has looked at.**

`mm/data.py` fetches with `autype=AuType.QFQ` (forward-adjusted). QFQ prices are expressed
relative to the *latest* price, so **the same historical bar returns different numbers before and
after a split.** `update_combined_csv()` merges new pulls into the existing archive. A split
between two pulls therefore splices two different price bases into one CSV, silently — and every
strategy here is a mean-reversion strategy that would read that seam as an enormous signal.

SPY/QQQ/IWM have not split, which is why this has never bitten. The mega-cap block is full of
symbols that have: AAPL 4:1 (2020), TSLA 5:1 (2020) and 3:1 (2022), AMZN and GOOGL 20:1 (2022),
NVDA 4:1 (2021) and 10:1 (2024).

Cheap to settle: pull one known-split symbol across its split date and check the seam. Costs one
quota slot of 97.

**Done when:** the behaviour is documented, and — if the seam is real — `update_combined_csv()`
gains an overlap-row price-mismatch check that quarantines rather than merges, matching what it
already does for corruption.

---

### Step 8 — Pre-register the universe ☐
*(was B0 — decided, not yet written down as a list)* 60 liquid ETFs / 25 mega-caps / 12 held in
reserve. Selection criteria (liquidity, median spread, price range, sector coverage) fixed before
any return is looked at. Survivorship bias stated explicitly in the writeup: picking names liquid
in 2026 and testing back to 2019 selects for survival.

**The quota makes this one-shot.** 97 slots, rolling 30-day refresh — a symbol pulled today
occupies its slot for 30 days. Getting the list wrong costs a month.

**Done when:** the explicit symbol list is committed to this repo, with the criteria that produced
it, and reviewed by the user before Step 9 spends anything.

---

### Step 9 — Bulk fetch ☐
*(was B1)* Extend `scripts/fetch_daily_archive.py` — do not rebuild it, `update_combined_csv`
already dedupes and quarantines correctly. Needs, and each is small enough to test on its own:

- **9a ☐ Throttling.** Futu documents ~30 requests / 30s. The measured unthrottled rate
  (0.07 s/page) would trip it immediately.
- **9b ☐ A quota ledger.** A persisted record of which symbol consumed a slot and when.
  Without it, a resume or a retry silently burns non-renewable slots — and the plan already calls
  the quota one-shot per 30 days.
- **9c ☐ Resumability + a pre-flight refusal** that will not start if the run would exceed
  remaining slots.

Target 2019 → present (depth verified ≥ 2019-01-02).

**Done when:** the universe is on disk, the ledger accounts for every slot spent, and a
re-invocation is a no-op rather than a second spend.

---

### Step 10 — Close the benchmark ☐
*(was loose end §3, A3)* The SPY buy-and-hold benchmark currently covers only to 2026-06-25 while
trades run to 08-24, because the local archive ends there; the script says so instead of quoting a
wrong number. Step 9 backfills it.

Also: for a 100-symbol scan the right null for each symbol is **that symbol's own buy-and-hold**,
not SPY's. Add it.

**Done when:** `analyze_trades.py` stops printing the partial-benchmark warning, and per-symbol
benchmarks appear in the scan output.

---

### Step 11 — Wide scan ☐
*(was B3)* Fast engines across the frozen universe, sharded by symbol — VPS has ~5 GB available and
a naive all-symbols-in-memory run would OOM; per-symbol independence is what edge measurement wants
anyway. Estimated ~56 min single-threaded at the measured 1.56 s per symbol-year per strategy.

Applies: Step 2's costs, Step 3's per-symbol cost table, Step 4's block CIs, Step 6's frozen
parameters, split, and selection rule.

**Done when:** results exist for the full universe with net PF, block-bootstrap CIs, and the
symbol's own benchmark, and the finalist list is produced by Step 6c's rule rather than by reading.

---

### Step 12 — Confirm finalists through the real code path ☐
*(was B4)* Only combinations that clear costs by a meaningful margin **in OOS** go to
`mm/replay.py`. This is where the ~650× slower engine earns its cost — on a handful of candidates,
not on 450 symbol-years.

**Done when:** each finalist has a replay result agreeing with its fast-engine result inside
Step 5's tolerance, or the disagreement is explained.

---

## Independent — do any time

### H1 — Repo housekeeping ☐
*(loose end §6, user-flagged)* `replay_2026_ytd/`, `replay_2026ytd/`, `replay_out/` in the repo root
are three variants of the same thing. Best done *before* Step 11 writes a fourth.

### H2 — Verify the weekly synthesis actually runs ☐
The Monday 9:00 ET synthesis failed 5/5 weeks (W30–W34) on a truncated `max_tokens`, fail-open
swallowed it, and Discord got "No summary available." every week. Fixed 2026-08-29, and the fix now
records `stop_reason` — **but the diagnosis is inference, not proof.** Check the next Monday run.
If it fails again with `stop_reason == "end_turn"`, the truncation theory is wrong and the
`docs/strategy_graveyard.md` entry needs correcting.

---

## Deferred infrastructure — OpenD / moomoo-api are out of date

**Not scheduled. Recorded so it stops being a background worry, and so the next session does not
re-derive it.** No research done on this in the 2026-08-29 session, by request.

**What is installed:** `moomoo_api` **10.6.6608** locally. Local OpenD runs the 10.6 headless
binary under a systemd user service.

**What is known from the last attempt (2026-06-29, local):** the 10.8 upgrade was tried and rolled
back. Root cause found via strace: 10.8 changed security-list initialisation from client-driven to
server-driven, and the server trigger never fires on Arch Linux (the binary targets Ubuntu 18.04).
Login worked; every candle query returned "Unknown stock" indefinitely. Rolled back to 10.6, which
works. Also learned the hard way: **never restart OpenD more than ~5 times an hour** — 220+
restarts during that diagnosis tripped both the local
`nOpenDStartUpMaxTimesPerHours` limit and a server-side login lockout.

**What the user recalls, which does not fully match the above:** a `.deb` that was awkward on Arch,
plus an authentication problem and config-file syntax differences between versions. The strace
diagnosis records a different failure mode. Both may be true of different attempts. **Treat neither
account as settled** — re-establish the facts before acting, don't inherit them.

**Is it a constraint on this plan?** Unknown, and deliberately not investigated. The two places it
could bite are both in Goal B and both will reveal it naturally:
- Step 7 (adjustment behaviour) depends on how this client version handles `autype` across splits.
- Step 9 (bulk fetch) depends on quota reporting and throttling behaviour holding at scale.

If either misbehaves in a way that looks version-related, *that* is when this becomes a task. Until
then it is a known-stale dependency on a working system, which is not an emergency.

**If it does become a task, the relevant differences are:** the VPS is Ubuntu, so the `.deb` path
that failed on Arch is not obviously a problem there — but the VPS and local would then be on
different OpenD versions, which is its own risk and needs deciding rather than drifting into.

---

## Parked — not cancelled, not now

- **Route 2b Phases 2–6** (`docs/expansions/route-2b-volatility-engine.md`) — the volatility
  term-structure engine feeding the regime gate, and the bounded ALLOW/TIGHTEN/BLOCK policy.
  Phase 1 and Phase 3 are done and Phase 1 keeps writing `logs/vol_state.jsonl` for free. Parked
  because adding an LLM policy layer on top of an unmeasured base is more surface area on the exact
  problem this plan exists to fix. Reopen after Step 12.
- **Route 2 Phase 5 formalization** (`docs/expansions/FRAMEWORK.md`) — the regime gate's
  keep/remove/tune decision. Same reason, and it is also a gate evaluation, so it is behind Step 1.
- **Route 3 — real money.** Parked, and nothing in this plan moves it.
- **`docs/codex-ai-size.md` / `codex-ai-size-remedies.md`** — repo doc-hierarchy analysis, parked
  for a dedicated session.

## Deliberately not doing

- **Not touching the live paper runner.** It keeps running unchanged throughout. Its job is
  execution validation, which is a different question from edge, and it passed months ago.
- **Not suspending gap_fade**, despite PF 0.29 gross and negative at every cost level. Decided
  2026-08-29: there is no capital at risk, so suspension buys nothing, while overriding a
  pre-registered gate the first time it is inconvenient costs the credibility of every other gate.
  Goal B will produce hundreds of gap_fade instances; eight more live trades would not.
- **Not retuning the gap-up short filter** on 7 trades, even though those losses sit below the
  existing >1% threshold. That is the parameter fitting the knob freeze exists to prevent. It goes
  to Step 11 as a hypothesis, not to `.env` as an edit.
- **Not going to 1-minute candles.** Five times the trades at a smaller move each, against a fixed
  cost, is the wrong direction at +1.31 bps.
- **Not raising again** (user-deprioritised): `ANTHROPIC_API_KEY` rotation, starting local OpenD.

## The honest endgame

At n≈15,000 net of realistic costs this may show that retail intraday mean reversion on liquid US
equities has no edge — it is the most competed trade in existence, so that is a live outcome.
**A hard null at that sample is a real finding** and frees the engine to point somewhere less
crowded. The current structure cannot produce even that. The failure being fixed is not that the
answer is bad; it is that no answer is reachable.

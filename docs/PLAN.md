# PLAN — the single active plan

> **Status: 2026-08-29.** This file replaces `docs/research-reset.md` as *the* plan. That file
> is now an evidence archive (the Goal A findings, the scoping measurements, the decisions log) —
> still worth reading once, no longer worth re-reading to find out what to do.
>
> **Everything to do next is in "The steps" below, in order.** Steps are sized to be finishable
> and testable one at a time. Each has a `Done when` line that is a command or a test name, not a
> feeling.
>
> **Amended 2026-09-16** after a Codex review (`docs/CLAUDE_REVIEW_HANDOFF_2026-09-16.md`, kept
> as its own record). Changes: new Step 0b (health review + per-strategy table), new Step 1b
> (frozen forward cohort), Step 6b corrected (2024+ is not unseen data). See "Amendments" at the
> bottom.
>
> **Right now: Step 9** (bulk fetch: throttling, quota ledger, resumability). Steps 5–7 closed 2026-09-17. Steps 0–4 (including 0b/1b) are done (2026-09-16/17). Former
> Step 8's universe preregistration was pulled into Step 3 because a per-symbol cost table cannot
> be built before its symbols are fixed; the bulk OpenD fetch remains Step 9 and has not begun.

## The one number that matters

The same 102 live trades: **gross +$12.92 / PF 1.189** → **net −$0.57 / PF 0.992**, CI
[0.545, 1.782], P(mean>0) = 0.48. The apparent profit disappears under the modeled costs. Every
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
python -m pytest tests/ -q                 # expect 341 passed (~4m)
python scripts/analyze_trades.py --all     # sections 1, 1b, 1c show net-of-cost
```

---

## The steps

### ~~Step 0 — Deploy the reporting fix to the VPS~~ ✅ DONE 2026-09-17 (VPS `f1ed556`, dashboard restarted, net headline live)
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

### ~~Step 0b — Health review: pull VPS logs, one table per strategy~~ ✅ DONE 2026-09-17
**Added 2026-09-16 (Codex review).** The loop so far has been "pull logs, fix bugs, keep
running" with no decision at the end of it. This step produces that decision.

1. `./sync_logs.sh`, then confirm what is deployed: the VPS commit, the active strategies, the
   `.env` gate settings, uptime, reconciliation errors, unfilled orders.
2. Split the trade history **wherever the configuration or behaviour changed** (e.g. ORB QQQ/IWM
   shorts off 2026-07-09, `ORB_LATEST_ENTRY=12:30` 2026-08-14). The 102 trades mix several eras,
   and a pooled number blurs them.
3. For each strategy × era: trades, win rate, gross and net PnL/PF, cost sensitivity, fill
   anomalies, whether its gate has been reached, and one next action: **continue / investigate
   execution / review strategy**.

**Read-only.** Nothing here changes a live parameter; a "review strategy" verdict goes through
the knob freeze like anything else.

**Done when:** the table is in `docs/strategy_graveyard.md` under a dated heading, and anything
that could not be verified is named as such.

**2026-09-17 — done** from synced logs after a VPS reboot fixed SSH. Table:
`docs/strategy_graveyard.md` § "Health Review — 2026-09-16". Headlines: the 32 trades since 08-24
are net PF 0.32 (CI [0.09, 0.87]); the whole period is net −$23.14, PF 0.79. ORB since the
08-14 cutoff change is net PF 0.20 on 12 trades. By symbol, QQQ is net positive and SPY and IWM are
negative, QQQ has passed the 50-trade symbol gate and SPY is 2 trades short of it.
Actions: review ORB, and evaluate the symbol gate once Step 1 is decided.

---

### ~~Step 1 — Decide: do the pre-registered gates mean gross or net?~~ ✅ DONE 2026-09-16 — net PF
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

**Decision:** every PF threshold means net PF under the frozen `mm/costs.py` model. Gross remains
visible for diagnosis. The dated amendment and inline gate wording are in
`docs/evaluation_criteria.md`.

### ~~Step 1b — Declare a frozen forward cohort~~ ✅ DONE 2026-09-16 — starts 2026-09-17
**Added 2026-09-16 (Codex review). Needs a human call.** All history — live and backtest — has
been looked at repeatedly while tuning, so none of it is a clean test (see Step 6b). The only
clean test left is data that does not exist yet: fix one configuration and a start date, and
count only trades from that date on under that configuration. The runner keeps running as it
does now; the cohort is a labelled slice of its output, not a second runner.

**Done when:** `docs/evaluation_criteria.md` has a dated entry naming the configuration
(commit + `.env` gate values), the start date, the question the cohort answers, and the rule for
reading the result. After that, any live knob change ends the cohort and must be recorded as such.

**Depends on:** Step 0b (know what is actually deployed) and Step 1 (which ruler it is read with).

**Decision:** the first forward-only cohort starts with the 2026-09-17 market session on runtime
code `f1ed556` and the verified configuration recorded in `docs/ARCHITECTURE.md`. The full question,
reading rule, frozen settings, and reset conditions are in `docs/evaluation_criteria.md`.

---

### ~~Step 2 — Wire `mm/costs.py` into the engines~~ ✅ DONE 2026-09-16
*(was B2a's remaining half, loose end §1)* The reporters go through `mm/trades.py` and agree.
The engines the wide scan actually runs through are still frictionless, so **B3 cannot produce a
cost-aware result until this is done.** Four small chunks, each independently testable:

- **2a ✅ `mm/backtest.py`** — the BB+KDJ engine and `print_summary()`. Every summary dict grows
  `net_pnl` / `net_pf` / `avg_bps_net` alongside the gross fields; gross is kept, never replaced.
  *Done when:* a test asserts net < gross on a winning synthetic run and that both appear in
  `print_summary()` output.
- **2b ✅ the four strategy engines** — `mm/orb_strategy.py`, `mm/vwap_pullback.py`,
  `mm/gap_fade.py`, `mm/ema_momentum.py`. Same shape as 2a. These already call the canonical
  `profit_factor`; costs go in at the same place.
  *Done when:* one parametrized test covers all four.
- **2c ✅ `mm/replay.py::summarize()`** (line ~305) — the real-code-path engine. Same fields.
  *Done when:* `scripts/replay_paper.py --latest` prints both rulers.
- **2d ✅ the guard** — a single test that walks every engine's summary output and fails if any
  one of them reports a PnL or PF without its net counterpart. This is the same shape of guard as
  `test_only_mm_backtest_defines_profit_factor`, and for the same reason: the failure mode here is
  a *new* engine being added later that quietly reports gross.

**Note on ordering:** this now comes before engine cross-validation (old B2), which the previous
plan had backwards. Comparing two engines under the frictionless ruler and then changing the
ruler means re-doing the comparison.

**Result:** `mm/backtest.py::summarize_trades()` is the shared fast-engine ruler; BB+KDJ, ORB,
VWAP Pullback, Gap Fade, EMA Momentum, and the deprecated VWAP engine print gross and net PnL/PF
plus gross/net bps. Replay pairs its own JSONL events through `mm/trades.py` and reports the same
fields. `tests/test_engine_cost_reporting.py` covers all engines and includes the repo-wide guard.
Full suite: **341 passed**.

---

### ~~Step 3 — Make the cost model credible for symbols it has never seen~~ ✅ DONE 2026-09-16
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

**Done when:** the `mm/costs.py` runtime interface covers a per-symbol table for the frozen
universe, with the estimator and its inputs documented, and the pre-registered expectation in
`docs/evaluation_criteria.md` is stated in a form that could come out either way.

**Blocks:** B0's universe decision is safe to keep, but the mega-cap slot allocation is only worth
25 quota slots if this step makes the test real.

**Result:** the ordering dependency was resolved by completing former Step 8's preregistration as
part of this step. `docs/wide_scan_universe.csv` freezes 60 primary ETFs, 25 primary liquid
large/mega-cap stocks, and 12 ordered reserves. All 97 have 250 public daily observations and pass
the predeclared ≥$5 price / ≥$25m median-dollar-volume screen; DBC failed as a reserve and was
replaced by PDBC before any five-minute history or strategy result was inspected.

`docs/wide_scan_methodology.md` freezes a return-independent heuristic based on minimum-tick bps,
median dollar volume, and a common execution/model-risk buffer. Its full inputs and components are
in `docs/wide_scan_cost_inputs.csv`; `mm/wide_scan_cost_table.py` carries the generated runtime
table. The original SPY/QQQ/IWM values remain exactly 1.5/1.5/2.5 bps. An attempted
Corwin-Schultz daily high/low estimator was rejected before adoption because it implied implausible
17–33 bps monthly-median spreads for those liquid anchors. The ETF-versus-stock claim is now about
the residual gross-return difference after displaying the modeled cost differential separately,
so the test can come out either way. No OpenD quota was used and no strategy return was read. Full
suite: **345 passed**.

---

### ~~Step 4 — Block-bootstrap the CIs before pooling across symbols~~ ✅ DONE 2026-09-16
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

**Result:** `bootstrap_pf_ci`, `bootstrap_mean_ci`, `prob_positive`, and `summarize` now accept
aligned block keys and resample whole blocks. A pooled report groups all same-day trades across
symbols; a one-symbol report retains the original IID method. Fewer than two blocks returns no
interval rather than false precision. Both `analyze_trades.py` and the dashboard label which method
they used, and behavioral tests pin the selection rule. On the current 134 live-paper trades, the
net-PF interval widened from the earlier IID **[0.47, 1.30]** to day-blocked **[0.43, 1.41]**;
the conclusion remains no demonstrated edge. Full suite: **350 passed**.

---

### ~~Step 5 — Cross-validate the two engines, net, with a number decided in advance~~ ✅ DONE 2026-09-17 (after a preregistered FAIL — see below)
**2026-09-17 — preregistered run FAILED; paused here, per the rule.** See
`docs/strategy_graveyard.md` § "Engine Cross-Validation — 2026-09-17". There are two causes. (1) The
replay's `instant` mode fills at the marketable limit, which costs about 40 bps per round trip;
live fills don't pay that. (2) **Live gap_fade ignored `GAP_LARGE_SHORT_FILTER_ENABLED`**, a live
bug, fixed and deployed 2026-09-17 (`f39df61`); the cohort was re-based onto that commit. A diagnostic
`fill_mode=close` rerun is recorded there. Step 5 stays open until the user decides how to proceed.

**Resolution 2026-09-17 (user: "fix all").** The gap_fade bug was fixed and deployed. The comparison
of record was switched to `fill_mode=close`, a post-hoc change recorded in evaluation_criteria.md.
All four strategies then agree exactly. **Carried forward:** both engines assume a fill at the
signal close. Live slippage (median −3.5 bps on entries) may exceed what `mm/costs.py` covers, so
check that before trusting a wide-scan net PF near 1.0 (see Step 6).

*(was B2)* `mm/replay.py` and the fast engines are different code paths and are **already known to
disagree** — 2026-06-12, replay vwap_pb PF 1.89 against a different backtest expectation. If they
still disagree, the wide scan measures the engine, not the market.

The previous wording — "if it's large and unexplained, fix before proceeding" — has no threshold,
which makes it unfalsifiable after the fact. **Write the tolerance down before running it**:
propose trade-count within 2%, and net PF within 0.05, over SPY/QQQ/IWM on the same window.

**Done when:** the comparison is run, the numbers are in `docs/strategy_graveyard.md`, and either
they clear the tolerance or the disagreement is explained and the plan pauses here.

---

### ~~Step 6 — Freeze the scan configuration, in writing, before any fetch~~ ✅ DONE 2026-09-17
**Partly new.** Three separate things get frozen, all before a single new symbol is pulled:

- **6a ✅ Parameters.** The live strategies carry per-symbol overrides (`ORB_VIX_MAX_OVERRIDES`,
  IWM's 30-minute OR, and so on) tuned on SPY/QQQ/IWM. Running SPY with tuned parameters and AAPL
  with defaults produces a comparison of tuning, not of symbols. **One symbol-agnostic parameter
  set for the whole scan**, written down here, with the tuned live values explicitly out of scope.
- **6b ✅ IS/OOS split.** Concrete dates, chosen now, never revisited. ~~Suggest IS 2019–2023,
  OOS 2024–present, which keeps a genuinely untouched recent window.~~ **Corrected 2026-09-16:**
  2024+ is *not* untouched. It was the OOS window for most past research, and live parameters were
  set from it — the ORB VIX cutoffs were chosen from 2024+ results
  (`docs/strategy_graveyard.md` § "OOS verification (2024+ only, 2026-07-23)"). For the SPY/QQQ/IWM
  live settings, 2024+ is development data. For symbols never pulled before, a historical OOS
  window is still meaningful. **The clean confirmation for the live settings is Step 1b's forward
  cohort**, not any historical window.
- **6c ✅ Selection rule and finalist count.** 100 symbols × 5 strategies × sweeps is an
  overfitting machine and the plan currently answers it with culture rather than a rule. Fix a
  number of finalists (suggest ≤ 10) and a multiple-testing-aware threshold *before* seeing
  results. The best of 500 combinations looks excellent by luck alone; that is arithmetic, not
  pessimism.

**Done when:** all three are written into `docs/evaluation_criteria.md` under a dated
pre-registration heading.

**Result 2026-09-17:** `docs/evaluation_criteria.md` § "Wide-scan configuration, split, and selection
rule". Parameters are in `docs/wide_scan_params_2026-09-17.env`: live base values, no per-symbol
overrides, w=0, shorts everywhere, context gates off, no sweeps. **Split: development 2022-01-03 →
2026-08-31, holdout 2019-01-02 → 2021-12-31.** The holdout is the only historical window no past
research touched; Step 11 must keep it sealed until finalists are committed. Selection has a primary
per-strategy pooled test (Bonferroni over 4) and secondary per-lane tests (BH q=0.10 over 340, at most
10 finalists), both with a +3.5 bps slippage stress on the holdout.

**Consequence for Step 9:** the fetch range is 2019-01-02 → 2026-08-31 for every symbol, including
SPY/QQQ/IWM, whose local archives start in 2022.

---

### ~~Step 7 — Verify what a re-fetch does to an existing archive~~ ✅ DONE 2026-09-17 (seam confirmed, fixed, 0 quota spent)
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

**Result 2026-09-17:** the seam is real and **dividends alone cause it**. The live SPY/IWM archives
already had ~25 bps seams, and a free re-pull (SPY/QQQ/IWM were already in the quota set) proved it
bar by bar. `update_combined_csv()` now rebases the archive onto the new basis when the overlap
shows a clean constant ratio (with a backup), and refuses otherwise. Along the way it turned out the
2026-08-24 test-fixture rows were never actually removed from the IWM archive; they are now, and
`tests/test_archive_integrity.py` guards it. Details: `docs/strategy_graveyard.md` § "Archive
price-basis seams". **For Step 9:** new symbols are pulled once over the full range, so they have a
single basis. SPY/QQQ/IWM's 2019+ pull goes through the rebase path.

---

### ~~Step 8 — Pre-register the universe~~ ✅ DONE 2026-09-16 (absorbed into Step 3)
*(was B0 — decided, not yet written down as a list)* 60 liquid ETFs / 25 mega-caps / 12 held in
reserve. Selection criteria (liquidity, median spread, price range, sector coverage) fixed before
any return is looked at. Survivorship bias stated explicitly in the writeup: picking names liquid
in 2026 and testing back to 2019 selects for survival.

**The quota makes this one-shot.** 97 slots, rolling 30-day refresh — a symbol pulled today
occupies its slot for 30 days. Getting the list wrong costs a month.

**Done when:** the explicit symbol list is committed to this repo, with the criteria that produced
it, and reviewed by the user before Step 9 spends anything.

**Result:** completed early because Step 3 required the list. See
`docs/wide_scan_universe.csv` and `docs/wide_scan_methodology.md`. This commits the list for review;
it does not authorize or begin Step 9's quota-consuming fetch.

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

**2026-09-17 — tooling done, paid run not started.** `mm/bulk_fetch.py` + `scripts/fetch_universe.py`
(a new script rather than an extension of `fetch_daily_archive.py`, but reusing its
`fetch_candles` / `update_combined_csv`):
- **9a:** a 1.1 s throttle between page requests.
- **9b:** `logs/wide_scan/quota_ledger.jsonl`. Each paid pull must move OpenD's own quota counter
  by exactly one slot (zero for symbols already held), or the run halts.
- **9c:** finished symbols are never re-requested; the run refuses to start (or continue) below a
  3-slot margin. `fetch_candles(strict=True)` now raises instead of returning a truncated history.
- **Reserves:** swapped in (same asset class, list order) only when a symbol is genuinely
  unavailable, never on transient errors.
- **Tests:** 11 in `tests/test_bulk_fetch.py`.

**VPS dry run:** 3 used / 97 free, 85 to fetch, **82 new slots**, 15 left after, and OpenD
recognises all 97 codes. **Free live test:** `--limit 1` fetched SPY (already held), 149,688 bars
2019-01-02 → 2026-08-31, **0 slots spent**, 2 m 47 s, 24 MB. The full run is ~4 h and ~2 GB (49 GB
free). Output goes to `logs/wide_scan/` on the VPS, one full pull per symbol (single price basis).
The local SPY/QQQ/IWM archives are not touched. **Waiting on user go-ahead to spend the 82 slots.**

---

### Step 10 — Close the benchmark ☐
*(was loose end §3, A3)* The SPY buy-and-hold benchmark currently covers only to 2026-06-25 while
trades run to 08-24, because the local archive ends there; the script says so instead of quoting a
wrong number. Step 9 backfills it.

Also: for a 100-symbol scan the right null for each symbol is **that symbol's own buy-and-hold**,
not SPY's. Add it.

**Done when:** `analyze_trades.py` stops printing the partial-benchmark warning, and per-symbol
benchmarks appear in the scan output.

**2026-09-17 — built, one wait left.** Per-symbol buy-and-hold over the scan window is in
`mm/scan.py::buy_and_hold` and in every `wide_scan.py dev` output. For the live benchmark, the VPS
nightly job now also keeps `US_SPY_K_DAY_combined.csv` (~400 days re-pulled each night, one page,
free), which `sync_logs.sh` copies down. `analyze_trades.py` prefers it and labels which bars it
used. **Done** once the first nightly run has produced the file and a sync shows no
partial-benchmark warning.

---

### Step 11 — Wide scan ☐
*(was B3)* Fast engines across the frozen universe, sharded by symbol — VPS has ~5 GB available and
a naive all-symbols-in-memory run would OOM; per-symbol independence is what edge measurement wants
anyway. Estimated ~56 min single-threaded at the measured 1.56 s per symbol-year per strategy.

Applies: Step 2's costs, Step 3's per-symbol cost table, Step 4's block CIs, Step 6's frozen
parameters, split, and selection rule.

**Holdout discipline (from Step 6):** run and print the development window only. Commit the
finalist list and the four pooled-strategy D verdicts **before** any code computes 2019–2021
results. Then run the holdout for exactly those. The scan script should refuse to compute the
holdout unless a committed finalist file exists.

**Done when:** results exist for the full universe with net PF, block-bootstrap CIs, and the
symbol's own benchmark, and the finalist list is produced by Step 6c's rule rather than by reading.

**2026-09-17 — built and trial-tested, waiting on Step 9's data.**
- **Code:** `mm/scan.py` holds the rules and constants from evaluation_criteria.md and
  `run_engines` (now shared with the Step 5 script, which reproduces its earlier output
  byte-for-byte). `scripts/wide_scan.py dev|holdout` does the rest:
  - `dev` writes `docs/wide_scan/dev_results.json` and `finalists.json`.
  - `holdout` refuses unless `finalists.json` is committed and unmodified.
  - Partial runs (`--symbols`, missing files) are trials: they write to `logs/wide_scan/trial/`
    and never touch the committed files.
- **Tests:** 7 in `tests/test_scan_rules.py`.
- **Trial:** SPY/QQQ/IWM on the dev window took 34 s (a plumbing check only; dev is not sealed).
- **To run** after the fetch: rsync `logs/wide_scan/` from the VPS, run
  `python scripts/wide_scan.py dev --workers 10`, commit `docs/wide_scan/`, then run `holdout`.

---

### Step 12 — Confirm finalists through the real code path ☐
*(was B4)* Only combinations that clear costs by a meaningful margin **in OOS** go to
`mm/replay.py`. This is where the ~650× slower engine earns its cost — on a handful of candidates,
not on 450 symbol-years.

**Done when:** each finalist has a replay result agreeing with its fast-engine result inside
Step 5's tolerance, or the disagreement is explained.

---

## Independent — do any time

### ~~H1 — Repo housekeeping~~ ✅ DONE 2026-09-17 — all three moved, untouched, into `replay_archive/` (gitignored, with a README)
*(loose end §6, user-flagged)* `replay_2026_ytd/`, `replay_2026ytd/`, `replay_out/` in the repo root
are three variants of the same thing. Best done *before* Step 11 writes a fourth.

### H2 — Verify the weekly synthesis actually runs ☐
The Monday 9:00 ET synthesis failed 5/5 weeks (W30–W34) on a truncated `max_tokens`, fail-open
swallowed it, and Discord got "No summary available." every week. Fixed 2026-08-29, and the fix now
records `stop_reason` — **but the diagnosis is inference, not proof.** Check the next Monday run.
If it fails again with `stop_reason == "end_turn"`, the truncation theory is wrong and the
`docs/strategy_graveyard.md` entry needs correcting.

---

### H3 — Extended README design ☐
*(user request, 2026-09-17)* Give `README.md` (328 lines) a proper design pass. **Must use the
`readme` skill** (user instruction): structure a skimmer can follow in 30 seconds, status tables, collapsibles, and a
diagram of the runner → logs → dashboard flow. It has to tell the honest story: a paper-only
research platform, currently no demonstrated edge net of costs, with measurement rebuilt and a
wide scan in progress. Don't sell it as a profitable system.
**Done when:** README renders cleanly on GitHub (checked in a browser), and every claim in it
matches `docs/` as of that date.

### H4 — GitHub Pages site ☐
*(user request, 2026-09-17)* A small public page for the project, e.g. an overview, the
methodology (the gross→net finding, the preregistration and holdout discipline, the Step 5
engine cross-validation), and possibly a static snapshot of wide-scan results once Step 11 exists.
Open decisions: plain `docs/`-folder Pages vs a `gh-pages` branch (the repo's `docs/` is already
the deep-doc folder, so a separate folder or branch is likely cleaner), and what to publish.
**Nothing live or account-specific:** no positions, no VPS host, nothing from `.env`.
**Done when:** the site builds from the repo and links back to README.

### H5 — Do the 2026-09 changes warrant dashboard changes? ☐
*(user request, 2026-09-17)* Review `scripts/web_dashboard.py` against what changed since Step 0's
deploy, then decide what (if anything) to build. Candidates:
- the **forward cohort** (a "since 2026-09-17" view, separate from all-time);
- the **gap-filter fix** (`gap_large_short` skips are now real events);
- the **day-blocked CIs** (Step 4);
- a wide-scan results page once Step 11 lands.
Related, found 2026-09-16: `/api/*` endpoints are readable without login, including `/api/stats`'s
process list. Decide whether that is intended for a public showcase.
Constraint: `feedback_config_ui` memory (toggles/pills/numbers only, TOTP auth).
**Done when:** a short decision list is written here, and anything chosen is built and deployed.

### ~~H6 — Retire the terminal dashboard~~ ✅ DONE 2026-09-17 — removed; references updated; `textual` dropped; graveyard entry added
*(user request, 2026-09-17: "long obsolete")* Remove `scripts/dashboard.py` (571 lines, TUI).
The web dashboard replaced it. Before deleting, check the references in `start.sh`, `README.md`,
`CLAUDE.md`, `docs/PROJECT_MAP.md`, `scripts/eod_summary.py`, and the `mm/stats.py` comment, and
make sure nothing imports it. Record it in `docs/strategy_graveyard.md` ("Decided Against /
retired") so it isn't rebuilt.
**Done when:** the file is gone, no reference is left dangling, and the full suite passes.

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

## Amendments

- **2026-09-16** — Folded in a Codex review (`docs/CLAUDE_REVIEW_HANDOFF_2026-09-16.md`, committed
  unedited as its own artifact; cross-model findings are input to verify, not fact). Verified
  against the repo before adopting: the 2024+ contamination (graveyard line ~56). Adopted: Step 0b,
  Step 1b, the 6b correction, and a softer headline ("disappears under the modeled costs" rather
  than "was the transaction costs" — same numbers, more precise claim). Its engineering
  recommendations matched Steps 2–7 and did not change the order.

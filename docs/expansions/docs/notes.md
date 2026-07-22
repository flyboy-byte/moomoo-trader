# Notes

> **Tier:** High-level (working scratchpad) · **Audience:** you only — this is a
> living notes file, not a polished deliverable · **Use when:** ongoing, update as
> real answers replace open questions.

Working scratchpad for decisions and questions that are still open. Update this file
as answers come in from real tests or research.

---

## Route 1 — Data Mining

### Open technical questions

**H1 (first-bar predictive):** What's the right lookforward window? 10:00–11:00 was
proposed arbitrarily. Should it be 10:00–12:00? Just the next 15 minutes? The right
window depends on what mechanism you'd hypothesize — if it's "momentum continuation,"
maybe 30 minutes; if it's "gap fill," maybe 90 minutes. Decide before running the
script to avoid cherry-picking the window after seeing the result.

**H2 (gap × VIX):** The gap_fade backtest engine returns trades with `gap_pct` as an
attribute. Confirm this is an actual field on `GapFadeTrade` before writing the
cross-join with VIX data. (Check `mm/gap_fade.py` dataclass definition.)

**H3 (autocorrelation):** How to handle the extended-hours bars? The CSVs include
pre-market (4:00–9:30) and post-market (16:00–20:00) bars. The autocorrelation
question is probably most interesting for RTH only (9:30–16:00). Filter explicitly.

**Sanity check pattern:** How to confirm a null result is a real null, not a bug?
Plan: add one known-positive test — BB lower touch → 5-bar forward return should be
positive on average (if it's not, the script has a bug). Run this sanity check in
every mining script before reporting a null.

### Sequencing — a reasonable next stretch of work

1. Write `scripts/mine_first_bar.py` (H1) — simplest, no new module needed
2. Add sanity-check pattern to it, confirm it works on a known edge
3. Run it, record the result in `route-1-data-mining.md`
4. If positive: write OOS validation, then deploy or park
5. If null: move to H3 (autocorrelation) — different data shape, might be more fruitful
6. H2 (gap × VIX) is lowest priority — only meaningful with more gap_fade live data

### Things to explicitly decide before committing further

- **Which hypothesis to run first** — H1 is simplest (already decided above)
- **OOS split date** — what date to use as the in-sample / out-of-sample boundary.
  Common choices: 2024-01-01 (start of archive) / 2025-01-01 (OOS) / 2026-01-01 (OOS-hold).
  Using 2024-01-01 as the in-sample start and holding 2026+ as OOS is reasonable
  given the archive size.

---

## Route 2 — LLM Signal Layer

### Credit alert

Anthropic credits are cheap but finite. Two options — pick one:
- **Console (zero code):** `console.anthropic.com` → Billing → set a low-balance email alert.
  Anthropic sends the email natively. No code needed. Do this first.
- **Programmatic (if you want it in-app):** After each `classify_regime()` call, parse the
  `x-anthropic-credits-remaining` response header (if Anthropic exposes it) and send a
  Discord webhook notification when it drops below a threshold. Use the existing
  `mm/notifications.py` Discord hook — zero new infra. Add as a post-call check in
  `mm/morning_regime.py`.

Recommendation: set the console billing alert first (2 minutes). Add the programmatic check
later only if you want it visible in the paper runner's Discord feed.

### Open technical questions

**Futures premium:** The initial architecture doc defers futures premium (needs quote
context at 9:20 ET, which is pre-market). Is VIX + prior-session close enough context
for the model to make a useful label? Unknown until tested. Start without futures,
add if label quality is poor.

**Macro calendar implementation:** Hardcoded Python dict for 2026 known dates is fine
as an MVP. The calendar is small (≈ 12 FOMC dates, 12 CPI dates, 8 NFP dates per year).
Maintaining it manually at year-start is < 30 minutes. A live scraper can come later.

**Which `_eval_*` functions to gate:** Start with `_eval_bb_kdj` only (it's the most
affected by choppy conditions — mean reversion is worse when there's no range). Do NOT
gate `_eval_orb` or `_eval_vwap_pb` in the initial build. Add them only after shadow
mode shows labels have predictive value for those specific strategies.

**Shadow-mode log format:** The shadow mode should log: `today's regime label, confidence,
reason, would_block (boolean), strategies_that_would_be_blocked`. Add a
`mm/events.py` or `paper.log` signal_skip event with `"shadow_only": true` so the
diagnose script can surface it without affecting P&L metrics.

**Prompt versioning:** Add a `prompt_version: "v1"` field to the output JSON so a
prompt change is distinguishable from a model behavior change in the shadow logs.

### Sequencing — a reasonable next stretch of work

1. Get Anthropic API key and install `anthropic` SDK in venv
2. Write 15-line test in a scratch script: call `claude-haiku-4-5` with draft prompt,
   parse JSON, confirm output format
3. Write `mm/morning_regime.py` with `classify_regime()` function
4. Add config fields to `mm/config.py`
5. Write `scripts/classify_regime.py` standalone runner
6. Run it manually for today and yesterday — do the labels make sense?
7. Wire shadow gate in `mm/evals.py` (`_eval_bb_kdj` only, `would_block` log-only)
8. Add VPS cron entry
9. Let shadow mode run for 2 weeks
10. Write the three replay tests
11. Review shadow log, decide whether to enable gate

### Things to explicitly decide before committing further

- **Shadow-mode event format** — decide before implementing so the diagnose script
  can be updated in the same PR
- **`REGIME_GATE_ENABLED=false` vs. no env var** — false is better (explicit intent),
  but means the cron still runs even when the gate is disabled. That's fine — the
  labels are cheap to generate and the shadow log is useful regardless.
- **VPS `.env` security** — the `ANTHROPIC_API_KEY` goes into the VPS `.env` file
  directly. Never pass it via command line args (would appear in process list).

### Open naming question

`morning_regime.py` is the current name for the new module. Alternative: `regime.py`.
Shorter, but more ambiguous (could be a filter, a classification, a scorer). Keep
`morning_regime.py` — the "morning" part communicates when it runs and why it's
separate from the live eval loop.

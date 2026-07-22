# Approach

> **Tier:** High-level (decision input) · **Audience:** decision-maker ·
> **Use when:** deciding go/no-go on the approach, and planning what to validate before
> spending real time. Several open items here are flagged for handoff to external deep
> research — see [`research-handoff.md`](./research-handoff.md).

This is early reasoning — treat every claim as a working hypothesis to test, not a
conclusion, until it's been checked against something real.

---

## Route 1 — Data Mining

### Alternatives considered

**Do nothing (wait for more live data):** Valid option — the strategies are running and
accumulating data. The counter is that "more data" won't answer "is there a non-obvious
edge in the opening bar?" — that's a research question, not a sample-size question.

**Read published microstructure research instead:** Could find edges in the literature
that apply to this data. But the point of Route 1 is to find something *in this
specific data*, not to re-implement someone else's finding. Literature review is a
complement, not a substitute.

**Use a proper feature-selection framework (sklearn, etc.):** Heavyweight for the
actual question. The three candidate hypotheses are specific and testable without a
full feature pipeline. Build the pipeline if a finding justifies it, not in advance.

**Chosen approach — narrow hypothesis-driven mining scripts:** Start with three
specific, testable hypotheses. Each becomes a 50-100 line script that outputs a table.
Kill hypotheses fast (< 1 hour of writing + running per hypothesis). This is faster
than any ML framework and produces interpretable outputs.

### What needs to be validated before investing real time

1. **Does the candle archive actually have enough coverage per hypothesis?** For H1
   (first-bar predictive), need days where both the 9:30–9:35 bar and the 10:00–11:00
   window are present. Extended-time candles complicate the time-key alignment.
   *Fast check: run `pd.read_csv(combined_csv).groupby(df.time_key.dt.date).size().min()`
   and confirm ≥ 70 bars per day (RTH alone is 78 bars at 5-min).*

2. **Is the backtest engine fast enough to iterate across 2+ years at this cadence?**
   The existing `run_backtest()` processes 50k candles in < 5 seconds. Mining scripts
   will run offline, not in the live loop, so iteration speed is fine.

3. **Can a null result be trusted?** The risk is that a script finds "no edge" when
   there actually is one (implementation bug, wrong time alignment, survivor bias in
   which days have full coverage). Every null result needs a sanity check: try it on
   a known edge (e.g. BB lower touch → upward mean reversion) and verify it shows up.

### Cost side

- **Time to first hypothesis result:** 2–4 hours per hypothesis (write script, run,
  interpret, write a conclusion)
- **Ongoing maintenance:** near-zero — mining scripts are offline tools, not live code
- **Monetary cost:** zero — all runs against local candle CSVs

### Time-to-first-real-signal

Write `scripts/mine_first_bar.py` in one session. Run it. If the 9:30 bar direction
has any predictive value for the 10:00–11:00 window, it will show up as a non-flat
return distribution conditioned on bar direction.

### Bottom line

The research loop is low-cost to build and fast to iterate. The biggest risk is that
all three candidate hypotheses come back null — that's a valid scientific result, not a
failure, but it means Route 1 contributes no new signal. If all three are null, the
right move is to document them in `strategy_graveyard.md` and either stop here or
generate three more hypotheses from looking at the actual data distributions.

---

## Route 2 — LLM Signal Layer

### Alternatives considered

**Purely quantitative regime filter (VIX threshold):** Already partially explored
(VIX gate for ORB, inconclusive per graveyard). Reproducible, no API dependency,
backtestable. The counter is it can't incorporate unstructured context (macro calendar,
futures structure). The LLM approach is richer but harder to backtest.

**Simple rules-based morning filter:** e.g. "skip entries on FOMC days, CPI days."
This is actually the right MVP before adding an LLM. The LLM version generalizes this
but adds complexity. *Recommended: implement the macro-calendar skip as a config list
first (SKIP_ENTRY_DATES=YYYY-MM-DD,...), then layer the LLM on top.*

**Fine-tuned model on historical regime → outcome pairs:** Heavyweight, requires
labeled training data (what is "choppy" empirically? how do you label it after the
fact?). Out of scope for now. If the Claude API approach produces good labels, the
natural next step would be to build a labeled dataset from shadow mode and fine-tune.

**Chosen approach — zero-shot Claude API call with structured output:** Fast to
implement, naturally handles unstructured context like calendar events, and requires
no labeled training data. The risk is prompt sensitivity (small wording changes might
shift labels). Mitigated by shadow-mode observation period before enabling the gate.

### What needs to be validated before investing real time

1. **Does claude-haiku-4-5 reliably return valid JSON in the expected format?**
   *Fast check: call the API manually with a test prompt, verify `json.loads()` works
   on 10 different synthetic inputs. If it fails, add a structured output / JSON mode
   call parameter.*

2. **Do the regime labels have face validity?** Run shadow mode for 2 weeks and look
   at whether "choppy" days were actually choppy, "risk_off" days actually had
   downside pressure. This is a qualitative check, not a quantitative one.

3. **Is the fail-open behavior actually fail-open?** Delete `logs/regime_YYYY-MM-DD.json`
   and confirm that `_load_regime_today()` returns "neutral" and no entries are blocked.

### Cost side

- **Time to build:** 4–8 hours (mm/morning_regime.py + config changes + evals.py
  gate + test + VPS cron setup)
- **Ongoing maintenance:** small — the prompt may need tuning if the API returns
  unexpected labels. The cron adds one more failure point to monitor.
- **Monetary cost:** claude-haiku-4-5 at ~$0.00025/1K input tokens. A 300-token
  prompt costs < $0.0001 per call. At 1 call/day × 250 trading days/year = ~$0.025/year.
  Negligible. (Inferred from public Anthropic pricing — see `research-handoff.md`.)

### Time-to-first-real-signal

Get an Anthropic API key. Write 15 lines of Python calling the Anthropic SDK with the
draft prompt. Run it. The time-to-first-signal for Route 2 is faster than Route 1
if the API key already exists — one call confirms the output format.

### Bottom line

The LLM gate is architecturally clean (one module, one config flag, fail-open default)
and low-cost to operate. The main risk is prompt quality — the regime label is only
useful if it actually reflects something about the day. The shadow-mode observation
period is the mitigation: 2 weeks of classifying before enabling gates means the first
real gate decisions are based on observed label quality, not assumption.

### Architectural traps specific to this codebase

**Module-level config bind (critical):** Any code that does `from .config import cfg`
at module level will read a stale config if the paper runner is ever reloaded (see
CLAUDE.md — this was a real bug fixed 2026-06-18 in strategy.py, backtest.py,
research.py). `mm/morning_regime.py` and the `_load_regime_today()` helper in
`mm/evals.py` must use the safe pattern:
```python
from . import config as _config
# ... inside function:
cfg = _config.cfg
```

**Replay test coverage:** The `_eval_*` functions are all exercised by `tests/test_replay.py`.
Adding `_load_regime_today()` to any `_eval_*` function means the replay tests will
try to load `logs/regime_YYYY-MM-DD.json` during test runs — and fail if the file
doesn't exist. The helper must return "neutral" when the file is absent (fail-open),
and the replay tests should exercise both the "file present → gate fires" and
"file absent → neutral → entry proceeds" paths.

**evals.py exit-before-entry ordering:** In every `_eval_*` function, the exit branch
runs BEFORE the entry branch. The regime gate must be placed inside the entry branch
only (or just before it) — not at the top of the function where it would also skip
exit processing for open positions.

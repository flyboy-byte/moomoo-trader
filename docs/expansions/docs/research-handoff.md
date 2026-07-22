# Research Handoff Workflow

> **Tier:** Meta (process doc) · **Audience:** you, during the scoping/validation
> phase · **Use when:** a doc in this packet has a claim marked unverified/inferred that
> needs real citations, current facts, or licensing specifics.

## Why this exists

Everything written in this packet is reasoning from the project codebase and general
priors — there's no live verification behind it except where explicitly noted. The right
tool for closing those gaps is a **deep research engine with live web access**
(Claude.ai research mode, ChatGPT research mode) run in the browser — not this
coding session, which shouldn't be the source of record for claims that need to be
current and citable.

## Current handoff queue

| # | Question | Source doc | Suggested engine | Why that engine |
| - | -------- | ---------- | ----------------- | ---------------- |
| 1 | What is the current per-token pricing for `claude-haiku-4-5`? The docs estimate < $0.01/day but use a number that may be stale. | `approach.md` (Route 2 cost side) | Claude research mode | Anthropic pricing page is frequently updated; need current numbers |
| 2 | Does the Anthropic Python SDK (`anthropic` package) support forced JSON output / structured output mode, and if so, what's the call signature? Or is a system prompt sufficient for `claude-haiku-4-5`? | `infrastructure.md` (Route 2 tools) | Claude research mode | SDK docs evolve; structured output was added for some models after initial release |
| 3 | Is there an established, maintained Python library for fetching US macro event calendars (FOMC, CPI, NFP) that doesn't require a paid data subscription? | `notes.md` (Route 2 macro calendar) | ChatGPT deep research | Broader awareness of open-source financial data tools; may know of yfinance or pandas_market_calendars extensions |
| 4 | Are there published academic or practitioner findings on intraday return autocorrelation in US ETFs (SPY/QQQ/IWM) at 5-minute resolution? Specifically: is lag-1 autocorrelation positive (momentum) or negative (mean-reversion) in the 9:30–11:00 window? | `route-1-data-mining.md` (H3) | ChatGPT deep research | Microstructure literature is better covered in ChatGPT's training data; want sourced findings to compare against our empirical result |
| 5 | Is there prior work on LLM-based regime classification for systematic trading? Any published results on accuracy or edge vs. purely quantitative filters? | `overview.md` (Route 2 novelty claim) | Claude research mode | Relevant for calibrating novelty claim; also useful for knowing what prompt structures have been tried |

## Handoff procedure

1. **Pick one row** — don't batch multiple unrelated questions.
2. **Write the prompt** using the template below and run it in the browser
   (claude.ai research mode or chatgpt.com deep research mode per the suggested engine).
   Ask for citations explicitly.
3. **Save the raw output** to `research/YYYY-MM-DD-<slug>-<engine>.md` before
   extracting anything from it.
4. **Merge findings back** into the originating doc: replace "inferred/unverified"
   language with the confirmed finding, and add a citation line pointing at the saved
   file. Don't delete the "was once unverified" note — the audit trail is useful.
5. **Update this queue** — mark the row resolved or add new questions that surfaced.

## Prompt template

```
I'm scoping an expansion to a Python paper-trading research project running
BB+KDJ, ORB, VWAP Pullback, and Gap Fade strategies on SPY/QQQ/IWM 5-min candles.

Research question: [paste the question from the queue above]

Please answer with current, sourced information — include links or citations for every
claim, note publication/last-verified dates where relevant, and flag anything that's
opinion/estimate rather than sourced fact.
```

## `research/` folder structure

Raw research session output:
```
research/
  YYYY-MM-DD-<short-topic-slug>-<engine>.md
```

Each file starts with: exact prompt used, engine name, date, then raw response.
Don't edit the raw response after saving.

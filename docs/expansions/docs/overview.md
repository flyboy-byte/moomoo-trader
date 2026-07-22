# Overview

> **Tier:** High-level · **Audience:** decision-maker, and anyone hearing about this
> expansion for the first time · **Use when:** deciding whether/how to pursue a route,
> or explaining it to someone new.
> See [`documentation-guide.md`](./documentation-guide.md) for how this fits with the
> rest of the packet.

## One-line summary

Two parallel research tracks to make the moomoo project more than "textbook strategies
accumulating paper trades": one mines the existing candle archive for non-obvious edges,
one adds the Claude API as a morning regime classifier to gate strategy entries.

## Who/what it's for

The developer (sole contributor). No external user, no deployment to share with
others — this is solo research infrastructure. The audience for findings is the
developer after a few weeks of live shadow data.

Explicitly **not** trying to be:
- A general-purpose trading framework or backtest library (many of those exist)
- A system for managing real money at scale (TRD_ENV=SIMULATE always; if real money
  ever enters scope, that's Route 3, which is parked)
- A production system with SLAs, uptime commitments, or operational on-call burden
- A publishable research paper (findings go in strategy_graveyard.md / eval docs,
  not formatted for external audiences)

---

## Route 1 — Data Mining: Find a Real Anomaly

**What it is:** A structured research loop running offline against 2+ years of
SPY/QQQ/IWM 5-min candles (RTH + extended, stored locally as combined CSVs). Write
hypothesis-driven mining scripts, measure what's actually in the data, deploy edges
that clear the pre-registered evaluation gates, kill or park everything else.

**Why this approach:** The existing strategies (BB+KDJ, ORB, VWAP Pullback, Gap Fade)
were all applied from published research. They work (most are profitable in OOS
backtests) but there's nothing novel about them. The candle archive is real,
self-collected data — it might contain edges that aren't in any paper because they're
specific to this instrument set, this time period, or this resolution.

**What success looks like:**
- At least one hypothesis produces a non-trivial, OOS-stable signal (PF ≥ 1.2 on
  ≥ 100 OOS trades, consistent across rolling 30-day walk-forward windows)
- That finding is deployed as a new `_eval_*` strategy or as a filter on an existing one
- The research loop itself is a working, repeatable process (write a script → get results
  in < 5 minutes → decide keep/kill)

**What's genuinely novel vs. applying an existing pattern:**
- The hypotheses are specific to this instrument set, this time resolution, and this
  multi-year data window — not lifted from a paper
- The research loop is novel engineering work (the mining scripts don't exist yet)
- Any actual edge found would be novel by definition
- The backtest infrastructure, evaluation criteria, and deploy pattern are all existing —
  the research itself is what's new

---

## Route 2 — LLM Signal Layer (Claude API)

**What it is:** A morning-of-session pipeline that calls the Claude API (claude-haiku-4-5)
with pre-market macro context — futures premium, VIX level, prior session stats, macro
calendar — and returns a structured regime label (trending_up | trending_down | choppy |
risk_off | neutral). That label gates or scales strategy entries for the rest of the day.
Written to `logs/regime_YYYY-MM-DD.json`, read by `mm/evals.py` before any entry.

**Why this approach:** Most systematic strategies use purely quantitative signals. This
adds a qualitative structured-output layer — something a human analyst would look at
each morning — and makes it machine-readable. The regime label is advisory, not
directional prediction: "choppy" means "mean-reversion thesis is weaker today," not
"market will fall." The implementation is clean: one new module, one config flag, all
existing `_eval_*` functions just check a cached string.

The canonical alternative is a purely quantitative regime filter (e.g. VIX threshold,
realized-vol band). That's lower-latency and reproducible. The Claude API approach is
richer — it can incorporate unstructured context like macro calendar — but adds an
API dependency and a prompt-quality risk. Both are worth having: the VIX gate was
already partially explored (see `docs/strategy_graveyard.md`); this adds the qualitative
layer on top.

**What success looks like:**
- Shadow mode runs for 2+ weeks with `REGIME_GATE_ENABLED=false` — regime labels are
  classified but don't block entries
- Labels have face validity: choppy/risk_off days look like choppy/risk_off days in
  the trade log afterward
- After enabling the gate, PF trends flat or up vs. baseline on a ≥ 20-session window
- Fail-open confirmed: if the API call fails, the day runs normally (no trades blocked)

**What's genuinely novel vs. applying an existing pattern:**
- Using an LLM as a structured morning regime classifier in a live systematic trading
  loop is novel at the solo-project level
- The shadow-mode rollout approach (classify without acting, then evaluate labels for
  2 weeks before enabling the gate) is a principled way to validate prompt quality
  without affecting live P&L during evaluation
- The integration pattern (`_load_regime_today()` with fail-open default) is designed
  to be zero-risk to existing strategies if the API is removed later

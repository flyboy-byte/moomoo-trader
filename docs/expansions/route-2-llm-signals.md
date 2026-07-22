# Route 2 — LLM Signal Layer (Claude API)

**Status:** Scaffolding — not started  
**Priority:** High (primary candidate)

## The Idea

Every morning before market open, call the Claude API with macro context and get back
a structured regime label that gates or scales strategy entries for the day.

This is not "use AI to predict the market." It's using an LLM as a structured
context-aggregation layer: take things a human analyst would check (futures,
VIX level, macro calendar, prior session behavior) and turn them into a machine-
readable label the entry logic can act on.

## Why This Is Interesting

- Novel: most systematic strategies use purely quantitative signals. This is a
  legitimate research direction (LLM-as-market-regime-classifier).
- The integration is clean: one new module, one config flag, one call per day.
  The existing `_eval_*` functions just check a cached label before firing.
- Something to write about: "we used Claude API as a morning regime gate" is a real
  thing, not a rehash.
- Fast to prototype: the API call itself is ~15 lines of Python.

## Proposed Architecture

### Daily Regime Classification

**When:** ~9:20 ET, before market open (add to `premarket_session()` or new
`morning_regime.py` module).

**Input context to Claude:**
```
SPY futures premium/discount: {es_pct}%
QQQ futures: {nq_pct}%
VIX current: {vix}  (prior close from vix_daily.jsonl)
VIX prior close: {vix_prev}
Today's macro calendar: {calendar_events}  (FOMC, CPI, NFP, etc.)
Prior session: SPY {spy_prev_close_pct}% | range {spy_prev_range}%
Prior session: QQQ {qqq_prev_close_pct}%
```

**Prompt structure (draft):**
```
Classify today's US equity session regime based on pre-market context.
Respond ONLY with a JSON object: {"regime": "<label>", "confidence": <0-1>, "reason": "<one sentence>"}
Regime options: trending_up | trending_down | choppy | risk_off | neutral
```

**Output stored in:** `logs/regime_YYYY-MM-DD.json` — so replay + backtesting can
read the same file format, and the label is auditable.

### Config Integration

**`.env`:**
```
ANTHROPIC_API_KEY=sk-ant-...
REGIME_GATE_ENABLED=true
REGIME_GATE_STRATEGIES=bb_kdj,bb_kdj_loose   # which strategies to gate
REGIME_SKIP_LABELS=choppy,risk_off           # regime labels that skip entry
```

**`mm/config.py`:**
```python
anthropic_api_key: str = _get("ANTHROPIC_API_KEY", "")
regime_gate_enabled: bool = _get("REGIME_GATE_ENABLED", "false").lower() == "true"
regime_gate_strategies: list[str] = _get("REGIME_GATE_STRATEGIES", "").split(",")
regime_skip_labels: list[str] = _get("REGIME_SKIP_LABELS", "choppy,risk_off").split(",")
```

### Live Integration in evals.py

```python
# mm/evals.py — near top of each gated _eval_* function
if cfg.regime_gate_enabled and strategy in cfg.regime_gate_strategies:
    label = _load_regime_today()
    if label in cfg.regime_skip_labels:
        elog.signal_skip(symbol, "regime_gate", regime=label)
        return position
```

`_load_regime_today()` reads `logs/regime_YYYY-MM-DD.json`, returns label string or
`"neutral"` if file missing (fail-open — don't block trades if API call failed).

### Replay / Backtest Integration

Replay already reads from logs/ — regime files slot in naturally. For backtesting:
- Regime files are stored forever (gitignored but kept)
- Offline replay through `replay.py` would pick up the correct label per day
- For historical sweep: generate synthetic regime labels from VIX + futures proxy data
  (the Claude call is the real version; the proxy is for historical sweep only)

## Data Sources for the API Call

| Context | Source | How |
|---|---|---|
| VIX | `logs/vix_daily.jsonl` | Already fetched nightly via `scripts/fetch_vix_morning.py` |
| Futures premium | `moomoo-api` quote context | `quote_ctx.get_market_snapshot(["US.ES2412"])` |
| Prior session stats | Last row in candle CSV | Read last day's open/close/range from combined CSV |
| Macro calendar | Hardcoded or scraped | Weekly hardcoded is fine initially; scraper later |

## Modules to Build

- `mm/morning_regime.py` — `classify_regime(date_str) -> RegimeResult`
  - Takes context dict, calls Claude API (anthropic SDK)
  - Writes `logs/regime_YYYY-MM-DD.json`
  - Returns `RegimeResult(label, confidence, reason)`
- `mm/evals.py` — add `_load_regime_today()` helper (10 lines, reads cached file)
  - Add regime gate inside each gated `_eval_*` function
- `scripts/classify_regime.py` — standalone runner: fetch context, call API, print result
  - Can be run manually or via cron at 9:20 ET
- Add to `install_cron.sh` — morning regime call at 9:20 ET on VPS

## Evaluation

After 30+ trading days with gate enabled:
- Does blocking `choppy`/`risk_off` days improve PF vs baseline?
- Do the labels have face validity? (Are they actually predicting something?)
- Do `confidence` scores matter? (High-confidence blocks more meaningful than low?)

This is an empirical question. The gate starts with `REGIME_GATE_ENABLED=false` (no
effect) and is flipped after a 2-week shadow-log period where regime is classified
but entries are not blocked. Same shadow-mode pattern used for gap_fade premarket filter.

## Risks and Notes

- The API call adds a network dependency to the morning flow. Always fail-open
  (if API returns error or file missing, treat as `neutral`, don't block anything).
- Model choice: `claude-haiku-4-5` is fast and cheap for this structured classification.
  The input is short (~200 tokens), output is ~30 tokens.
- The regime label is advisory, not directional prediction. "Choppy" means
  "mean reversion thesis is weaker today" — not "market will fall."
- Keep the API key in `.env` only. Never commit it.

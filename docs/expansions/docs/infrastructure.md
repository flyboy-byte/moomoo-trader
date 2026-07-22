# Infrastructure

> **Tier:** Low-level (build detail) · **Audience:** whoever is actually building this ·
> **Use when:** setting up tools and scaffolding before building the first real
> version. Assumes the reader has already read
> [`overview.md`](./overview.md) and doesn't need the framing re-explained.

---

## Route 1 — Data Mining

### Core tools / platforms

- Python 3.11+ (venv at `.venv/`)
- `pandas` — already installed, all candle loading uses it
- `numpy` — for correlation and distribution stats
- No new dependencies needed; both numpy and pandas are already present

### Data / storage

All data already exists locally:
- `logs/US_SPY_K_5M_combined.csv` — 2+ years of SPY 5-min candles (RTH + extended)
- `logs/US_QQQ_K_5M_combined.csv` — same for QQQ
- `logs/US_IWM_K_5M_combined.csv` — same for IWM
- `logs/vix_daily.jsonl` — 646 records (2024-01-01 to now), backfilled using yfinance

Mining scripts write their output to stdout / logging (no persistent output files needed
unless a finding is worth saving to `docs/expansions/research/`).

### Hard constraints (do not violate)

- All mining is offline against the candle CSVs — no live market calls during mining
- TRD_ENV=SIMULATE always — mining scripts never touch the paper runner
- OOS validation required before deploying any finding: the data used to find the edge
  must be a different date range than the data used to confirm it
- Pre-registered evaluation gates: PF ≥ 1.2, ≥ 100 OOS trades, walk-forward consistent
  (same gates as existing strategies in `docs/evaluation_criteria.md`)

### Security-relevant infrastructure

None — mining runs locally against files, no API keys, no outbound calls.

### Testing infrastructure

**For the mining scripts themselves:** No automated tests needed — these are research
tools, not production code. The sanity-check is: run the script on a known edge
(BB lower touch → upward return) and confirm it shows up.

**For any new `_eval_*` strategy deployed from a finding:** Must add a replay test in
`tests/test_replay.py` following the existing pattern. Use the FakeBroker replay path
to confirm the strategy fires on expected candles and is silent on non-qualifying candles.

### Files to create

| File | What it does |
|---|---|
| `scripts/mine_first_bar.py` | H1: load all CSVs, extract 9:30–9:35 bar per day, compute conditional return distribution for 10:00–11:00 window |
| `scripts/mine_autocorrelation.py` | H3: compute lag-1 autocorr of 5-min returns by hour-of-day bucket across all days |
| `scripts/backtest_gap_fade.py` | Extend with `--sweep-vix` to segment gap_fade trades by VIX band (H2) |

### Files to modify if a finding is deployed

| File | Change |
|---|---|
| `mm/evals.py` | Add new `_eval_<finding>()` following the existing pattern |
| `mm/paper.py` | Add strategy name to `STRATEGY_MAP` and `KNOWN_STRATEGIES` |
| `mm/config.py` | Add any new config knobs (same scalar/list field pattern) |
| `.env` | Add new strategy to `STRATEGIES=` |
| `docs/evaluation_criteria.md` | Register pre-deployment gates for the new strategy |
| `docs/ARCHITECTURE.md` | Add strategy to the deployed strategy table |
| `tests/test_replay.py` | Add replay test for the new strategy |

---

## Route 2 — LLM Signal Layer

### Core tools / platforms

- `anthropic` Python SDK — **not yet installed** (add to `requirements.txt`)
  - `pip install anthropic` in venv
  - Model: `claude-haiku-4-5` (fast, cheap, structured output capable)
- Python `json` (stdlib) — parsing API response
- Python `logging` (stdlib) — all output via existing logger pattern

### Data / storage

- `logs/regime_YYYY-MM-DD.json` — one file per trading day, written at 9:20 ET by the
  morning classify call, read by `_load_regime_today()` in evals.py
  - Format: `{"date": "YYYY-MM-DD", "regime": "choppy", "confidence": 0.82, "reason": "...", "model": "claude-haiku-4-5", "ts": "2026-07-21T09:20:15"}`
  - Stored in `logs/` which is gitignored — never committed
- `logs/vix_daily.jsonl` — already exists, read by `classify_regime()` to get VIX context
- Last-row of combined candle CSVs — read at classification time for prior-session stats

### Hard constraints (do not violate)

- **Fail-open always:** if `logs/regime_YYYY-MM-DD.json` is absent or malformed,
  `_load_regime_today()` returns `"neutral"` and entries proceed normally
- **Exits never gated:** the regime check must live inside the entry branch of `_eval_*`,
  never before the exit branch — open positions always get their exit evaluation
- **Module-level config bind:** use `from . import config as _config` + `_config.cfg.*`
  at call time in any module that might be reloaded (see CLAUDE.md)
- **API key in .env only:** `ANTHROPIC_API_KEY=sk-ant-...` — never hardcoded, never committed
- TRD_ENV=SIMULATE always — the regime gate blocks entries, never forces them

### Security-relevant infrastructure

- `ANTHROPIC_API_KEY` in `.env` (gitignored). Add to VPS `.env` separately via SSH.
- The API call goes outbound from the VPS at 9:20 ET — confirm the VPS has outbound
  HTTPS to `api.anthropic.com`. (Inferred: should work on standard VPS — verify.)
- No auth needed for reading regime files (they're local files, not an API endpoint)

### Testing infrastructure

**`scripts/classify_regime.py` (standalone test runner):**
- Run manually: `python scripts/classify_regime.py --date 2026-07-21`
- Confirm it writes a valid JSON file to `logs/regime_2026-07-21.json`
- Confirm the regime field is one of the 5 valid labels

**`tests/test_replay.py` additions (required before enabling gate):**

1. **Gate fires on skip label:**
   ```python
   # Write regime_YYYY-MM-DD.json with regime="choppy" to the log dir
   # Replay with REGIME_GATE_ENABLED=true, REGIME_SKIP_LABELS=choppy
   # Assert: no bb_kdj entries in the replay output
   ```

2. **Gate is neutral when file missing (fail-open):**
   ```python
   # Don't write any regime file
   # Replay with REGIME_GATE_ENABLED=true
   # Assert: bb_kdj entries still fire normally (same as without gate)
   ```

3. **Exits still fire when gate would block entries:**
   ```python
   # Replay with an open position entering before the regime check date
   # Set regime="choppy" for the exit date
   # Assert: exit fires correctly even though entry would have been blocked
   ```

### Files to create

| File | What it does |
|---|---|
| `mm/morning_regime.py` | `classify_regime(date_str, context) -> RegimeResult`; `_load_regime_today()` |
| `scripts/classify_regime.py` | Standalone runner: fetch context, call API, write JSON, print result |

### Files to modify

| File | Change | Line-level guidance |
|---|---|---|
| `mm/config.py` | Add 3 new fields | After `orb_vol_mult_overrides`: add `anthropic_api_key`, `regime_gate_enabled`, `regime_gate_strategies`, `regime_skip_labels` |
| `mm/evals.py` | Add `_load_regime_today()` + gate in `_eval_bb_kdj` | Gate goes inside `elif not already_entered and ...` branch, before the signal check. Same module-import pattern as rest of evals.py. |
| `mm/evals.py` | Optionally gate `_eval_orb` and `_eval_vwap_pb` | Only after shadow mode confirms labels have predictive value — start with bb_kdj only |
| `requirements.txt` | Add `anthropic>=0.30` | After existing deps |
| `.env` | Add `ANTHROPIC_API_KEY=` and `REGIME_GATE_ENABLED=false` | At end of file |
| `docs/ARCHITECTURE.md` | Add `REGIME_GATE_ENABLED`, `REGIME_SKIP_LABELS` to Key Config Vars | Under the strategy config block |
| `scripts/install_cron.sh` | Add 9:20 ET cron: `classify_regime.py` | After existing fetch_vix_morning.py cron entry |
| `tests/test_replay.py` | 3 new replay tests (see above) | Following existing `test_gap_fade_replay` pattern |

### What's notably absent (gaps to fill)

- **Macro calendar source:** Route 2 docs mention including FOMC/CPI/NFP dates in the
  context prompt. No live calendar feed is wired. Initial version will use a hardcoded
  Python dict of known 2026 dates (trivially maintainable); a live scraper can come later.
- **Futures premium data:** The moomoo API can fetch ES/NQ futures quotes, but `mm/connection.py`
  context manager is used inside the running paper loop — the morning regime call runs
  before market open when the quote context may not be ready. Initial version will omit
  futures premium and rely on VIX + prior-session close only; add futures later if the
  label quality suffers without it.
- **VPS outbound HTTPS confirmation:** Assumed to work; verify before first deploy.

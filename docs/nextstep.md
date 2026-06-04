# Next Steps: Strategy Expansion

*Planned June 4 2026. First live ORB trades fired today (SPY @ $755.37, QQQ @ $739.65). Plumbing validated.*

Source: `docs/STRATEGY_EXPANSION.md`

---

## Step 0 — Update docs (5 min)
- `CLAUDE.md` — add first live trades note, update "what to build next"
- `memory/project_state.md` — same
- Commit immediately, no code changes

---

## Step 1 — ORB Shorts ✅ DONE (2026-06-04)

**Why first:** Recovers ~50% of ORB edge currently discarded. Clear scope, low risk.

**`mm/config.py`**
- Add `orb_shorts_enabled: bool = _bool("ORB_SHORTS_ENABLED", False)`

**`mm/paper.py` — PaperPosition**
- Add `direction: str = "long"` field

**`mm/paper.py` — new helpers**
- `_place_short()` — mirrors `_place_buy()`, uses `TrdSide.SELL_SHORT`
- `_place_cover()` — mirrors `_place_sell()`, uses `TrdSide.BUY_BACK`

**`mm/paper.py` — `_eval_orb()` entry**
- Existing: `close > or_high + vol_ok` → long (unchanged)
- Add: `close < or_low + vol_ok + cfg.orb_shorts_enabled` → short
  - stop = or_high, target = close - cfg.orb_target_mult × or_range

**`mm/paper.py` — `_eval_orb()` exit**
- Stop: `close >= stop_price if short else close <= stop_price`
- Target: `close <= target_price if short else close >= target_price`
- Time stop 15:45 ET: unchanged

**Tests** (`tests/test_orb_shorts.py`):
- Short entry fires on close < or_low with volume
- Short stop: exits on close >= stop (not <=)
- Short target: exits on close <= target (not >=)
- Long behavior unchanged

> **Senior Engineer Note:** When implementing `_place_short()`, verify that `calc_qty()` correctly handles the symbol size cap for shorts. In Moomoo SIMULATE, shorting is generally permissive, but we should ensure our internal cap is respected and that the order doesn't fail due to "insufficient power" (margin) if the paper account balance has been modified.

**Deploy:** `ORB_SHORTS_ENABLED=true` in VPS .env after tests pass

---

## Step 2 — Logging improvements ✅ DONE (2026-06-04)

**`mm/paper.py`:**
- `bar_eval` — `regime_label` added (trending/ranging, ADX>25) — all 4 strategies
- `position_open` — `direction` + `vix_at_entry: null` added
- `position_close` — `hold_bars` + `direction` added — all 4 strategies

**Bugs fixed during audit:**
- `_load_position` was not restoring `direction` field on restart (would flip short exit logic)
- `_eval_vwap` was missing `regime_label` in bar_eval and `hold_bars` in position_close
- Dead code removed from diagnose_logs.py `_uptime()`

---

## Step 3 — VIX daily regime filter + relaxed MR mode

**Prereq:** `pip install yfinance`, add to `requirements.txt`

**`mm/config.py`**
```python
vix_block_threshold: float = float(_get("VIX_BLOCK_THRESHOLD", "25"))
vix_relax_threshold: float = float(_get("VIX_RELAX_THRESHOLD", "30"))
```

**`mm/paper.py`** — fetch VIX once at session start:
```python
def _fetch_vix() -> float | None:
    try:
        return yf.download("^VIX", period="1d", interval="1d", progress=False)["Close"].iloc[-1]
    except Exception:
        return None
```

**Entry gating** in `_eval_bb_kdj()`:
- VIX > 25 → `signal_skip("vix_block")`
- VIX > 30 → use `effective_score = 1` instead of `cfg.min_signal_score`

**Backtest result (2026-06-04): DO NOT DEPLOY — VIX filter makes things worse OOS.**
```
Combined OOS (2024+):  Baseline=1.224  Block>=20=1.208  Block>=25=1.181  Relax>30=1.193
IWM specifically:      Baseline=1.033  Block>=20=0.800  (VIX>20 days are IWM's best entries)
SPY exception:         Block>=20 OOS=1.443 (vs 1.287 baseline) but not worth IWM damage
```
Verdict: moved to graveyard. Code in `scripts/backtest_vix_filter.py` for reference.

---

## Step 4 — diagnose_logs.py ✅ DONE (2026-06-04)

```bash
python scripts/diagnose_logs.py [--date YYYY-MM-DD] [--all] [--symbol US.SPY]
```

Output: uptime gaps, signal hit rates, staleness (market hours only), trade pairs with direction, skip reasons.

---

## Step 5 — Push architecture pilot (future, big lift)

**Do not start until Steps 1-4 are live and stable.**

`scripts/live_price_monitor.py` — subscribe to `StockQuoteHandlerBase`, log ticks to CSV for 30 min. Measure frequency, gaps, reconnect events. If stable → design intra-bar exits. If flaky → stay on polling.

---

## Files per step

| Step | Files |
|------|-------|
| 0 | CLAUDE.md, memory/project_state.md |
| 1 | mm/config.py, mm/paper.py, tests/test_orb_shorts.py |
| 2 | mm/paper.py |
| 3 | mm/config.py, mm/paper.py, requirements.txt, scripts/backtest_vix_filter.py |
| 4 | scripts/diagnose_logs.py (new) |
| 5 | scripts/live_price_monitor.py (new, pilot only) |

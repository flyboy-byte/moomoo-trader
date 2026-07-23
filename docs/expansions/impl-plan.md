# Implementation Plan — Remaining Buildable Items

> Working reference. Each item has: files to touch, function signatures, test strategy,
> cron additions, and codebase-specific gotchas. Order = recommended build sequence.

---

## Constraints that apply to everything here

- **Clock seam**: `clock.today()` / `clock.now_et()` — never `date.today()` / `datetime.now()`
- **Config bind**: `cfg = _config.cfg` inside each function — never at module level
- **Fail-open**: every Claude API call must return a usable default on any exception
- **Exit-before-entry**: new gates go inside entry branch only — exits always fire
- **JSONL logging**: skipped entries use `elog.signal_skip(reason, score, bonus, min_score, strategy=...)`
- **Shadow mode**: `ENABLED=false` → log the would-block event, return False, proceed normally

---

## Item 1 — Weekly Synthesis (≈1h)

**What:** Every Monday at 9:00 ET, Claude reads last week's trade events and posts a
structured analysis to Discord. Closes the feedback loop between regime labels and outcomes.

### Files

| File | Action |
|---|---|
| `scripts/weekly_synthesis.py` | Create |
| `scripts/install_cron.sh` | Add Monday cron line |
| `mm/morning_regime.py` | Add `synthesize_week()` function |

### `mm/morning_regime.py` — add `synthesize_week()`

```python
def synthesize_week(
    week_str: str | None = None,   # ISO week "2026-W30"; defaults to last week
    logs_dir: Path | None = None,
) -> dict:
    """
    Read last week's JSONL trade events, call Claude for structured analysis,
    write logs/synthesis_YYYY-WW.json. Fail-open: returns raw stats dict on API error.
    """
    import anthropic
    from isoweek import Week  # stdlib: datetime.date.isocalendar()

    cfg = _config.cfg
    if logs_dir is None:
        logs_dir = cfg.logs_dir

    # Determine date range for last week
    today = clock.today()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_friday = last_monday + timedelta(days=4)
    week_str = week_str or f"{last_monday.year}-W{last_monday.isocalendar()[1]:02d}"

    # --- Load and filter events ---
    KEEP = {"position_open", "position_close", "signal_skip"}
    rows = []
    for jsonl in sorted(logs_dir.glob("paper_*_202*.jsonl")):
        date_part = jsonl.stem.split("_")[-1]
        if not (str(last_monday) <= date_part <= str(last_friday)):
            continue
        for line in jsonl.read_text().splitlines():
            try:
                e = json.loads(line)
                if e.get("event") in KEEP:
                    rows.append(e)
            except json.JSONDecodeError:
                pass

    # --- Build compact summary table ---
    trades = [r for r in rows if r["event"] in ("position_open", "position_close")]
    skips  = [r for r in rows if r["event"] == "signal_skip"]
    regime_labels = _load_week_regimes(logs_dir, last_monday, last_friday)

    stats = _build_week_stats(trades, skips, regime_labels)

    out_path = logs_dir / f"synthesis_{week_str}.json"

    if not cfg.anthropic_api_key:
        out_path.write_text(json.dumps({"week": week_str, "stats": stats}, indent=2))
        return stats

    prompt = _build_synthesis_prompt(week_str, stats)
    try:
        client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        msg = client.messages.create(
            model=cfg.anthropic_model,
            max_tokens=512,
            system=(
                "You are a trading strategy analyst reviewing a week of paper-trading results. "
                "Respond ONLY with a valid JSON object. No markdown, no explanation."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(raw)
    except Exception as e:
        log.warning("Weekly synthesis API call failed (%s) — writing raw stats only", e)
        parsed = {"error": str(e)}

    result = {"week": week_str, "stats": stats, "analysis": parsed,
              "model": cfg.anthropic_model, "ts": datetime.utcnow().isoformat()}
    out_path.write_text(json.dumps(result, indent=2))

    # Log API usage
    _append_api_usage(logs_dir, {
        "call_type": "weekly_synthesis", "week": week_str,
        "input_tokens": getattr(getattr(msg, "usage", None), "input_tokens", 0),
        "output_tokens": getattr(getattr(msg, "usage", None), "output_tokens", 0),
    })

    log.info("Weekly synthesis for %s written → %s", week_str, out_path)
    return result
```

Helper functions to add in the same file:
```python
def _load_week_regimes(logs_dir, monday, friday) -> dict[str, str]:
    """Return {date_str: regime} for each trading day in the week."""
    result = {}
    d = monday
    while d <= friday:
        label = load_regime_today(str(d), logs_dir=logs_dir)
        result[str(d)] = label
        d += timedelta(days=1)
    return result

def _build_week_stats(trades, skips, regime_labels) -> dict:
    """Aggregate trade events into a compact summary dict."""
    # Group closes by strategy
    by_strat: dict[str, list] = {}
    for e in trades:
        if e["event"] == "position_close":
            s = e.get("strategy", "unknown")
            by_strat.setdefault(s, []).append(e)
    summary = {}
    for strat, closes in by_strat.items():
        pnls = [c.get("pnl", 0) for c in closes]
        summary[strat] = {
            "trades": len(closes),
            "wins": sum(1 for p in pnls if p > 0),
            "total_pnl": round(sum(pnls), 2),
        }
    regime_counts: dict[str, int] = {}
    for label in regime_labels.values():
        regime_counts[label] = regime_counts.get(label, 0) + 1
    skip_counts: dict[str, int] = {}
    for sk in skips:
        r = sk.get("reason", "unknown")
        skip_counts[r] = skip_counts.get(r, 0) + 1
    return {"by_strategy": summary, "regime_counts": regime_counts, "skip_counts": skip_counts}

def _build_synthesis_prompt(week_str, stats) -> str:
    return f"""Weekly paper-trading results for {week_str}:

Strategy results:
{json.dumps(stats['by_strategy'], indent=2)}

Regime labels this week (days classified):
{json.dumps(stats['regime_counts'])}

Signal skip reasons (entry blocks):
{json.dumps(stats['skip_counts'])}

Respond with this JSON:
{{
  "summary": "<2-3 sentence plain-English summary>",
  "bright_spots": ["<strategy or pattern that worked>"],
  "concerns": ["<what's losing or behaving oddly>"],
  "regime_verdict": "<did regime labels correlate with outcomes this week?>",
  "recommendation": "<one concrete next action, or 'more data needed'>",
  "data_quality": "<comment on sample size / noise>"
}}"""
```

### `scripts/weekly_synthesis.py`

```python
#!/usr/bin/env python3
"""Post weekly trading synthesis to Discord. Run Monday 9:00 ET via cron."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.morning_regime import synthesize_week
from mm.notifications import notify

def main():
    result = synthesize_week()
    analysis = result.get("analysis", {})
    week = result.get("week", "")
    summary = analysis.get("summary", "No summary available.")
    rec = analysis.get("recommendation", "")
    msg = f"**Weekly Synthesis {week}**\n{summary}"
    if rec:
        msg += f"\n> {rec}"
    notify(msg)
    print(msg)

if __name__ == "__main__":
    main()
```

### Cron addition in `install_cron.sh`

```bash
# 9:00 ET = 13:00 UTC Mon. Reads last week's JSONL and posts synthesis to Discord.
SYNTHESIS_LINE='0 13 * * 1 cd ~/moomoo && .venv/bin/python scripts/weekly_synthesis.py >> logs/cron_synthesis.log 2>&1'
update_line "weekly_synthesis.py" "$SYNTHESIS_LINE"
```

### Tests

```python
# tests/test_weekly_synthesis.py
def test_build_week_stats_empty():
    from mm.morning_regime import _build_week_stats
    stats = _build_week_stats([], [], {})
    assert stats["by_strategy"] == {}
    assert stats["regime_counts"] == {}

def test_build_week_stats_with_trades():
    closes = [
        {"event": "position_close", "strategy": "orb", "pnl": -1.2},
        {"event": "position_close", "strategy": "orb", "pnl": 2.5},
        {"event": "position_close", "strategy": "bb_kdj", "pnl": 0.8},
    ]
    stats = _build_week_stats(closes, [], {"2026-07-21": "neutral"})
    assert stats["by_strategy"]["orb"]["trades"] == 2
    assert stats["by_strategy"]["orb"]["wins"] == 1
    assert abs(stats["by_strategy"]["orb"]["total_pnl"] - 1.3) < 0.01
    assert stats["regime_counts"]["neutral"] == 1

def test_synthesize_week_fail_open(tmp_path, monkeypatch):
    """API failure must still write raw stats file, not raise."""
    import mm.config as _config
    monkeypatch.setattr(_config.cfg, "anthropic_api_key", "bad-key")
    # write a minimal paper JSONL in tmp_path
    ...  # fixture with one position_close event
    result = synthesize_week(logs_dir=tmp_path)
    assert "stats" in result
    assert (tmp_path / f"synthesis_{result['week']}.json").exists()
```

---

## Item 2 — ORB Setup Scorer (≈2h)

**What:** Before entering an ORB trade, call Claude with the specific setup context
(OR range, vol ratio, VIX, morning regime) and get a 0–1 confidence. Shadow mode first.

### Files

| File | Action |
|---|---|
| `mm/morning_regime.py` | Add `score_orb_setup()` |
| `mm/evals.py` | Wire into `_eval_orb()` entry branch |
| `mm/config.py` | Add `orb_setup_scorer_enabled`, `orb_entry_min_confidence` |
| `.env` | Add both keys (disabled by default) |

### `mm/config.py` — add two fields

```python
# ORB per-trade setup scorer (Route 2 Phase 2)
orb_setup_scorer_enabled: bool = _bool("ORB_SETUP_SCORER_ENABLED", False)
orb_entry_min_confidence: float = float(_get("ORB_ENTRY_MIN_CONFIDENCE", "0.65"))
```

### `mm/morning_regime.py` — add `score_orb_setup()`

```python
# Module-level cache: (symbol, bar_ts_str) → result dict. Never call twice per bar.
_orb_score_cache: dict[str, dict] = {}

def score_orb_setup(
    symbol: str,
    bar_ts: str,
    setup: dict,
    logs_dir: Path | None = None,
) -> dict:
    """
    Return {"confidence": float, "reason": str} for this ORB setup.
    Fail-open: returns {"confidence": 0.5, "reason": "unavailable"} on any error.
    Cached per (symbol, bar_ts) — safe to call multiple times per bar.
    """
    import anthropic

    cache_key = f"{symbol}:{bar_ts}"
    if cache_key in _orb_score_cache:
        return _orb_score_cache[cache_key]

    _FAIL_OPEN = {"confidence": 0.5, "reason": "unavailable"}

    cfg = _config.cfg
    if not cfg.anthropic_api_key:
        return _FAIL_OPEN

    prompt = (
        f"Rate this Opening Range Breakout setup. Respond ONLY with JSON: "
        f'{"{"}"confidence": <0.0-1.0>, "reason": "<one sentence>"{"}"}\\n\\n'
        f"Symbol: {symbol}\\n"
        f"Date: {setup.get('date')}\\n"
        f"Direction: {setup.get('direction')} (close {'above OR high' if setup.get('direction') == 'LONG' else 'below OR low'})\\n"
        f"OR range: {setup.get('or_range_pct', 0):.2f}% of price\\n"
        f"Volume ratio: {setup.get('vol_ratio', 0):.1f}× 20-bar MA\\n"
        f"VIX prior close: {setup.get('vix', 'unknown')}\\n"
        f"Prior session: {setup.get('prior_chg', 0):+.2f}%\\n"
        f"Morning regime: {setup.get('regime', 'neutral')} (confidence {setup.get('regime_confidence', 0):.2f})\\n"
        f"Time since open: {setup.get('mins_since_open', 0)} min"
    )

    try:
        client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        msg = client.messages.create(
            model=cfg.anthropic_model, max_tokens=64,
            system="You are a technical trading setup evaluator. Respond ONLY with valid JSON.",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(raw)
        result = {
            "confidence": float(parsed.get("confidence", 0.5)),
            "reason": str(parsed.get("reason", "")),
        }
        _append_api_usage(cfg.logs_dir if logs_dir is None else logs_dir, {
            "call_type": "orb_setup_scorer", "symbol": symbol, "bar_ts": bar_ts,
            "input_tokens": msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
            "confidence": result["confidence"],
        })
    except Exception as e:
        log.warning("score_orb_setup failed (%s) — using 0.5", e)
        result = _FAIL_OPEN

    _orb_score_cache[cache_key] = result
    return result


def clear_orb_score_cache() -> None:
    _orb_score_cache.clear()
```

Also extract `_append_api_usage()` as a shared helper (currently inline in `classify_regime`):
```python
def _append_api_usage(logs_dir: Path, extra: dict) -> None:
    record = {"ts": datetime.utcnow().isoformat(), "host": socket.gethostname(), **extra}
    with open(logs_dir / "api_usage.jsonl", "a") as f:
        f.write(json.dumps(record) + "\n")
```

### `mm/evals.py` — wire into `_eval_orb()` entry branch

After the VIX gate passes, before the long/short split (around line 650):

```python
# ORB setup scorer — per-trade Claude confidence gate
if cfg.orb_setup_scorer_enabled or True:  # always compute when scorer configured
    or_range_pct = (or_range / close) * 100
    vol_ratio = vol / vol_ma if vol_ma else 0
    vix_val = _load_vix_today(bar_date.strftime("%Y-%m-%d"))
    morning_regime = load_regime_today(bar_date.strftime("%Y-%m-%d"))
    setup = {
        "date": bar_date.strftime("%Y-%m-%d"),
        "direction": "LONG" if close > or_high else "SHORT",
        "or_range_pct": round(or_range_pct, 3),
        "vol_ratio": round(vol_ratio, 2),
        "vix": vix_val,
        "regime": morning_regime,
        "mins_since_open": int((bar_time - bar_time.replace(hour=9, minute=30)).total_seconds() / 60),
    }
    score_result = score_orb_setup(symbol, str(candle_ts), setup)
    confidence = score_result["confidence"]
    if cfg.orb_setup_scorer_enabled and confidence < cfg.orb_entry_min_confidence:
        log.info("%-8s [orb]    SKIP  orb_claude_score=%.2f < min=%.2f  reason=%s",
                 symbol, confidence, cfg.orb_entry_min_confidence, score_result["reason"])
        elog.signal_skip("orb_claude_score", score=0, bonus=0, min_score=0,
                         strategy="orb", confidence=confidence,
                         reason=score_result["reason"])
        return position
    else:
        log.info("%-8s [orb]    SCORE  confidence=%.2f  %s  (gate_enabled=%s)",
                 symbol, confidence, score_result["reason"], cfg.orb_setup_scorer_enabled)
```

Add import at top of evals.py:
```python
from .morning_regime import load_regime_today, score_orb_setup
```

### `.env` additions

```
# ORB per-trade setup scorer (shadow mode first)
ORB_SETUP_SCORER_ENABLED=false
ORB_ENTRY_MIN_CONFIDENCE=0.65
```

### Tests

```python
# tests/test_orb_scorer.py
from unittest.mock import patch, MagicMock

def test_score_orb_setup_fail_open():
    """API failure returns 0.5 confidence, never raises."""
    from mm.morning_regime import score_orb_setup, clear_orb_score_cache
    clear_orb_score_cache()
    with patch("anthropic.Anthropic") as mock:
        mock.return_value.messages.create.side_effect = RuntimeError("network error")
        result = score_orb_setup("US.SPY", "2026-07-23 10:05:00",
                                  {"date": "2026-07-23", "direction": "LONG"},
                                  logs_dir=Path("/tmp"))
    assert result["confidence"] == 0.5
    assert result["reason"] == "unavailable"

def test_score_orb_setup_cached():
    """Second call with same key returns cached value without API call."""
    from mm.morning_regime import score_orb_setup, clear_orb_score_cache, _orb_score_cache
    clear_orb_score_cache()
    _orb_score_cache["US.SPY:ts1"] = {"confidence": 0.9, "reason": "cached"}
    result = score_orb_setup("US.SPY", "ts1", {})
    assert result["confidence"] == 0.9  # returned from cache, no API call
```

### Verification after deploy

```bash
# Watch shadow logs after 1-2 ORB setups fire:
grep orb_claude_score logs/paper_US_SPY_$(date +%Y-%m-%d).jsonl | python3 -m json.tool
# Check api_usage.jsonl for call_type=orb_setup_scorer entries:
grep orb_setup_scorer logs/api_usage.jsonl | tail -5
```

---

## Item 3 — Regime Gate Replay Tests (≈30 min)

**What:** Three test cases to assert the gate wiring is correct. Add to `tests/`.

### Pattern — how to override config in replay tests

Looking at how existing tests work: `replay()` calls `_reload_paper()` which re-imports
config from `.env`. To inject a test config, write a temp `.env` and monkeypatch
`mm.config.cfg` directly, then call `clear_regime_cache()` between cases.

```python
# tests/test_regime_gate.py
import json
from pathlib import Path
import pytest
from mm.morning_regime import clear_regime_cache

CSV = Path("logs/US_SPY_K_5M_combined.csv")
pytestmark = pytest.mark.skipif(not CSV.exists(), reason="candle CSVs not on disk")

START, END = "2026-05-27", "2026-05-27"  # single day is enough


def _write_regime(tmp_path: Path, date_str: str, regime: str):
    record = {"date": date_str, "regime": regime, "confidence": 0.9,
              "reason": "test", "model": "test", "prompt_version": "v1",
              "ts": "2026-01-01T00:00:00"}
    (tmp_path / f"regime_{date_str}.json").write_text(json.dumps(record))


def test_regime_choppy_blocks_bb_kdj_entry(tmp_path, monkeypatch):
    """regime=choppy + gate enabled → no bb_kdj entries."""
    import mm.config as _config
    _write_regime(tmp_path, START, "choppy")
    clear_regime_cache()
    monkeypatch.setattr(_config.cfg, "regime_gate_enabled", True)
    monkeypatch.setattr(_config.cfg, "regime_gate_strategies", ["bb_kdj", "bb_kdj_loose"])
    monkeypatch.setattr(_config.cfg, "regime_skip_labels", ["choppy", "risk_off"])
    monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)

    from mm.replay import replay, FakeBroker
    stats = replay([CSV], ["bb_kdj"], start=START, end=END,
                   fill_mode="touch", out_dir=tmp_path / "out", quiet=True)

    events = [json.loads(l)
              for f in (tmp_path / "out").glob("paper_*.jsonl")
              for l in f.read_text().splitlines()]
    bb_opens = [e for e in events if e["event"] == "position_open"
                and e.get("strategy") == "bb_kdj"]
    gate_skips = [e for e in events if e["event"] == "signal_skip"
                  and e.get("reason") == "regime_gate"]
    assert len(bb_opens) == 0, "regime gate should have blocked all bb_kdj entries"
    # gate skips should only appear if there were underlying signals
    # (they may be 0 if the test window had no bb_kdj signals anyway)
    clear_regime_cache()


def test_regime_missing_file_is_fail_open(tmp_path, monkeypatch):
    """No regime file → neutral → entries proceed normally."""
    import mm.config as _config
    clear_regime_cache()
    # Don't write any regime file
    monkeypatch.setattr(_config.cfg, "regime_gate_enabled", True)
    monkeypatch.setattr(_config.cfg, "regime_gate_strategies", ["bb_kdj", "bb_kdj_loose"])
    monkeypatch.setattr(_config.cfg, "regime_skip_labels", ["choppy", "risk_off"])
    monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)

    from mm.morning_regime import load_regime_today
    label = load_regime_today(START, logs_dir=tmp_path)
    assert label == "neutral"  # fail-open
    clear_regime_cache()


def test_exit_fires_on_gated_day(tmp_path, monkeypatch):
    """Open position must exit even when regime gate would block a new entry."""
    import mm.config as _config
    _write_regime(tmp_path, START, "choppy")
    clear_regime_cache()
    monkeypatch.setattr(_config.cfg, "regime_gate_enabled", True)
    monkeypatch.setattr(_config.cfg, "regime_gate_strategies", ["bb_kdj", "bb_kdj_loose"])
    monkeypatch.setattr(_config.cfg, "regime_skip_labels", ["choppy", "risk_off"])
    monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)

    # Run a 2-day window: day 1 neutral (entry opens), day 2 choppy (exit must still fire)
    _write_regime(tmp_path, "2026-05-27", "neutral")
    _write_regime(tmp_path, "2026-05-28", "choppy")
    # This is a structural test — if the exit branch is gated, positions would never close.
    # We verify it by checking that any opens on day 1 have matching closes by end of day 2.
    from mm.replay import replay
    stats = replay([CSV], ["bb_kdj"], start="2026-05-27", end="2026-05-28",
                   fill_mode="touch", out_dir=tmp_path / "out2", quiet=True)
    assert stats["reconcile_mismatches"] == 0
    clear_regime_cache()
```

---

## Item 4 — Route 1: First-Bar Mining (≈1.5h)

**What:** Does the 9:30–9:35 first bar predict 10am–11am returns?

### `scripts/mine_first_bar.py`

```python
#!/usr/bin/env python3
"""
H1: Does the 9:30-9:35 first bar predict 10:00-11:00 returns?

Extracts first-bar features (direction, body%, range%) and forward returns,
runs correlation and Mann-Whitney U test. OOS discipline: derive on 2022-2023,
test on 2024+.

Usage:
    python scripts/mine_first_bar.py --all
    python scripts/mine_first_bar.py logs/US_SPY_K_5M_combined.csv
"""
import argparse
import sys
from pathlib import Path
import pandas as pd
import numpy as np
from scipy import stats as sp

sys.path.insert(0, str(Path(__file__).parent.parent))
from mm.backtest import load_candles

DERIVE_END = "2023-12-31"
OOS_START  = "2024-01-01"


def extract_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ts"] = pd.to_datetime(df["time_key"])
    df["date"] = df["ts"].dt.date
    df["time"] = df["ts"].dt.time

    from datetime import time as dtime
    FIRST_BAR = dtime(9, 35)
    T1000     = dtime(10, 0)
    T1100     = dtime(11, 0)

    rows = []
    for date, g in df.groupby("date"):
        first = g[g["time"] == FIRST_BAR]
        fwd   = g[(g["time"] >= T1000) & (g["time"] <= T1100)]
        if first.empty or fwd.empty:
            continue
        f = first.iloc[0]
        body = f["close"] - f["open"]
        rng  = f["high"] - f["low"]
        fwd_ret = (fwd.iloc[-1]["close"] - fwd.iloc[0]["open"]) / fwd.iloc[0]["open"] * 100
        rows.append({
            "date": str(date),
            "first_bar_dir": 1 if body > 0 else -1,    # +1 = bullish, -1 = bearish
            "first_bar_body_pct": body / f["open"] * 100,
            "first_bar_range_pct": rng / f["open"] * 100,
            "fwd_ret_pct": fwd_ret,
        })
    return pd.DataFrame(rows)


def report(feat: pd.DataFrame, label: str) -> None:
    up   = feat[feat["first_bar_dir"] ==  1]["fwd_ret_pct"]
    down = feat[feat["first_bar_dir"] == -1]["fwd_ret_pct"]
    if len(up) < 10 or len(down) < 10:
        print(f"{label}: insufficient data ({len(feat)} days)")
        return

    corr, p_corr = sp.pearsonr(feat["first_bar_body_pct"], feat["fwd_ret_pct"])
    u_stat, p_mw = sp.mannwhitneyu(up, down, alternative="two-sided")
    effect = (up.mean() - down.mean()) / feat["fwd_ret_pct"].std()

    print(f"\n{label}  (n={len(feat)} days)")
    print(f"  Up-bar fwd ret:   mean={up.mean():+.3f}%  median={up.median():+.3f}%  n={len(up)}")
    print(f"  Down-bar fwd ret: mean={down.mean():+.3f}%  median={down.median():+.3f}%  n={len(down)}")
    print(f"  Pearson r={corr:+.3f}  p={p_corr:.4f}")
    print(f"  Mann-Whitney p={p_mw:.4f}  Cohen's d={effect:.3f}")
    sig = p_mw < 0.05 and abs(effect) > 0.2
    print(f"  → {'SIGNAL: worth investigating further' if sig else 'NULL: no meaningful edge'}")


def run_file(path: Path) -> None:
    sym = path.stem.split("_K_")[0].replace("_", ".", 1)
    df = load_candles(path)
    feat = extract_features(df)
    print(f"\n{'='*60}\n{sym}")
    derive = feat[feat["date"] <= DERIVE_END]
    oos    = feat[feat["date"] >= OOS_START]
    report(derive, f"  IN-SAMPLE  (≤{DERIVE_END})")
    report(oos,    f"  OOS        (≥{OOS_START})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csvs", nargs="*")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    logs = Path("logs")
    paths = [Path(p) for p in args.csvs] if args.csvs else \
            sorted(logs.glob("US_*_K_5M_combined.csv")) if args.all else []
    if not paths:
        ap.print_help(); sys.exit(1)
    for p in paths:
        run_file(p)

if __name__ == "__main__":
    main()
```

**Decision rule:** deploy only if OOS p < 0.05 AND Cohen's d > 0.2 AND n > 100.
If result is null, document in `docs/strategy_graveyard.md`.

### Tests

```python
# tests/test_mine_first_bar.py
def test_extract_features_returns_expected_columns(tmp_path):
    # build minimal candle DF with known first bar + forward window
    import pandas as pd
    from scripts.mine_first_bar import extract_features
    ...  # fixture: bullish first bar, then 10am-11am positive return
    feat = extract_features(df)
    assert "first_bar_dir" in feat.columns
    assert "fwd_ret_pct" in feat.columns
    assert feat.iloc[0]["first_bar_dir"] == 1   # bullish bar
```

---

## Item 5 — Gap Fade Premarket Filter (parked, blocked)

**Status:** Blocked — requires live premarket candle fetch before 9:35 ET.

`mm/premarket.py::premarket_session()` needs a live `QuoteContext` open at ~9:30 ET
to fetch premarket bars. The live paper runner doesn't currently call it.

**What activation requires:**
1. A premarket fetch step in `mm/paper.py` (or a new `scripts/fetch_premarket.py`)
   that runs at 9:30 ET and saves sessions to a temp dict in memory or a file
2. `mm/evals.py::_eval_gap_fade()` to read that dict before the 9:35 first bar
3. `GAP_PREMARKET_FILTER_ENABLED=true` in `.env`

**Minimum to unblock:** write `scripts/fetch_premarket.py` that opens a QuoteContext,
pulls the last 30 premarket bars for each symbol, and saves to `logs/premarket_YYYY-MM-DD.json`.
Then `_eval_gap_fade()` loads it. Until then: leave `GAP_PREMARKET_FILTER_ENABLED=false`.

---

## Build order

| # | Item | Effort | Value |
|---|---|---|---|
| 1 | Regime gate replay tests | 30 min | Closes a known gap in test coverage |
| 2 | Weekly synthesis | 1h | Immediate feedback loop, uses existing data |
| 3 | mine_first_bar.py | 1.5h | Answers a concrete research question |
| 4 | ORB setup scorer | 2h | Claude in the entry path, per-trade |
| 5 | Gap fade filter | 2h+ | Blocked on premarket infrastructure |

Start with tests (always) → synthesis (quick win with existing data) → mining → scorer.

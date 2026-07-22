"""
Morning regime classifier — calls the Claude API at ~9:20 ET with pre-market context
and returns a structured regime label. Writes logs/regime_YYYY-MM-DD.json.

The live eval loop reads the cached file; this module is called once per trading day
by scripts/classify_regime.py (run via VPS cron at 9:20 ET).

Fail-open: if the API call fails or the file is missing, _load_regime_today()
returns "neutral" and all strategy entries proceed normally.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path

from . import clock
from . import config as _config
from .logger import get_logger

log = get_logger("regime")

VALID_LABELS = {"trending_up", "trending_down", "choppy", "risk_off", "neutral"}
PROMPT_VERSION = "v1"

_SYSTEM = (
    "You are a pre-market US equity session classifier. "
    "Respond ONLY with a valid JSON object and nothing else. "
    "No markdown, no explanation, no extra text."
)

_USER_TEMPLATE = """\
Classify today's US equity session regime based on pre-market context.

Context:
- Date: {date}
- VIX prior close: {vix} ({vix_note})
- SPY prior session: close {spy_chg:+.2f}%, range {spy_range:.2f}%
- QQQ prior session: close {qqq_chg:+.2f}%, range {qqq_range:.2f}%
- Macro calendar today: {calendar}

Regime options:
  trending_up   — market showing upward momentum, mean-reversion less reliable
  trending_down — market showing downward pressure, mean-reversion less reliable
  choppy        — range-bound, no clear direction, whipsaws likely
  risk_off      — elevated fear/vol (VIX spike, macro shock), avoid new entries
  neutral       — no strong signal, strategies run normally

Respond with exactly this JSON structure:
{{"regime": "<label>", "confidence": <0.0-1.0>, "reason": "<one sentence max>"}}
"""


@dataclass
class RegimeResult:
    date: str
    regime: str
    confidence: float
    reason: str
    model: str
    prompt_version: str
    ts: str


def _vix_note(vix: float | None) -> str:
    if vix is None:
        return "unknown"
    if vix >= 30:
        return "elevated — risk-off zone"
    if vix >= 20:
        return "above average"
    if vix >= 15:
        return "normal"
    return "low"


def _load_vix(logs_dir: Path, date_str: str) -> float | None:
    vix_file = logs_dir / "vix_daily.jsonl"
    if not vix_file.exists():
        return None
    with open(vix_file) as f:
        for line in f:
            try:
                rec = json.loads(line)
                if rec.get("date") == date_str:
                    return float(rec["vix_prev_close"])
            except (KeyError, ValueError, json.JSONDecodeError):
                continue
    return None


def _load_prior_session(logs_dir: Path, symbol: str) -> tuple[float, float]:
    """Return (pct_change, range_pct) for the last trading day in the combined CSV."""
    import pandas as pd
    sym_slug = symbol.replace(".", "_")
    csv = logs_dir / f"{sym_slug}_K_5M_combined.csv"
    if not csv.exists():
        return 0.0, 0.0
    try:
        df = pd.read_csv(csv, usecols=["time_key", "open", "close", "high", "low"])
        df["time_key"] = pd.to_datetime(df["time_key"])
        df["date"] = df["time_key"].dt.date
        last_day = df["date"].max()
        day_df = df[df["date"] == last_day]
        if day_df.empty:
            return 0.0, 0.0
        day_open = day_df.iloc[0]["open"]
        day_close = day_df.iloc[-1]["close"]
        day_high = day_df["high"].max()
        day_low = day_df["low"].min()
        pct_chg = (day_close - day_open) / day_open * 100
        range_pct = (day_high - day_low) / day_open * 100
        return round(pct_chg, 2), round(range_pct, 2)
    except Exception:
        return 0.0, 0.0


def _macro_calendar(date_str: str) -> str:
    """Return a short description of known macro events for this date, or 'none'."""
    known: dict[str, str] = {
        # FOMC 2026 (approximate — update at year-start)
        "2026-01-28": "FOMC rate decision",
        "2026-01-29": "FOMC rate decision",
        "2026-03-18": "FOMC rate decision",
        "2026-03-19": "FOMC rate decision",
        "2026-05-06": "FOMC rate decision",
        "2026-05-07": "FOMC rate decision",
        "2026-06-17": "FOMC rate decision",
        "2026-06-18": "FOMC rate decision",
        "2026-07-28": "FOMC rate decision",
        "2026-07-29": "FOMC rate decision",
        "2026-09-16": "FOMC rate decision",
        "2026-09-17": "FOMC rate decision",
        "2026-11-04": "FOMC rate decision",
        "2026-11-05": "FOMC rate decision",
        "2026-12-16": "FOMC rate decision",
        "2026-12-17": "FOMC rate decision",
        # CPI 2026 (approximate)
        "2026-01-15": "CPI release",
        "2026-02-12": "CPI release",
        "2026-03-12": "CPI release",
        "2026-04-10": "CPI release",
        "2026-05-13": "CPI release",
        "2026-06-11": "CPI release",
        "2026-07-14": "CPI release",
        "2026-08-12": "CPI release",
        "2026-09-10": "CPI release",
        "2026-10-13": "CPI release",
        "2026-11-12": "CPI release",
        "2026-12-10": "CPI release",
        # NFP (first Friday of each month)
        "2026-01-09": "Non-farm payrolls",
        "2026-02-06": "Non-farm payrolls",
        "2026-03-06": "Non-farm payrolls",
        "2026-04-03": "Non-farm payrolls",
        "2026-05-08": "Non-farm payrolls",
        "2026-06-05": "Non-farm payrolls",
        "2026-07-10": "Non-farm payrolls",
        "2026-08-07": "Non-farm payrolls",
        "2026-09-04": "Non-farm payrolls",
        "2026-10-02": "Non-farm payrolls",
        "2026-11-06": "Non-farm payrolls",
        "2026-12-04": "Non-farm payrolls",
    }
    return known.get(date_str, "none")


def classify_regime(
    date_str: str | None = None,
    logs_dir: Path | None = None,
) -> RegimeResult:
    """
    Call the Claude API with pre-market context and return a RegimeResult.
    Writes the result to logs/regime_YYYY-MM-DD.json.
    Raises on API error — callers should catch and fall back to neutral.
    """
    import anthropic

    cfg = _config.cfg
    if not cfg.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in .env")

    if date_str is None:
        date_str = clock.today().isoformat()
    if logs_dir is None:
        logs_dir = cfg.logs_dir

    vix = _load_vix(logs_dir, date_str)
    spy_chg, spy_range = _load_prior_session(logs_dir, "US_SPY")
    qqq_chg, qqq_range = _load_prior_session(logs_dir, "US_QQQ")
    calendar = _macro_calendar(date_str)

    prompt = _USER_TEMPLATE.format(
        date=date_str,
        vix=f"{vix:.1f}" if vix is not None else "unavailable",
        vix_note=_vix_note(vix),
        spy_chg=spy_chg,
        spy_range=spy_range,
        qqq_chg=qqq_chg,
        qqq_range=qqq_range,
        calendar=calendar,
    )

    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    log.info("Calling %s for regime classification (date=%s)", cfg.anthropic_model, date_str)

    message = client.messages.create(
        model=cfg.anthropic_model,
        max_tokens=128,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    log.debug("Raw API response: %s", raw)

    # Strip markdown code fences if the model wraps the JSON despite being told not to
    clean = raw
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1]  # drop first line (```json or ```)
        clean = clean.rsplit("```", 1)[0]  # drop trailing ```
    clean = clean.strip()

    try:
        parsed = json.loads(clean)
        regime = parsed.get("regime", "neutral")
        if regime not in VALID_LABELS:
            log.warning("Unexpected regime label %r — falling back to neutral", regime)
            regime = "neutral"
        confidence = float(parsed.get("confidence", 0.5))
        reason = str(parsed.get("reason", ""))
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        log.warning("Failed to parse API response (%s): %r — using neutral", e, raw)
        regime, confidence, reason = "neutral", 0.0, "parse error"

    result = RegimeResult(
        date=date_str,
        regime=regime,
        confidence=round(confidence, 3),
        reason=reason,
        model=cfg.anthropic_model,
        prompt_version=PROMPT_VERSION,
        ts=datetime.utcnow().isoformat(),
    )

    out_path = logs_dir / f"regime_{date_str}.json"
    out_path.write_text(json.dumps(asdict(result), indent=2))
    log.info("Regime for %s: %s (confidence=%.2f) → %s", date_str, regime, confidence, out_path)

    return result


# Module-level cache: date_str → regime label. Avoids re-reading the file on every bar.
_regime_cache: dict[str, str] = {}


def load_regime_today(date_str: str, logs_dir: Path | None = None) -> str:
    """
    Return today's regime label, or 'neutral' if the file is missing or unreadable.
    Result is cached per date so file I/O happens at most once per trading day.
    """
    if date_str in _regime_cache:
        return _regime_cache[date_str]

    cfg = _config.cfg
    if logs_dir is None:
        logs_dir = cfg.logs_dir

    path = logs_dir / f"regime_{date_str}.json"
    if not path.exists():
        log.debug("No regime file for %s — using neutral", date_str)
        _regime_cache[date_str] = "neutral"
        return "neutral"

    try:
        data = json.loads(path.read_text())
        label = data.get("regime", "neutral")
        if label not in VALID_LABELS:
            label = "neutral"
        _regime_cache[date_str] = label
        return label
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Failed to read regime file %s (%s) — using neutral", path, e)
        _regime_cache[date_str] = "neutral"
        return "neutral"


def clear_regime_cache() -> None:
    """Clear the in-process cache. Used in tests to reset state between runs."""
    _regime_cache.clear()

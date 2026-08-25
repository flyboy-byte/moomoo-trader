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
import socket
import time
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
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


def _extract_text(message) -> str:
    """Return the first text block from an API response, skipping ThinkingBlocks.

    claude-sonnet-5 (and other extended-thinking models) may prepend a ThinkingBlock
    before the TextBlock. Accessing content[0].text directly raises AttributeError.
    """
    for block in message.content:
        if hasattr(block, "text"):
            return block.text.strip()
    raise ValueError(f"No text block found in API response: {message.content}")


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


def _load_prior_session(
    logs_dir: Path,
    symbol: str,
    before_date: str | None = None,
) -> tuple[float, float]:
    """Return (pct_change, range_pct) for the last trading day in the combined CSV.

    before_date: if given (YYYY-MM-DD), use the last day strictly before this date.
    Useful for historical classification where the "prior session" must be anchored
    to the correct date rather than today's CSV tail.
    """
    import pandas as pd
    sym_slug = symbol.replace(".", "_")
    csv = logs_dir / f"{sym_slug}_K_5M_combined.csv"
    if not csv.exists():
        return 0.0, 0.0
    try:
        df = pd.read_csv(csv, usecols=["time_key", "open", "close", "high", "low"])
        df["time_key"] = pd.to_datetime(df["time_key"])
        df["date"] = df["time_key"].dt.date
        if before_date:
            df = df[df["date"] < pd.Timestamp(before_date).date()]
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
    prior_session_date: str | None = None,
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
    spy_chg, spy_range = _load_prior_session(logs_dir, "US_SPY", before_date=prior_session_date)
    qqq_chg, qqq_range = _load_prior_session(logs_dir, "US_QQQ", before_date=prior_session_date)
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

    raw = _extract_text(message)
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
        ts=datetime.now(timezone.utc).isoformat(),
    )

    out_path = logs_dir / f"regime_{date_str}.json"
    out_path.write_text(json.dumps(asdict(result), indent=2))
    log.info("Regime for %s: %s (confidence=%.2f) → %s", date_str, regime, confidence, out_path)

    # Append to api_usage.jsonl — prompt, response, token counts, and hostname.
    _append_api_usage(logs_dir, {
        "call_type": "classify_regime",
        "date": date_str,
        "model": cfg.anthropic_model,
        "prompt_version": PROMPT_VERSION,
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
        "system_prompt": _SYSTEM,
        "user_prompt": prompt,
        "raw_response": raw,
        "regime": regime,
        "confidence": result.confidence,
    })
    log.info("API usage logged: input=%d output=%d tokens host=%s",
             message.usage.input_tokens, message.usage.output_tokens,
             socket.gethostname())

    return result


# Module-level caches: date_str → label / confidence. Avoids re-reading the file on every bar.
_regime_cache: dict[str, str] = {}
_regime_confidence_cache: dict[str, float] = {}


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
        cached_version = data.get("prompt_version")
        if cached_version != PROMPT_VERSION:
            # Bug fix 2026-08-25 (found by external audit): a cached regime file
            # written by an older prompt version must not be silently reused as
            # if the current classifier produced it — the label's meaning can
            # change across prompt revisions. Fail open to neutral, same as a
            # missing file, rather than trusting stale-version output.
            log.warning(
                "Regime file %s has prompt_version=%r, current is %r — "
                "treating as stale, using neutral",
                path, cached_version, PROMPT_VERSION,
            )
            _regime_cache[date_str] = "neutral"
            _regime_confidence_cache[date_str] = 0.5
            return "neutral"
        label = data.get("regime", "neutral")
        if label not in VALID_LABELS:
            label = "neutral"
        _regime_cache[date_str] = label
        _regime_confidence_cache[date_str] = float(data.get("confidence", 0.5))
        return label
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Failed to read regime file %s (%s) — using neutral", path, e)
        _regime_cache[date_str] = "neutral"
        _regime_confidence_cache[date_str] = 0.5
        return "neutral"


def load_regime_confidence_today(date_str: str, logs_dir: Path | None = None) -> float:
    """Return the confidence for today's regime classification, or 0.5 if unavailable.
    Reads the regime file only if load_regime_today() hasn't already cached it.
    """
    if date_str not in _regime_confidence_cache:
        load_regime_today(date_str, logs_dir)
    return _regime_confidence_cache.get(date_str, 0.5)


def clear_regime_cache() -> None:
    """Clear the in-process cache. Used in tests to reset state between runs."""
    _regime_cache.clear()
    _regime_confidence_cache.clear()


# ---------------------------------------------------------------------------
# Shared API usage logger
# ---------------------------------------------------------------------------

def _append_api_usage(logs_dir: Path, extra: dict) -> None:
    """Append one record to logs/api_usage.jsonl with host + timestamp."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        **extra,
    }
    with open(logs_dir / "api_usage.jsonl", "a") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Weekly synthesis
# ---------------------------------------------------------------------------

def _build_week_stats(
    events: list[dict],
    regime_labels: dict[str, str],
) -> dict:
    """Aggregate trade + skip events into a compact summary dict."""
    by_strat: dict[str, dict] = {}
    for e in events:
        if e.get("event") == "position_close":
            s = e.get("strategy", "unknown")
            if s not in by_strat:
                by_strat[s] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
            pnl = float(e.get("pnl", 0))
            by_strat[s]["trades"] += 1
            by_strat[s]["wins"] += 1 if pnl > 0 else 0
            by_strat[s]["total_pnl"] = round(by_strat[s]["total_pnl"] + pnl, 2)

    skip_counts: dict[str, int] = {}
    for e in events:
        if e.get("event") == "signal_skip":
            r = e.get("reason", "unknown")
            skip_counts[r] = skip_counts.get(r, 0) + 1

    regime_counts: dict[str, int] = {}
    for label in regime_labels.values():
        regime_counts[label] = regime_counts.get(label, 0) + 1

    return {
        "by_strategy": by_strat,
        "skip_counts": skip_counts,
        "regime_counts": regime_counts,
    }


def _build_synthesis_prompt(week_str: str, stats: dict) -> str:
    return f"""Weekly paper-trading results for {week_str}:

Strategy results (paper/simulate account — not real money):
{json.dumps(stats['by_strategy'], indent=2)}

Morning regime labels this week:
{json.dumps(stats['regime_counts'])}

Entry skip reasons (how often entries were blocked and why):
{json.dumps(stats['skip_counts'])}

Respond with exactly this JSON:
{{"summary": "<2-3 sentence plain-English summary>", "bright_spots": ["<item>"], "concerns": ["<item>"], "regime_verdict": "<did regime labels seem to match outcomes?>", "recommendation": "<one concrete next action or 'more data needed'>", "data_quality": "<comment on sample size>"}}"""


def synthesize_week(
    week_str: str | None = None,
    logs_dir: Path | None = None,
) -> dict:
    """
    Read last week's JSONL trade events, call Claude for structured analysis,
    write logs/synthesis_YYYY-WW.json. Fail-open: returns raw stats on API error.
    Called by scripts/weekly_synthesis.py every Monday at 9:00 ET.
    """
    import anthropic

    cfg = _config.cfg
    if logs_dir is None:
        logs_dir = cfg.logs_dir

    today = clock.today()
    days_since_monday = today.weekday()
    last_monday = today - timedelta(days=days_since_monday + 7)
    last_friday = last_monday + timedelta(days=4)

    if week_str is None:
        year, week_num, _ = last_monday.isocalendar()
        week_str = f"{year}-W{week_num:02d}"

    # Load position_close + signal_skip events from last week's JSONL files
    KEEP = {"position_close", "signal_skip"}
    events: list[dict] = []
    for jsonl in sorted(logs_dir.glob("paper_*_202*.jsonl")):
        date_part = jsonl.stem.rsplit("_", 1)[-1]
        if not (str(last_monday) <= date_part <= str(last_friday)):
            continue
        for line in jsonl.read_text().splitlines():
            try:
                e = json.loads(line)
                if e.get("event") in KEEP:
                    events.append(e)
            except json.JSONDecodeError:
                pass

    # Collect regime labels for the week
    regime_labels: dict[str, str] = {}
    d = last_monday
    while d <= last_friday:
        ds = str(d)
        regime_labels[ds] = load_regime_today(ds, logs_dir=logs_dir)
        d += timedelta(days=1)

    stats = _build_week_stats(events, regime_labels)
    out_path = logs_dir / f"synthesis_{week_str}.json"

    # Fail-open: write raw stats even if API call fails
    if not cfg.anthropic_api_key:
        result = {"week": week_str, "stats": stats, "analysis": None,
                  "ts": datetime.now(timezone.utc).isoformat()}
        out_path.write_text(json.dumps(result, indent=2))
        log.info("Weekly synthesis (no API key) written → %s", out_path)
        return result

    prompt = _build_synthesis_prompt(week_str, stats)
    analysis: dict = {}
    input_tokens = output_tokens = 0
    try:
        client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        msg = client.messages.create(
            model=cfg.anthropic_model_cheap,
            max_tokens=512,
            system=(
                "You are a trading strategy analyst reviewing paper-trading results. "
                "Respond ONLY with a valid JSON object. No markdown, no explanation."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _extract_text(msg)
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        analysis = json.loads(raw)
        input_tokens = msg.usage.input_tokens
        output_tokens = msg.usage.output_tokens
        _append_api_usage(logs_dir, {
            "call_type": "weekly_synthesis",
            "week": week_str,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "user_prompt": prompt,
            "raw_response": raw,
        })
    except Exception as e:
        log.warning("Weekly synthesis API call failed (%s) — writing raw stats only", e)
        analysis = {"error": str(e)}

    result = {
        "week": week_str,
        "stats": stats,
        "analysis": analysis,
        "model": cfg.anthropic_model_cheap,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    out_path.write_text(json.dumps(result, indent=2))
    log.info("Weekly synthesis for %s written → %s", out_path.name, out_path)
    return result


# ---------------------------------------------------------------------------
# ORB per-trade setup scorer
# ---------------------------------------------------------------------------

_orb_score_cache: dict[str, dict] = {}
_FAIL_OPEN_SCORE = {"confidence": 1.0, "reason": "unavailable"}  # fail-open = always allow

_ORB_SCORE_SYSTEM = (
    "You are a technical trading setup evaluator for Opening Range Breakout strategies. "
    "Respond ONLY with a valid JSON object. No markdown, no explanation."
)


def score_orb_setup(
    symbol: str,
    bar_ts: str,
    setup: dict,
    logs_dir: Path | None = None,
) -> dict:
    """
    Return {"confidence": float 0-1, "reason": str} for this ORB entry setup.
    Fail-open: returns confidence=0.5 on any API error.
    Cached per (symbol, bar_ts) — safe to call multiple times per bar.
    """
    import anthropic

    cache_key = f"{symbol}:{bar_ts}"
    if cache_key in _orb_score_cache:
        return _orb_score_cache[cache_key]

    cfg = _config.cfg
    if not cfg.anthropic_api_key:
        return _FAIL_OPEN_SCORE

    prompt = (
        f"Rate this Opening Range Breakout setup on confidence 0.0-1.0.\n\n"
        f"Symbol: {symbol}\n"
        f"Date: {setup.get('date', 'unknown')}\n"
        f"Direction: {setup.get('direction', 'unknown')}\n"
        f"OR range: {setup.get('or_range_pct', 0):.2f}% of price\n"
        f"Volume ratio: {setup.get('vol_ratio', 0):.1f}x 20-bar MA\n"
        f"VIX prior close: {setup.get('vix') or 'unknown'}\n"
        f"Prior session change: {setup.get('prior_chg', 0):+.2f}%\n"
        f"Morning regime: {setup.get('regime', 'neutral')} "
        f"(confidence {setup.get('regime_confidence', 0.5):.2f})\n"
        f"Minutes since open: {setup.get('mins_since_open', 0)}\n\n"
        f'Respond with: {{"confidence": <0.0-1.0>, "reason": "<one sentence>"}}'
    )

    try:
        client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        msg = client.messages.create(
            model=cfg.anthropic_model_cheap,
            max_tokens=128,
            system=_ORB_SCORE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _extract_text(msg)
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(raw)
        result: dict = {
            "confidence": float(parsed.get("confidence", 0.5)),
            "reason": str(parsed.get("reason", "")),
        }
        _append_api_usage(logs_dir or cfg.logs_dir, {
            "call_type": "orb_setup_scorer",
            "symbol": symbol,
            "bar_ts": bar_ts,
            "input_tokens": msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
            "user_prompt": prompt,
            "raw_response": raw,
            "confidence": result["confidence"],
        })
    except Exception as e:
        log.warning("score_orb_setup failed for %s@%s (%s) — using 0.5", symbol, bar_ts, e)
        result = dict(_FAIL_OPEN_SCORE)

    _orb_score_cache[cache_key] = result
    return result


def clear_orb_score_cache() -> None:
    """Clear per-bar score cache. Used in tests."""
    _orb_score_cache.clear()

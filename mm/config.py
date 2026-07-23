from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent.parent / ".env")


def _get(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _bool(key: str, default: bool = False) -> bool:
    return _get(key, str(default)).lower() in ("true", "1", "yes")


class Config:
    host: str = _get("MOOMOO_HOST", "127.0.0.1")
    port: int = int(_get("MOOMOO_PORT", "11111"))
    trd_env: str = _get("TRD_ENV", "SIMULATE")

    live_trading_enabled: bool = _bool("LIVE_TRADING_ENABLED", False)
    live_confirmation: bool = _bool("LIVE_CONFIRMATION", False)

    symbol: str = _get("SYMBOL", "US.SPY")
    # Comma-separated list for multi-symbol paper runner. Falls back to SYMBOL if not set.
    symbols: list[str] = [s.strip() for s in _get("SYMBOLS", _get("SYMBOL", "US.SPY")).split(",") if s.strip()]
    candle_ktype: str = _get("CANDLE_KTYPE", "K_5M")

    max_trades_per_day: int = int(_get("MAX_TRADES_PER_DAY", "3"))
    # Per-strategy cap within the global daily limit. 0 = disabled (global limit only).
    # Example: MAX_TRADES_PER_STRATEGY=1 lets each strategy take at most 1 trade/day,
    # preventing ORB from consuming all 3 global slots and starving BB+KDJ/VWAP PB.
    max_trades_per_strategy: int = int(_get("MAX_TRADES_PER_STRATEGY", "0"))
    max_daily_loss: float = float(_get("MAX_DAILY_LOSS", "20"))
    max_position_dollars: float = float(_get("MAX_POSITION_DOLLARS", "50"))
    # Risk-normalized sizing: qty = risk_dollars / (entry - stop), capped by the
    # dollar cap above. 0 = disabled (use plain dollar-cap sizing). Infrastructure
    # knob per docs/evaluation_criteria.md — not a frozen strategy parameter.
    risk_dollars_per_trade: float = float(_get("RISK_DOLLARS_PER_TRADE", "0"))
    # Per-symbol overrides: "US.IWM:300,US.SPY:600" → {"US.IWM": 300.0, "US.SPY": 600.0}
    # Falls back to max_position_dollars for symbols not listed.
    symbol_size_overrides: dict[str, float] = {
        s.split(":")[0].strip(): float(s.split(":")[1].strip())
        for s in _get("SYMBOL_SIZE_OVERRIDES", "").split(",")
        if ":" in s and s.strip()
    }

    trade_password_md5: str = _get("TRADE_PASSWORD_MD5", "")
    # "strict" = BB touch + KDJ cross + bonus>=min_signal_score (production default)
    # "permissive" = BB touch only + bonus>=1 (use to validate order execution flow)
    strategy_mode: str = _get("STRATEGY_MODE", "strict")

    # KDJ window: look back N bars for a KDJ golden cross when evaluating a BB touch entry.
    # 0 = same-bar only (original behavior).
    # Sweep on IWM+QQQ 2022-2025: w=3 gives 10x more trades, PF>1.1, improves OOS.
    # SPY breaks at any window>0 — use KDJ_WINDOW_OVERRIDES=US.SPY:0 to keep SPY at same-bar only.
    kdj_window_bars: int = int(_get("KDJ_WINDOW_BARS", "0"))
    # Per-symbol overrides: "US.SPY:0,US.IWM:3" → {"US.SPY": 0, "US.IWM": 3}
    # Falls back to kdj_window_bars for symbols not listed.
    kdj_window_overrides: dict[str, int] = {
        s.split(":")[0].strip(): int(s.split(":")[1].strip())
        for s in _get("KDJ_WINDOW_OVERRIDES", "").split(",")
        if ":" in s and s.strip()
    }

    discord_webhook_url: str = _get("DISCORD_WEBHOOK_URL", "")
    dashboard_password: str = _get("DASHBOARD_PASSWORD", "")

    # Research finding: KDJ death cross exit cuts winning mean-reversion trades early.
    # Set to false (default) to use target+stop only. Set to true to restore original behavior.
    exit_on_kdj_death: bool = _bool("EXIT_ON_KDJ_DEATH", False)

    # ATR stop multiplier. Sweep tested 0.5–2.5 on 2022–2025 SPY 5-min data.
    # 1.0 ATR had best PnL (+2.34) and tied-best walk-forward consistency (7/12 windows positive).
    # 2.5 ATR had higher full-period PnL but same consistency — likely small-sample noise.
    atr_stop_mult: float = float(_get("ATR_STOP_MULT", "1.0"))

    # Bonus confirmation threshold (0-3). Core entry (BB touch + KDJ cross) is always required.
    # Bonus signals: rsi_oversold, ranging (ADX<25), volume_spike.
    # 0 = original BB+KDJ only.  2 = 51.7% win, PF=1.843, 60 trades (default).
    min_signal_score: int = int(_get("MIN_SIGNAL_SCORE", "2"))

    # Strategy selector: "bb_kdj" = original mean reversion, "vwap" = VWAP scalp day trader
    strategy_type: str = _get("STRATEGY_TYPE", "bb_kdj")
    # Multi-strategy: comma-separated list of active strategies. Defaults to strategy_type.
    # Example: STRATEGIES=bb_kdj,vwap  runs both simultaneously on the same symbols.
    active_strategies: list[str] = [
        s.strip() for s in _get("STRATEGIES", _get("STRATEGY_TYPE", "bb_kdj")).split(",")
        if s.strip()
    ]

    # VWAP strategy parameters (deprecated crossover strategy)
    vwap_band_mult: float = float(_get("VWAP_BAND_MULT", "0.5"))
    vwap_stop_mult: float = float(_get("VWAP_STOP_MULT", "0.75"))

    # VWAP Pullback strategy parameters
    # Sweep on SPY+QQQ 2022-2025: max_crosses=1 optimal (strict no-chop filter).
    # IWM fails OOS — use VWAP_PB_SYMBOLS to restrict to SPY+QQQ.
    vwap_pb_stop_mult: float = float(_get("VWAP_PB_STOP_MULT", "1.0"))
    vwap_pb_max_crosses: int = int(_get("VWAP_PB_MAX_CROSSES", "1"))
    # Comma-separated whitelist. Empty = all active symbols.
    vwap_pb_symbols: list[str] = [
        s.strip() for s in _get("VWAP_PB_SYMBOLS", "").split(",") if s.strip()
    ]
    # No entries before this ET time. Sweep confirmed 10:00 >> 9:45 (opening noise).
    # Format: "H:MM" e.g. "10:00". Default 10:00.
    vwap_pb_min_entry_time: tuple[int, int] = (
        lambda s: (int(s.split(":")[0]), int(s.split(":")[1]))
    )(_get("VWAP_PB_MIN_ENTRY_TIME", "10:00"))

    # ORB strategy parameters
    # orb_minutes: opening range window in minutes (15 or 30). Default 15.
    # Sweep: 15-min optimal for SPY/QQQ; 30-min dramatically better for IWM (PF 1.017→1.217).
    orb_minutes: int = int(_get("ORB_MINUTES", "15"))
    # Per-symbol overrides: "US.IWM:30,US.QQQ:15" → {"US.IWM": 30, "US.QQQ": 15}
    orb_minutes_overrides: dict[str, int] = {
        s.split(":")[0].strip(): int(s.split(":")[1].strip())
        for s in _get("ORB_MINUTES_OVERRIDES", "").split(",")
        if ":" in s and s.strip()
    }
    # orb_target_mult: target = mult × OR range height. 1.5 optimal per sweep (PF=1.215).
    orb_target_mult: float = float(_get("ORB_TARGET_MULT", "1.5"))
    # Per-symbol target mult overrides. OOS sweep (2024+): QQQ 2.0x (+4.3% PF), IWM 1.0x (+6%).
    orb_target_mult_overrides: dict[str, float] = {
        s.split(":")[0].strip(): float(s.split(":")[1].strip())
        for s in _get("ORB_TARGET_MULT_OVERRIDES", "").split(",")
        if ":" in s and s.strip()
    }
    orb_vol_mult: float = float(_get("ORB_VOL_MULT", "1.2"))
    # Per-symbol vol mult overrides. OOS sweep (2024+): global 1.5 optimal; SPY could use 2.0.
    orb_vol_mult_overrides: dict[str, float] = {
        s.split(":")[0].strip(): float(s.split(":")[1].strip())
        for s in _get("ORB_VOL_MULT_OVERRIDES", "").split(",")
        if ":" in s and s.strip()
    }
    orb_min_range_pct: float = float(_get("ORB_MIN_RANGE_PCT", "0.001"))
    orb_max_range_pct: float = float(_get("ORB_MAX_RANGE_PCT", "0.008"))
    # Short entries for ORB. Disable at runtime by creating STOP_SHORTS.txt in project root.
    orb_shorts_enabled: bool = _bool("ORB_SHORTS_ENABLED", True)
    # Per-symbol short allow-list. Empty = all symbols. e.g. "US.SPY,US.QQQ"
    orb_short_symbols: list = [s.strip() for s in _get("ORB_SHORT_SYMBOLS", "").split(",") if s.strip()]

    # Gap Fade pre-market filter knobs (GAP_PREMARKET_FILTER_ENABLED, GAP_PREMARKET_FILL_PCT_MIN)
    # live as self-contained module constants in mm/gap_fade.py, NOT here — that file doesn't
    # import cfg at all (deliberate, matches its other GAP_* constants). Bug fix 2026-06-17:
    # this used to duplicate those same two as dead cfg.* fields that nothing ever read —
    # a future caller could reasonably set cfg.gap_premarket_filter_enabled expecting it to
    # do something; it silently wouldn't have. Use the .env vars directly (same names), not cfg.
    # gap_premarket_vol_ratio_max stays here, genuinely unused on purpose: research found
    # volume ratio is not monotonic, not trusted as a filter (see strategy_graveyard.md) —
    # kept only as a documented placeholder, not a trap.
    gap_premarket_vol_ratio_max: float = float(_get("GAP_PREMARKET_VOL_RATIO_MAX", "1.5"))

    # LLM regime gate (Route 2 expansion)
    # classify_regime() calls Claude API at 9:20 ET, writes logs/regime_YYYY-MM-DD.json.
    # _eval_* functions check the label before entry. Fail-open: missing file = "neutral".
    anthropic_api_key: str = _get("ANTHROPIC_API_KEY", "")
    anthropic_model: str = _get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    regime_gate_enabled: bool = _bool("REGIME_GATE_ENABLED", False)
    # Strategies the gate applies to. Empty = gate applies to all active strategies.
    regime_gate_strategies: list[str] = [
        s.strip() for s in _get("REGIME_GATE_STRATEGIES", "bb_kdj,bb_kdj_loose").split(",") if s.strip()
    ]
    # Regime labels that block entry. "neutral" is never a skip label.
    regime_skip_labels: list[str] = [
        s.strip() for s in _get("REGIME_SKIP_LABELS", "choppy,risk_off").split(",") if s.strip()
    ]

    # ORB per-trade setup scorer (Route 2 Phase 2) — calls Claude before each entry.
    # Shadow mode (false): logs confidence score without blocking.
    # Live mode (true): blocks entries below orb_entry_min_confidence.
    orb_setup_scorer_enabled: bool = _bool("ORB_SETUP_SCORER_ENABLED", False)
    orb_entry_min_confidence: float = float(_get("ORB_ENTRY_MIN_CONFIDENCE", "0.65"))

    # ORB VIX gate — block ORB entries when prior-day VIX > threshold.
    # Global default: empty/unset = no global filter. Per-symbol override wins if set.
    # Sweep (2024+ OOS): IWM benefits at ≤18 (PF 1.045→1.113); QQQ hurts at every threshold;
    # SPY mild positive at 20. Deploy as IWM-only via ORB_VIX_MAX_OVERRIDES=US.IWM:18.
    # Reads logs/vix_daily.jsonl. Fail-open: missing VIX data for a date = no block.
    orb_vix_max: float | None = (
        float(_get("ORB_VIX_MAX", "")) if _get("ORB_VIX_MAX", "") else None
    )
    # Per-symbol VIX max overrides: "US.IWM:18,US.SPY:20" → {"US.IWM": 18.0, "US.SPY": 20.0}
    # Falls back to orb_vix_max for symbols not listed.
    orb_vix_max_overrides: dict[str, float] = {
        s.split(":")[0].strip(): float(s.split(":")[1].strip())
        for s in _get("ORB_VIX_MAX_OVERRIDES", "").split(",")
        if ":" in s and s.strip()
    }

    # Capital allocation. When TOTAL_CAPITAL > 0, per-slot dollars are computed automatically
    # as total_capital / (symbols × strategies). Overrides MAX_POSITION_DOLLARS entirely.
    # FRACTIONAL_SHARES=true required to trade below one-share price (e.g. $100 / 9 slots).
    total_capital: float = float(_get("TOTAL_CAPITAL", "0"))
    fractional_shares: bool = _bool("FRACTIONAL_SHARES", False)

    logs_dir: Path = Path(__file__).parent.parent / "logs"


cfg = Config()

_VALID_STRATEGIES = {"bb_kdj", "bb_kdj_loose", "orb", "vwap_pb", "vwap", "gap_fade"}


def validate_config() -> list[str]:
    """Return a list of error strings. Empty list = config is sane.

    Call at paper runner startup. Any CRITICAL error should abort the process.
    Warnings are logged but do not block startup.
    """
    errors: list[str] = []

    # Safety invariants — these are always fatal
    if cfg.trd_env != "SIMULATE":
        errors.append(f"CRITICAL: TRD_ENV={cfg.trd_env!r} — must be SIMULATE")
    if cfg.live_trading_enabled:
        errors.append("CRITICAL: LIVE_TRADING_ENABLED=true — paper runner refuses to run")

    # Strategy / symbol config
    if not cfg.symbols:
        errors.append("SYMBOLS is empty — nothing to trade")
    if not cfg.active_strategies:
        errors.append("STRATEGIES is empty — no strategies active")
    for s in cfg.active_strategies:
        if s not in _VALID_STRATEGIES:
            errors.append(f"Unknown strategy {s!r} in STRATEGIES — valid: {sorted(_VALID_STRATEGIES)}")

    # Numeric sanity
    if cfg.min_signal_score < 0 or cfg.min_signal_score > 3:
        errors.append(f"MIN_SIGNAL_SCORE={cfg.min_signal_score} must be 0–3")
    if cfg.atr_stop_mult <= 0:
        errors.append(f"ATR_STOP_MULT={cfg.atr_stop_mult} must be > 0")
    if cfg.kdj_window_bars < 0:
        errors.append(f"KDJ_WINDOW_BARS={cfg.kdj_window_bars} must be >= 0")
    if cfg.total_capital < 0:
        errors.append(f"TOTAL_CAPITAL={cfg.total_capital} must be >= 0")
    if cfg.total_capital == 0 and cfg.max_position_dollars <= 0:
        errors.append("MAX_POSITION_DOLLARS must be > 0 when TOTAL_CAPITAL is not set")
    if cfg.max_trades_per_day < 0:
        errors.append(f"MAX_TRADES_PER_DAY={cfg.max_trades_per_day} must be >= 0 (0 = unlimited)")
    if cfg.max_daily_loss <= 0:
        errors.append(f"MAX_DAILY_LOSS={cfg.max_daily_loss} must be > 0")

    # VWAP PB symbol whitelist sanity
    for s in cfg.vwap_pb_symbols:
        if s not in cfg.symbols:
            errors.append(f"VWAP_PB_SYMBOLS contains {s!r} which is not in SYMBOLS")

    # Override format sanity — catch "US.IWM:300,US.SPY" (missing value on SPY)
    for raw in _get("SYMBOL_SIZE_OVERRIDES", "").split(","):
        raw = raw.strip()
        if raw and ":" not in raw:
            errors.append(f"SYMBOL_SIZE_OVERRIDES entry {raw!r} missing colon — expected 'SYMBOL:DOLLARS'")
    for raw in _get("ORB_MINUTES_OVERRIDES", "").split(","):
        raw = raw.strip()
        if raw and ":" not in raw:
            errors.append(f"ORB_MINUTES_OVERRIDES entry {raw!r} missing colon — expected 'SYMBOL:MINUTES'")
    for raw in _get("KDJ_WINDOW_OVERRIDES", "").split(","):
        raw = raw.strip()
        if raw and ":" not in raw:
            errors.append(f"KDJ_WINDOW_OVERRIDES entry {raw!r} missing colon — expected 'SYMBOL:BARS'")
    for raw in _get("ORB_TARGET_MULT_OVERRIDES", "").split(","):
        raw = raw.strip()
        if raw and ":" not in raw:
            errors.append(f"ORB_TARGET_MULT_OVERRIDES entry {raw!r} missing colon — expected 'SYMBOL:MULT'")
    for raw in _get("ORB_VOL_MULT_OVERRIDES", "").split(","):
        raw = raw.strip()
        if raw and ":" not in raw:
            errors.append(f"ORB_VOL_MULT_OVERRIDES entry {raw!r} missing colon — expected 'SYMBOL:MULT'")

    return errors

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
    max_daily_loss: float = float(_get("MAX_DAILY_LOSS", "5"))
    max_position_dollars: float = float(_get("MAX_POSITION_DOLLARS", "50"))
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
    # SPY breaks at any window>0 — exclude SPY from BB+KDJ or keep at w=0.
    kdj_window_bars: int = int(_get("KDJ_WINDOW_BARS", "0"))

    discord_webhook_url: str = _get("DISCORD_WEBHOOK_URL", "")

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

    # VWAP strategy parameters
    vwap_band_mult: float = float(_get("VWAP_BAND_MULT", "0.5"))
    vwap_stop_mult: float = float(_get("VWAP_STOP_MULT", "0.75"))

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
    orb_vol_mult: float = float(_get("ORB_VOL_MULT", "1.2"))
    orb_min_range_pct: float = float(_get("ORB_MIN_RANGE_PCT", "0.001"))
    orb_max_range_pct: float = float(_get("ORB_MAX_RANGE_PCT", "0.008"))

    logs_dir: Path = Path(__file__).parent.parent / "logs"


cfg = Config()

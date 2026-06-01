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

    logs_dir: Path = Path(__file__).parent.parent / "logs"


cfg = Config()

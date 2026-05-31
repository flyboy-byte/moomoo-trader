from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from moomoo import RET_OK, KLType, AuType, KL_FIELD

from .config import cfg
from .connection import quote_context
from .logger import get_logger

log = get_logger("data")

_KTYPE_MAP = {
    "K_1M": KLType.K_1M,
    "K_3M": KLType.K_3M,
    "K_5M": KLType.K_5M,
    "K_15M": KLType.K_15M,
    "K_30M": KLType.K_30M,
    "K_60M": KLType.K_60M,
    "K_DAY": KLType.K_DAY,
}


def fetch_candles(
    symbol: str | None = None,
    ktype: str | None = None,
    start: str | None = None,
    end: str | None = None,
    max_count: int = 1000,
) -> pd.DataFrame:
    symbol = symbol or cfg.symbol
    ktype_str = ktype or cfg.candle_ktype
    ktype_val = _KTYPE_MAP.get(ktype_str, KLType.K_5M)

    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")
    if start is None:
        start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    log.info("Fetching %s %s candles from %s to %s", symbol, ktype_str, start, end)

    frames: list[pd.DataFrame] = []
    page_key = None

    with quote_context() as ctx:
        while True:
            ret, data, page_key = ctx.request_history_kline(
                code=symbol,
                start=start,
                end=end,
                ktype=ktype_val,
                autype=AuType.QFQ,
                fields=[KL_FIELD.ALL],
                max_count=max_count,
                page_req_key=page_key,
            )
            if ret != RET_OK:
                log.error("request_history_kline error: %s", data)
                break

            frames.append(data)
            log.debug("Fetched %d rows (page_key=%s)", len(data), page_key)

            if page_key is None:
                break

    if not frames:
        log.warning("No candle data returned for %s", symbol)
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df["time_key"] = pd.to_datetime(df["time_key"])
    df = df.sort_values("time_key").reset_index(drop=True)
    log.info("Fetched %d candles for %s", len(df), symbol)
    return df


def save_candles(df: pd.DataFrame, symbol: str, ktype: str) -> Path:
    cfg.logs_dir.mkdir(exist_ok=True)
    safe_symbol = symbol.replace(".", "_")
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = cfg.logs_dir / f"{safe_symbol}_{ktype}_{date_str}.csv"
    df.to_csv(path, index=False)
    log.info("Saved %d rows to %s", len(df), path)
    return path


def fetch_and_save(
    symbol: str | None = None,
    ktype: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> Path | None:
    symbol = symbol or cfg.symbol
    ktype = ktype or cfg.candle_ktype
    df = fetch_candles(symbol=symbol, ktype=ktype, start=start, end=end)
    if df.empty:
        return None
    return save_candles(df, symbol, ktype)

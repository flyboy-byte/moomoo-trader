import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from moomoo import RET_OK, KLType, AuType, KL_FIELD

from . import clock
from . import config as _config
from .connection import quote_context
from .logger import get_logger

log = get_logger("data")

class FetchError(RuntimeError):
    """An API error during a strict (all-or-nothing) candle fetch."""


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
    extended_time: bool = False,
    strict: bool = False,
    before_request=None,
) -> pd.DataFrame:
    """Fetch QFQ candles, following pagination.

    strict=True raises FetchError on any API error instead of returning whatever
    pages arrived so far — a bulk fetch must never save a silently truncated
    history. before_request, if given, is called before every page request
    (rate limiting).
    """
    cfg = _config.cfg
    symbol = symbol or cfg.symbol
    ktype_str = ktype or cfg.candle_ktype
    ktype_val = _KTYPE_MAP.get(ktype_str, KLType.K_5M)

    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")
    if start is None:
        start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    log.info("Fetching %s %s candles from %s to %s (extended_time=%s)",
              symbol, ktype_str, start, end, extended_time)

    frames: list[pd.DataFrame] = []
    page_key = None

    with quote_context() as ctx:
        while True:
            if before_request is not None:
                before_request()
            ret, data, page_key = ctx.request_history_kline(
                code=symbol,
                start=start,
                end=end,
                ktype=ktype_val,
                autype=AuType.QFQ,
                fields=[KL_FIELD.ALL],
                max_count=max_count,
                page_req_key=page_key,
                extended_time=extended_time,
            )
            if ret != RET_OK:
                log.error("request_history_kline error: %s", data)
                if strict:
                    raise FetchError(f"{symbol}: {data}")
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


def save_candles(df: pd.DataFrame, symbol: str, ktype: str, extended_time: bool = False) -> Path:
    cfg = _config.cfg
    cfg.logs_dir.mkdir(exist_ok=True)
    safe_symbol = symbol.replace(".", "_")
    date_str = datetime.now().strftime("%Y-%m-%d")
    suffix = "_EXT" if extended_time else ""
    path = cfg.logs_dir / f"{safe_symbol}_{ktype}{suffix}_{date_str}.csv"
    df.to_csv(path, index=False)
    log.info("Saved %d rows to %s", len(df), path)
    return path


# QFQ (forward-adjusted) prices are expressed relative to the latest price, so every
# dividend or split re-scales all earlier bars. A pull made after such an event returns
# different numbers for bars already in the archive. Merging it naively splices two
# price bases into one file (found 2026-09-17, PLAN.md Step 7: SPY had a 25.8 bps seam
# at 2026-06-16 and IWM a 23.7 bps seam at 2026-06-11). Instead the archive is moved
# onto the new basis, with a backup, whenever the overlap shows a clean constant ratio.
_BASIS_TOL = 0.5e-4        # 0.5 bps: larger ratio drift than this is an adjustment event
_BASIS_MIN_REF_BARS = 20   # need this many overlapping bars on one day to trust a ratio
_PRICE_COLS = ("open", "high", "low", "close")


class ArchiveBasisError(RuntimeError):
    """New pull and archive disagree in a way that cannot be rebased safely."""


def _rebase_factor(df_old: pd.DataFrame, df_new: pd.DataFrame) -> float | None:
    """Return old→new price factor from the earliest overlapping day, or None.

    None means "no rebase needed or possible": the overlap is too small to trust
    (legacy keep-last merge applies). Raises ArchiveBasisError if the reference
    day's ratios are not constant, i.e. something other than an adjustment.
    """
    ov = df_old[["time_key", "close"]].merge(
        df_new[["time_key", "close"]], on="time_key", suffixes=("_old", "_new"))
    ov = ov[(ov["close_old"] > 0) & (ov["close_new"] > 0)]
    if ov.empty:
        old_end, new_start = df_old["time_key"].max(), df_new["time_key"].min()
        # Adjustments take effect between sessions, so a same-day continuation is safe.
        if old_end < new_start and old_end.date() != new_start.date():
            raise ArchiveBasisError(
                "new pull does not overlap the archive — cannot check the price basis")
        return None
    first_day = ov["time_key"].dt.date.min()
    ref = ov[ov["time_key"].dt.date == first_day]
    if len(ref) < _BASIS_MIN_REF_BARS:
        return None
    ratios = ref["close_new"] / ref["close_old"]
    r = float(ratios.median())
    if float((ratios / r - 1).abs().max()) > _BASIS_TOL:
        raise ArchiveBasisError(
            f"overlap ratios on {first_day} are not constant "
            f"({ratios.min():.6f}..{ratios.max():.6f}) — not a clean adjustment")
    return None if abs(r - 1) <= _BASIS_TOL else r


def update_combined_csv(
    df_new: pd.DataFrame,
    symbol: str,
    ktype: str,
    extended_time: bool = False,
) -> Path:
    """Merge df_new into a running, non-date-stamped combined archive CSV,
    deduping on time_key (keep="last" — Moomoo may revise a bar after a
    provisional fetch). Creates the file if it doesn't exist yet."""
    cfg = _config.cfg
    cfg.logs_dir.mkdir(exist_ok=True)
    safe_symbol = symbol.replace(".", "_")
    suffix = "_EXT" if extended_time else ""
    path = cfg.logs_dir / f"{safe_symbol}_{ktype}{suffix}_combined.csv"

    df_new = df_new.copy()
    df_new["time_key"] = pd.to_datetime(df_new["time_key"])

    if path.exists():
        try:
            df_old = pd.read_csv(path)
            df_old["time_key"] = pd.to_datetime(df_old["time_key"])
        except Exception as e:
            # A crash mid-write (VPS restart, OOM) can leave this file truncated/corrupt.
            # Bug fix 2026-08-25 (found by external audit): this used to log and silently
            # rebuild `combined = df_new`, which replaces the ENTIRE multi-year never-pruned
            # archive with whatever's in the current small fetch, then commits that
            # truncated version atomically and irreversibly — the archive corruption bug
            # documented in docs/strategy_graveyard.md. Quarantine the unreadable file
            # instead and fail loudly so a human looks at it once, rather than erasing
            # years of history automatically. Caller (scripts/fetch_daily_archive.py)
            # already catches per-symbol so one corrupt archive doesn't block the rest.
            quarantine = path.with_name(
                f"{path.stem}.corrupt-{clock.now().strftime('%Y%m%dT%H%M%S')}{path.suffix}"
            )
            os.replace(path, quarantine)
            log.error(
                "Existing archive %s unreadable (%s) — quarantined to %s, NOT rebuilt "
                "(refusing to silently wipe history); investigate and restore/discard manually",
                path, e, quarantine,
            )
            raise

        try:
            factor = _rebase_factor(df_old, df_new)
        except ArchiveBasisError:
            # Leave the archive untouched; keep the pull for a human to look at.
            sidecar = path.with_name(
                f"{path.stem}.basis-mismatch-{clock.now().strftime('%Y%m%dT%H%M%S')}{path.suffix}"
            )
            df_new.to_csv(sidecar, index=False)
            log.error("Price basis check failed for %s — archive NOT merged; new pull saved "
                      "to %s", path, sidecar)
            raise
        if factor is not None:
            backup = path.with_name(
                f"{path.stem}.pre-rebase-{clock.now().strftime('%Y%m%dT%H%M%S')}{path.suffix}"
            )
            shutil.copy2(path, backup)
            before = df_old["time_key"] < df_new["time_key"].min()
            for col in _PRICE_COLS:
                if col in df_old.columns:
                    df_old.loc[before, col] = df_old.loc[before, col] * factor
            log.warning("Price basis changed for %s (adjustment event): rebased %d earlier "
                        "rows by x%.6f; backup at %s", path, int(before.sum()), factor, backup)
        combined = pd.concat([df_old, df_new], ignore_index=True)
    else:
        combined = df_new

    combined = combined.drop_duplicates(subset=["time_key"], keep="last")
    combined = combined.sort_values("time_key").reset_index(drop=True)

    # Atomic write: a crash mid-write to the real path would corrupt it for every
    # future read. Write to a temp file in the same directory, then os.replace()
    # (atomic on POSIX) so the destination is always either the old version or the
    # complete new one, never a partial write.
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    combined.to_csv(tmp_path, index=False)
    os.replace(tmp_path, path)
    log.info("Updated %s: %d total rows", path, len(combined))
    return path


def fetch_and_save(
    symbol: str | None = None,
    ktype: str | None = None,
    start: str | None = None,
    end: str | None = None,
    extended_time: bool = False,
) -> Path | None:
    cfg = _config.cfg
    symbol = symbol or cfg.symbol
    ktype = ktype or cfg.candle_ktype
    df = fetch_candles(symbol=symbol, ktype=ktype, start=start, end=end, extended_time=extended_time)
    if df.empty:
        return None
    return save_candles(df, symbol, ktype, extended_time=extended_time)

#!/usr/bin/env python3
"""Start the paper-trading loop (single or multi-symbol).

Usage:
    python scripts/run_paper.py                        # uses SYMBOLS from .env
    python scripts/run_paper.py --symbol US.QQQ        # single symbol override
    python scripts/run_paper.py --symbols US.SPY,US.IWM  # explicit multi-symbol

Kill switch: create STOP_TRADING.txt in the project root to pause immediately.
Remove the file to resume. Ctrl-C to exit cleanly.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.config import cfg
from mm.health import run_health_check
from mm.paper import run, run_multi

_SYMBOL_RE = re.compile(r'^[A-Z]{1,2}\.[A-Z0-9]+$')


def _validate_symbols(symbols: list[str]) -> None:
    for sym in symbols:
        if not _SYMBOL_RE.match(sym):
            print(f"ERROR: Invalid symbol format '{sym}' — expected e.g. US.SPY, US.IWM")
            sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run paper-trading loop")
    parser.add_argument("--symbol", default=None, help="Single symbol override")
    parser.add_argument("--symbols", default=None,
                        help="Comma-separated symbols (e.g. US.SPY,US.QQQ,US.IWM)")
    args = parser.parse_args()

    if args.symbol:
        _validate_symbols([args.symbol])
    elif args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        _validate_symbols(symbols)

    if not run_health_check():
        print("OpenD health check failed — aborting")
        sys.exit(1)

    if args.symbol:
        run(symbol=args.symbol)
    elif args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        run_multi(symbols=symbols)
    elif len(cfg.symbols) > 1:
        run_multi()
    else:
        run(symbol=cfg.symbols[0])


if __name__ == "__main__":
    main()

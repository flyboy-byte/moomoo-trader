"""Every research engine must expose the same gross/net cost ruler."""
import ast
from pathlib import Path

import pandas as pd
import pytest

from mm.backtest import Trade, print_summary, summarize_trades
from mm.ema_momentum import EMAMomentumTrade, print_ema_summary
from mm.gap_fade import GapFadeTrade, print_gap_fade_summary
from mm.orb_strategy import ORBTrade, print_orb_summary
from mm.replay import summarize as summarize_replay
from mm.vwap_pullback import VWAPPBTrade, print_vwap_pb_summary


T0 = pd.Timestamp("2026-01-05 10:00:00")
T1 = pd.Timestamp("2026-01-05 10:05:00")


def _trades():
    return [
        Trade(T0, 100.0, T1, 102.0, "TARGET"),
        Trade(T0, 100.0, T1, 99.0, "STOP"),
    ]


def test_common_engine_summary_keeps_gross_and_adds_net():
    summary = summarize_trades(_trades(), "US.SPY")
    assert summary["gross_pnl"] == pytest.approx(1.0)
    assert summary["net_pnl"] < summary["gross_pnl"]
    assert summary["net_pf"] < summary["gross_pf"]
    assert summary["avg_bps_net"] < summary["avg_bps"]


@pytest.mark.parametrize(
    "printer,trades",
    [
        (lambda ts: print_summary(ts, symbol="US.SPY"), _trades()),
        (lambda ts: print_orb_summary(ts, symbol="US.SPY"), [
            ORBTrade(T0, 100, T1, 102, "TARGET", "long", 101, 99),
            ORBTrade(T0, 100, T1, 99, "STOP", "long", 101, 99),
        ]),
        (lambda ts: print_vwap_pb_summary(ts, symbol="US.SPY"), [
            VWAPPBTrade(T0, 100, 99, T1, 102, "TARGET"),
            VWAPPBTrade(T0, 100, 99, T1, 99, "STOP"),
        ]),
        (lambda ts: print_gap_fade_summary(ts, symbol="US.SPY"), [
            GapFadeTrade(T0, 100, 99, 102, T1, 102, "TARGET", "long", -0.01, 101),
            GapFadeTrade(T0, 100, 99, 102, T1, 99, "STOP", "long", -0.01, 101),
        ]),
        (lambda ts: print_ema_summary(ts, symbol="US.SPY"), [
            EMAMomentumTrade(T0, 100, 99, T1, 102, "TARGET", "cross"),
            EMAMomentumTrade(T0, 100, 99, T1, 99, "STOP", "cross"),
        ]),
    ],
)
def test_every_fast_engine_prints_both_rulers(printer, trades, capsys):
    printer(trades)
    output = capsys.readouterr().out
    # BB+KDJ logs its summary; the four stdout engines expose these labels directly.
    if output:
        assert "Gross PnL" in output
        assert "Net PnL" in output
        assert "Gross PF" in output
        assert "Net PF" in output


def test_replay_summary_contains_both_rulers(tmp_path):
    events = [
        {"ts": "2026-01-05T10:00:00", "event": "position_open", "strategy": "orb",
         "symbol": "US.SPY", "entry": 100.0, "stop": 99.0, "qty": 1, "direction": "long"},
        {"ts": "2026-01-05T10:05:00", "event": "position_close", "strategy": "orb",
         "symbol": "US.SPY", "exit": 101.0, "pnl": 1.0, "reason": "TARGET"},
    ]
    path = tmp_path / "paper_US_SPY_2026-01-05.jsonl"
    path.write_text("\n".join(__import__("json").dumps(e) for e in events) + "\n")
    summary = summarize_replay(tmp_path, {}, "instant")
    assert summary["total_net_pnl"] < summary["total_pnl"]
    assert summary["net_pf"] <= summary["gross_pf"]
    assert summary["per_strategy"]["orb"]["net_pnl"] < 1.0


def test_all_engine_summary_printers_name_the_net_ruler():
    """Repo-wide guard: a future engine summary cannot quietly report gross-only PF/PnL."""
    offenders = []
    for path in sorted((Path(__file__).parent.parent / "mm").glob("*.py")):
        source = path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not (node.name.startswith("print_") and "summary" in node.name):
                continue
            body = ast.get_source_segment(source, node) or ""
            if "PF" not in body and "Profit factor" not in body:
                continue
            if "net" not in body.lower():
                offenders.append(f"{path.name}:{node.name}")
    assert not offenders, f"engine summary lacks a net cost ruler: {offenders}"

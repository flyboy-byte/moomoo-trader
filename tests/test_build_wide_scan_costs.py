import csv
from pathlib import Path

import pytest

from mm.wide_scan_cost_table import WIDE_SCAN_ROUND_TRIP_BPS
from scripts.build_wide_scan_costs import estimate_round_trip_bps

ROOT = Path(__file__).parent.parent


def test_universe_has_exact_frozen_slot_allocation_and_no_duplicates():
    with (ROOT / "docs/wide_scan_universe.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    primary_etfs = [row for row in rows if row["status"] == "primary" and row["asset_class"] == "etf"]
    primary_stocks = [
        row for row in rows if row["status"] == "primary" and row["asset_class"] == "stock"
    ]
    reserves = [row for row in rows if row["status"] == "reserve"]

    assert len(rows) == 97
    assert len(primary_etfs) == 60
    assert len(primary_stocks) == 25
    assert len(reserves) == 12
    assert len({row["symbol"] for row in rows}) == 97
    assert [int(row["slot"]) for row in rows] == list(range(1, 98))


def test_cost_heuristic_is_monotonic_and_rounds_against_the_strategy():
    liquid = estimate_round_trip_bps(median_price=500.0, median_dollar_volume=20_000_000_000)
    cheaper_stock = estimate_round_trip_bps(median_price=50.0, median_dollar_volume=20_000_000_000)
    less_liquid = estimate_round_trip_bps(median_price=500.0, median_dollar_volume=100_000_000)

    assert liquid["round_trip_bps"] >= liquid["raw_bps"]
    assert cheaper_stock["round_trip_bps"] > liquid["round_trip_bps"]
    assert less_liquid["round_trip_bps"] > liquid["round_trip_bps"]
    assert liquid["round_trip_bps"] % 0.5 == pytest.approx(0.0)


def test_cost_heuristic_has_visible_pessimistic_bounds():
    very_liquid = estimate_round_trip_bps(1_000.0, 100_000_000_000)
    very_illiquid = estimate_round_trip_bps(5.0, 1_000_000)
    assert very_liquid["round_trip_bps"] == 1.5
    assert very_illiquid["round_trip_bps"] == 12.0


def test_runtime_table_exactly_matches_audited_inputs_and_all_symbols_pass_screen():
    with (ROOT / "docs/wide_scan_cost_inputs.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    audited = {row["symbol"]: float(row["round_trip_bps"]) for row in rows}
    assert all(row["screen_pass"] == "True" for row in rows)
    assert WIDE_SCAN_ROUND_TRIP_BPS == audited

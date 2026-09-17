from scripts.compare_engine_results import compare, replay_metrics, summarize_one_share


def _trade(symbol="US.SPY", strategy="orb", pnl=2.0, qty=2, entry=100.0):
    return {
        "closed": True,
        "symbol": symbol,
        "strategy": strategy,
        "pnl": pnl,
        "qty": qty,
        "entry": entry,
    }


def test_replay_summary_normalizes_quantity_before_costs():
    # SPY costs 1.5 bps: $1 gross per share - $0.015 cost = $0.985 net.
    result = summarize_one_share([_trade()])

    assert result["trades"] == 1
    assert result["gross_pnl"] == 1.0
    assert result["net_pnl"] == 0.985
    assert result["avg_bps"] == 100.0
    assert result["avg_bps_net"] == 98.5


def test_replay_metrics_splits_symbol_and_strategy():
    result = replay_metrics([
        _trade("US.SPY", "orb"),
        _trade("US.QQQ", "orb"),
        _trade("US.SPY", "vwap_pb"),
    ])

    assert result["aggregate"]["orb"]["trades"] == 2
    assert result["aggregate"]["vwap_pb"]["trades"] == 1
    assert result["per_symbol"]["US.SPY"]["orb"]["trades"] == 1
    assert result["per_symbol"]["US.QQQ"]["orb"]["trades"] == 1


def test_compare_applies_both_preregistered_gates():
    fast = {"aggregate": {
        "orb": {"trades": 100, "net_pf": 1.20},
        "vwap_pb": {"trades": 50, "net_pf": 1.30},
    }}
    replay = {"aggregate": {
        "orb": {"trades": 98, "net_pf": 1.25},
        "vwap_pb": {"trades": 48, "net_pf": 1.31},
    }}

    result = compare(fast, replay, ["orb", "vwap_pb"])

    assert result["strategies"]["orb"]["pass"]
    assert not result["strategies"]["vwap_pb"]["trade_count_pass"]
    assert result["strategies"]["vwap_pb"]["net_pf_pass"]
    assert not result["pass"]

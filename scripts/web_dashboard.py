#!/usr/bin/env python3
"""Flask web dashboard — reads today's JSONL and serves at :8080.

Usage:
    python scripts/web_dashboard.py
    python scripts/web_dashboard.py --port 8080
    python scripts/web_dashboard.py --date 2026-06-01   # review past session
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask
from mm.config import cfg
from eod_summary import SessionSummary, load_summary

app = Flask(__name__)
_session_date: date = date.today()


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _load_recent_evals(n: int = 20) -> list[dict]:
    date_str = _session_date.strftime("%Y-%m-%d")
    evals: list[dict] = []
    for f in sorted(cfg.logs_dir.glob(f"paper_US_*_{date_str}.jsonl")):
        sym = f.stem.removeprefix("paper_").removesuffix(f"_{date_str}").replace("_", ".", 1)
        for line in f.read_text().splitlines():
            try:
                e = json.loads(line)
                if e.get("event") == "bar_eval" and e.get("strategy") == "bb_kdj":
                    e.setdefault("symbol", sym)
                    evals.append(e)
            except json.JSONDecodeError:
                pass
    return evals[-n:]


def _load_latest_evals_by_symbol() -> dict[str, dict[str, dict]]:
    """Return {symbol: {strategy: latest bar_eval}} for today's session."""
    date_str = _session_date.strftime("%Y-%m-%d")
    result: dict[str, dict[str, dict]] = {}
    for f in sorted(cfg.logs_dir.glob(f"paper_US_*_{date_str}.jsonl")):
        sym = f.stem.removeprefix("paper_").removesuffix(f"_{date_str}").replace("_", ".", 1)
        result.setdefault(sym, {})
        for line in f.read_text().splitlines():
            try:
                e = json.loads(line)
                if e.get("event") == "bar_eval":
                    strat = e.get("strategy", "?")
                    e.setdefault("symbol", sym)
                    result[sym][strat] = e
            except json.JSONDecodeError:
                pass
    return result


def _load_recent_skips(n: int = 12) -> list[dict]:
    """Return last N signal_skip events across all symbol files."""
    date_str = _session_date.strftime("%Y-%m-%d")
    skips: list[dict] = []
    for f in sorted(cfg.logs_dir.glob(f"paper_US_*_{date_str}.jsonl")):
        sym = f.stem.removeprefix("paper_").removesuffix(f"_{date_str}").replace("_", ".", 1)
        for line in f.read_text().splitlines():
            try:
                e = json.loads(line)
                if e.get("event") == "signal_skip":
                    e.setdefault("symbol", sym)
                    skips.append(e)
            except json.JSONDecodeError:
                pass
    skips.sort(key=lambda x: x.get("ts", ""))
    return skips[-n:]


def _runner_status(last_eval: dict | None) -> tuple[str, str]:
    """Return (label, css-color) based on last bar_eval age."""
    if not last_eval:
        return "NO DATA", "#888"
    try:
        last_ts = datetime.fromisoformat(last_eval["ts"])
        age = datetime.now() - last_ts
        secs = int(age.total_seconds())
        if secs < 180:
            return f"ALIVE  ({secs}s ago)", "#4caf50"
        if secs < 600:
            return f"STALE  ({secs // 60}m ago)", "#ff9800"
        return f"DEAD  ({secs // 60}m ago)", "#f44336"
    except (KeyError, ValueError):
        return "UNKNOWN", "#888"


def _signal_dot(val: bool) -> str:
    return '<span style="color:#4caf50">●</span>' if val else '<span style="color:#444">○</span>'


def _pnl_color(v: float) -> str:
    return "#4caf50" if v >= 0 else "#f44336"


def _fmt_pnl(v: float) -> str:
    return f"+${v:.2f}" if v >= 0 else f"-${abs(v):.2f}"


def _bb_kdj_status(sig: dict, bonus: int) -> str:
    bb = sig.get("bb_touch", False)
    kdj = sig.get("kdj_cross", False)
    bb_lower = sig.get("bb_lower", 0.0)
    bb_middle = sig.get("bb_middle", 0.0)
    close = sig.get("close", 0.0)
    min_bonus = cfg.min_signal_score
    if bb and kdj and bonus >= min_bonus:
        return '<span style="color:#4caf50;font-weight:bold">READY ▲</span>'
    if bb and not kdj:
        return '<span style="color:#ffeb3b">BB ✓ · need KDJ</span>'
    if kdj and not bb:
        if bb_lower and close:
            pct = (close - bb_lower) / close * 100
            return f'<span style="color:#888">KDJ ✓ · BB {pct:+.2f}%</span>'
        return '<span style="color:#888">KDJ ✓ · wait BB</span>'
    # neither — show distance to BB lower
    if bb_lower and close:
        pct = (close - bb_lower) / close * 100
        color = "#ffeb3b" if pct < 0.10 else "#555"
        return f'<span style="color:{color}">BB {pct:+.2f}% away</span>'
    return '<span style="color:#555">watching</span>'


def _orb_status(sig: dict, close: float) -> str:
    if not sig.get("or_valid"):
        return '<span style="color:#555">no OR yet</span>'
    or_high = sig.get("or_high", 0.0)
    or_low = sig.get("or_low", 0.0)
    if close > or_high:
        return '<span style="color:#4caf50;font-weight:bold">LONG READY ▲</span>'
    if or_low and close < or_low:
        return '<span style="color:#ff5252;font-weight:bold">SHORT READY ▼</span>'
    if or_high:
        pct_to_high = (or_high - close) / close * 100
        pct_to_low = (close - or_low) / close * 100 if or_low else 0
        return f'<span style="color:#555">inside · +{pct_to_high:.2f}% to H · -{pct_to_low:.2f}% to L</span>'
    return '<span style="color:#555">inside range</span>'


def _vwap_status(sig: dict) -> str:
    crosses = sig.get("cross_count", 0)
    above = sig.get("close_above_vwap", False)
    wick = sig.get("wick_below", False)
    max_crosses = cfg.vwap_pb_max_crosses
    if crosses > max_crosses:
        return f'<span style="color:#555">choppy ({crosses} crosses > {max_crosses})</span>'
    if wick and above:
        return '<span style="color:#4caf50;font-weight:bold">READY ▲</span>'
    if wick and not above:
        return '<span style="color:#888">wick ✓ · close below VWAP</span>'
    return '<span style="color:#555">watching</span>'


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def _render_market_conditions(
    latest: dict[str, dict[str, dict]],
    skips: list[dict],
) -> str:
    if not latest and not skips:
        return ""

    # --- BB+KDJ section ---
    bb_rows = ""
    for sym in sorted(latest):
        e = latest[sym].get("bb_kdj")
        if not e:
            continue
        sig = e.get("signals", {})
        sig["close"] = e.get("close", 0.0)
        close = e.get("close", 0.0)
        bb_lower = sig.get("bb_lower", 0.0)
        bb_middle = sig.get("bb_middle", 0.0)
        bonus = e.get("bonus_score", 0)
        ranging = sig.get("ranging", False)
        regime_col = "#4caf50" if ranging else "#ff9800"
        regime_txt = "RANGING" if ranging else "TRENDING"
        bar_time = e.get("ts", "")[:16].replace("T", " ")[11:]
        bb_rows += f"""<tr>
          <td><b>{sym.replace("US.", "")}</b></td>
          <td style="color:#666">{bar_time}</td>
          <td>${close:.3f}</td>
          <td style="color:#888">${bb_lower:.3f}</td>
          <td style="color:#888">${bb_middle:.3f}</td>
          <td style="color:{regime_col};font-size:11px;letter-spacing:.5px">{regime_txt}</td>
          <td>{_signal_dot(sig.get("bb_touch", False))}</td>
          <td>{_signal_dot(sig.get("kdj_cross", False))}</td>
          <td>{_signal_dot(sig.get("rsi_oversold", False))}</td>
          <td>{_signal_dot(ranging)}</td>
          <td>{_signal_dot(sig.get("volume_spike", False))}</td>
          <td style="color:#666;font-size:11px">{bonus}/{cfg.min_signal_score}</td>
          <td>{_bb_kdj_status(sig, bonus)}</td>
        </tr>"""

    # --- ORB section ---
    orb_rows = ""
    for sym in sorted(latest):
        e = latest[sym].get("orb")
        if not e:
            continue
        sig = e.get("signals", {})
        close = e.get("close", 0.0)
        or_valid = sig.get("or_valid", False)
        or_high = sig.get("or_high", 0.0)
        or_low = sig.get("or_low", 0.0)
        bar_time = e.get("ts", "")[:16].replace("T", " ")[11:]
        or_valid_html = '<span style="color:#4caf50">✓</span>' if or_valid else '<span style="color:#444">—</span>'
        or_high_str = f"${or_high:.3f}" if or_high else "—"
        or_low_str = f"${or_low:.3f}" if or_low else "—"
        orb_rows += f"""<tr>
          <td><b>{sym.replace("US.", "")}</b></td>
          <td style="color:#666">{bar_time}</td>
          <td>${close:.3f}</td>
          <td style="color:#888">{or_high_str}</td>
          <td style="color:#888">{or_low_str}</td>
          <td>{or_valid_html}</td>
          <td>{_orb_status(sig, close)}</td>
        </tr>"""

    # --- VWAP PB section ---
    vwap_rows = ""
    for sym in sorted(latest):
        e = latest[sym].get("vwap_pb")
        if not e:
            continue
        sig = e.get("signals", {})
        close = e.get("close", 0.0)
        crosses = sig.get("cross_count", 0)
        above = sig.get("close_above_vwap", False)
        wick = sig.get("wick_below", False)
        bar_time = e.get("ts", "")[:16].replace("T", " ")[11:]
        cross_col = "#f44336" if crosses > cfg.vwap_pb_max_crosses else "#4caf50"
        vwap_rows += f"""<tr>
          <td><b>{sym.replace("US.", "")}</b></td>
          <td style="color:#666">{bar_time}</td>
          <td>${close:.3f}</td>
          <td style="color:{cross_col}">{crosses}</td>
          <td>{_signal_dot(above)}</td>
          <td>{_signal_dot(wick)}</td>
          <td>{_vwap_status(sig)}</td>
        </tr>"""

    # --- Skip reasons ---
    skip_rows = ""
    for e in reversed(skips):
        ts = e.get("ts", "")[:16].replace("T", " ")[11:]
        sym = e.get("symbol", "?").replace("US.", "")
        strat = e.get("strategy", "?")
        reason = e.get("reason", "?")
        score = e.get("score", 0)
        min_s = e.get("min_score", "?")
        r_col = "#f44336" if "block" in reason or "risk" in reason else "#888"
        skip_rows += f"""<tr>
          <td style="color:#666">{ts}</td>
          <td><b>{sym}</b></td>
          <td style="color:#555;font-size:11px">{strat}</td>
          <td style="color:{r_col}">{reason}</td>
          <td style="color:#555;font-size:11px">{score}/{min_s}</td>
        </tr>"""

    section_label = '<div style="font-size:11px;color:#555;letter-spacing:1px;margin:12px 0 6px">'
    divider = '<div style="border-top:1px solid #222;margin:10px 0"></div>'

    bb_section = f"""
        {section_label}BB+KDJ</div>
        <table>
          <tr class="th">
            <th>Symbol</th><th>Bar</th><th>Price</th>
            <th title="Bollinger lower band">BB Low</th>
            <th title="Bollinger middle band">BB Mid</th>
            <th>Regime</th>
            <th title="Price ≤ BB lower">BB</th>
            <th title="KDJ golden cross">KDJ</th>
            <th title="RSI < 35">RSI</th>
            <th title="ADX < 25">RNG</th>
            <th title="Volume spike 1.5×">VOL</th>
            <th>Bonus</th><th>Status</th>
          </tr>
          {bb_rows}
        </table>""" if bb_rows else ""

    orb_section = f"""
        {divider}
        {section_label}ORB</div>
        <table>
          <tr class="th">
            <th>Symbol</th><th>Bar</th><th>Price</th>
            <th>OR High</th><th>OR Low</th>
            <th title="Opening range built">OR</th>
            <th>Status</th>
          </tr>
          {orb_rows}
        </table>""" if orb_rows else ""

    vwap_section = f"""
        {divider}
        {section_label}VWAP PULLBACK</div>
        <table>
          <tr class="th">
            <th>Symbol</th><th>Bar</th><th>Price</th>
            <th title="VWAP crosses today">Crosses</th>
            <th title="Close above VWAP">Above</th>
            <th title="Wick below VWAP">Wick</th>
            <th>Status</th>
          </tr>
          {vwap_rows}
        </table>""" if vwap_rows else ""

    skips_section = f"""
        {divider}
        {section_label}RECENT SKIPS</div>
        <table>
          <tr class="th">
            <th>Time</th><th>Symbol</th><th>Strategy</th><th>Reason</th><th>Score/Min</th>
          </tr>
          {skip_rows}
        </table>""" if skip_rows else ""

    return f"""
    <div class="card">
      <div class="card-title">MARKET CONDITIONS</div>
      {bb_section}{orb_section}{vwap_section}{skips_section}
    </div>"""


def _render(summary: SessionSummary, evals: list[dict], market_cond_html: str = "") -> str:
    last_eval = evals[-1] if evals else None
    status_label, status_color = _runner_status(last_eval)
    now_str = datetime.now().strftime("%H:%M:%S")
    date_str = _session_date.strftime("%Y-%m-%d (%A)")

    last_close = f"${last_eval['close']:.3f}" if last_eval else "—"
    last_score = str(last_eval.get("signal_score", "—")) if last_eval else "—"

    ct = summary.closed_trades
    pnl = summary.realized_pnl
    pnl_str = _fmt_pnl(pnl)
    pnl_col = _pnl_color(pnl)

    # Open position block
    open_html = ""
    if summary.open_at_close:
        tr = summary.open_at_close[0]
        unrealized = ""
        if last_eval:
            unreal = (last_eval["close"] - tr.entry_price) * tr.qty
            unrealized = f'<span style="color:{_pnl_color(unreal)}">{_fmt_pnl(unreal)} unrealized</span>'
        open_html = f"""
        <div class="card open-pos">
          <div class="card-title">OPEN POSITION</div>
          <table><tr>
            <td>Symbol</td><td><b>{tr.symbol}</b></td>
            <td>Entry</td><td>${tr.entry_price:.3f}</td>
            <td>Stop</td><td>${tr.stop_price:.3f}</td>
            <td>Qty</td><td>{tr.qty}</td>
            <td>Last</td><td>{last_close}</td>
            <td>P&L</td><td>{unrealized}</td>
          </tr></table>
        </div>"""

    # Trades table
    trades_html = ""
    if ct:
        rows = ""
        for tr in ct:
            et = tr.entry_time[11:16] if tr.entry_time else "?"
            xt = tr.exit_time[11:16] if tr.exit_time else "?"
            icon = "✓" if "TARGET" in tr.exit_reason.upper() or tr.exit_reason == "target" else "✗"
            col = _pnl_color(tr.pnl)
            rows += f"""<tr>
              <td>{tr.symbol}</td><td>{et}</td><td>{xt}</td>
              <td>${tr.entry_price:.3f}</td><td>${tr.exit_price:.3f}</td>
              <td style="color:{col}"><b>{_fmt_pnl(tr.pnl)}</b></td>
              <td>{icon} {tr.exit_reason}</td><td>{tr.hold_minutes}m</td>
            </tr>"""
        trades_html = f"""
        <div class="card">
          <div class="card-title">TRADES</div>
          <table>
            <tr class="th"><th>Symbol</th><th>Entry</th><th>Exit</th>
            <th>Entry$</th><th>Exit$</th><th>P&L</th><th>Reason</th><th>Hold</th></tr>
            {rows}
          </table>
        </div>"""

    # Signal feed
    sig_rows = ""
    for e in reversed(evals):
        sig = e.get("signals", {})
        t = e.get("ts", "")[:19].replace("T", " ")
        entry_flag = "▲" if (sig.get("bb_touch") and sig.get("kdj_cross")) else ""
        sig_rows += f"""<tr>
          <td>{t[11:]}</td>
          <td>${e.get('close', 0):.3f}</td>
          <td>{_signal_dot(sig.get('bb_touch', False))}</td>
          <td>{_signal_dot(sig.get('kdj_cross', False))}</td>
          <td>{_signal_dot(sig.get('rsi_oversold', False))}</td>
          <td>{_signal_dot(sig.get('ranging', False))}</td>
          <td>{_signal_dot(sig.get('volume_spike', False))}</td>
          <td>{e.get('bonus_score', 0)}</td>
          <td style="color:#4caf50"><b>{entry_flag}</b></td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="30">
  <title>moomoo-trader</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: monospace; background: #111; color: #ddd; padding: 16px; font-size: 14px; }}
    h1 {{ font-size: 18px; margin-bottom: 12px; color: #fff; }}
    .status-bar {{ display: flex; gap: 24px; align-items: center; margin-bottom: 16px;
                   background: #1a1a1a; padding: 10px 14px; border-radius: 6px; }}
    .runner-status {{ font-size: 15px; font-weight: bold; color: {status_color}; }}
    .meta {{ color: #888; font-size: 12px; }}
    .card {{ background: #1a1a1a; border-radius: 6px; padding: 12px 14px; margin-bottom: 14px; }}
    .card-title {{ font-size: 11px; color: #666; letter-spacing: 1px; margin-bottom: 8px; }}
    .open-pos {{ border-left: 3px solid #ff9800; }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }}
    .stat {{ background: #222; border-radius: 4px; padding: 10px 12px; }}
    .stat-label {{ font-size: 11px; color: #666; margin-bottom: 4px; }}
    .stat-value {{ font-size: 20px; font-weight: bold; }}
    table {{ width: 100%; border-collapse: collapse; }}
    td, th {{ padding: 5px 8px; text-align: left; border-bottom: 1px solid #222; }}
    .th th {{ color: #666; font-size: 11px; letter-spacing: 0.5px; }}
    tr:last-child td {{ border-bottom: none; }}
  </style>
</head>
<body>
  <h1>moomoo-trader</h1>

  <div class="status-bar">
    <span class="runner-status">{status_label}</span>
    <span class="meta">date: {date_str}</span>
    <span class="meta">mode: {cfg.strategy_mode}</span>
    <span class="meta">symbol: {', '.join(cfg.symbols)}</span>
    <span class="meta">last price: {last_close}  score: {last_score}</span>
    <span class="meta" style="margin-left:auto">updated {now_str} · refreshes every 30s</span>
  </div>

  <div class="card">
    <div class="card-title">TODAY</div>
    <div class="summary-grid">
      <div class="stat"><div class="stat-label">P&L</div>
        <div class="stat-value" style="color:{pnl_col}">{pnl_str}</div></div>
      <div class="stat"><div class="stat-label">TRADES</div>
        <div class="stat-value">{len(ct)}</div></div>
      <div class="stat"><div class="stat-label">WINS</div>
        <div class="stat-value" style="color:#4caf50">{summary.wins}</div></div>
      <div class="stat"><div class="stat-label">LOSSES</div>
        <div class="stat-value" style="color:#f44336">{summary.losses}</div></div>
      <div class="stat"><div class="stat-label">BARS EVAL</div>
        <div class="stat-value">{summary.bar_evals}</div></div>
      <div class="stat"><div class="stat-label">TARGETS</div>
        <div class="stat-value">{summary.targets}</div></div>
      <div class="stat"><div class="stat-label">STOPS</div>
        <div class="stat-value">{summary.stops}</div></div>
    </div>
  </div>

  {open_html}
  {trades_html}
  {market_cond_html}

  <div class="card">
    <div class="card-title">SIGNAL FEED (last 20 bars · bb_kdj only)</div>
    <table>
      <tr class="th">
        <th>Time</th><th>Close</th>
        <th title="BB touch">BB</th>
        <th title="KDJ cross">KDJ</th>
        <th title="RSI oversold">RSI</th>
        <th title="ADX ranging">RNG</th>
        <th title="Volume spike">VOL</th>
        <th>Score</th><th>Entry</th>
      </tr>
      {sig_rows}
    </table>
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@app.route("/")
def index() -> str:
    summary = load_summary(_session_date)
    evals = _load_recent_evals()
    latest = _load_latest_evals_by_symbol()
    skips = _load_recent_skips()
    market_cond_html = _render_market_conditions(latest, skips)
    return _render(summary, evals, market_cond_html)


# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="moomoo-trader web dashboard")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--date", help="Session date YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    global _session_date
    if args.date:
        _session_date = date.fromisoformat(args.date)

    print(f"Dashboard running at http://0.0.0.0:{args.port}")
    print(f"Session date: {_session_date}")
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()

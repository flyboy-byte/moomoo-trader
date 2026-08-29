#!/usr/bin/env python3
"""Flask web dashboard — reads today's JSONL and serves at :8080.

Usage:
    python scripts/web_dashboard.py
    python scripts/web_dashboard.py --port 8080
    python scripts/web_dashboard.py --date 2026-06-01   # review past session
"""
import argparse
import base64
import hmac
import io
import json
import re
import secrets
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import psutil
import pyotp
import qrcode
from flask import Flask, Response, abort, jsonify, redirect, render_template, request, session, url_for
from markupsafe import Markup, escape
from mm import clock, costs, stats
from mm.config import cfg
# Canonical trade reconstruction + cost model. Before 2026-08-29 this file paired
# trades itself, applied no cost model, and labelled the resulting gross figure
# "net_pnl" — so the dashboard showed +$12.92 / PF 1.189 for a portfolio that
# analyze_trades.py scored at net −$0.57 / PF 0.992. See mm/trades.py's docstring.
from mm.trades import load_trades, profit_factor
from eod_summary import SessionSummary, load_summary

_PROJECT_ROOT = Path(__file__).parent.parent
_SCRIPTS_DIR = Path(__file__).parent
_ENV_PATH = _PROJECT_ROOT / ".env"

app = Flask(__name__,
            static_folder=str(_SCRIPTS_DIR / "static"),
            template_folder=str(_SCRIPTS_DIR / "templates"))
# Random per-process secret: sessions reset on restart (deploys), which is fine.
# Never derive this from the password — the derivation scheme is public in this
# repo, so a deterministic key would turn any captured session cookie into
# offline brute-force material against the password.
app.secret_key = secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True  # only sent over HTTPS — nginx terminates TLS
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)
_date_override: date | None = None

# In-memory login rate limit.
# Lockout duration escalates with repeated offenses: 5 fails → 15 min, 10 → 1 h, 15+ → 24 h.
_LOGIN_FAIL_TIERS: list[tuple[int, int]] = [(15, 86400), (10, 3600), (5, 900)]
# Tracks all fail timestamps per IP (never pruned beyond the longest window).
_login_fails: dict[str, list[float]] = {}

import logging as _logging
_auth_log = _logging.getLogger("dashboard.auth")


@app.context_processor
def _inject_template_globals():
    return {"csrf_token": _csrf_token, "cfg": cfg}


def _client_ip() -> str:
    # X-Real-IP is set by nginx from $remote_addr (trusted upstream).
    # Never read X-Forwarded-For — clients can spoof it to bypass rate limiting.
    return request.headers.get("X-Real-IP", request.remote_addr or "?")


def _login_blocked(ip: str) -> tuple[bool, int]:
    """Return (blocked, retry_after_seconds). Prunes stale timestamps."""
    now = time.time()
    longest_window = _LOGIN_FAIL_TIERS[0][1]  # 24 h — max window to keep
    fails = [t for t in _login_fails.get(ip, []) if now - t < longest_window]
    _login_fails[ip] = fails
    for threshold, window_s in _LOGIN_FAIL_TIERS:
        recent = sum(1 for t in fails if now - t < window_s)
        if recent >= threshold:
            oldest_in_window = min(t for t in fails if now - t < window_s)
            retry_after = int(oldest_in_window + window_s - now) + 1
            return True, retry_after
    return False, 0

def _csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def _check_csrf() -> None:
    token = request.form.get("_csrf_token", "")
    expected = session.get("csrf_token", "")
    if not expected or not hmac.compare_digest(token, expected):
        abort(403)


# ---------------------------------------------------------------------------
# Auth + config editor support
# ---------------------------------------------------------------------------

# Keys the config editor is allowed to read and write.
_EDITABLE_KEYS = {
    # Risk / sizing
    "MAX_DAILY_LOSS", "MAX_POSITION_DOLLARS", "MAX_TRADES_PER_DAY",
    "MAX_TRADES_PER_STRATEGY", "MIN_SIGNAL_SCORE", "ATR_STOP_MULT", "TOTAL_CAPITAL",
    "FRACTIONAL_SHARES",
    # Strategy / symbol lists
    "STRATEGIES", "SYMBOLS", "SYMBOL_SIZE_OVERRIDES",
    "KDJ_WINDOW_BARS", "KDJ_WINDOW_OVERRIDES",
    "VWAP_PB_SYMBOLS", "VWAP_PB_MAX_CROSSES", "VWAP_PB_STOP_MULT",
    # ORB
    "ORB_MINUTES", "ORB_MINUTES_OVERRIDES", "ORB_VOL_MULT", "ORB_VOL_MULT_OVERRIDES",
    "ORB_TARGET_MULT", "ORB_TARGET_MULT_OVERRIDES", "ORB_SHORTS_ENABLED", "ORB_SHORT_SYMBOLS",
    "ORB_VIX_MAX_OVERRIDES", "ORB_ENTRY_MIN_CONFIDENCE", "ORB_SETUP_SCORER_ENABLED",
    # Regime gate (AI)
    "REGIME_GATE_ENABLED", "REGIME_GATE_STRATEGIES", "REGIME_SKIP_LABELS",
    # Gap fade
    "GAP_VIX_MAX_OVERRIDES", "GAP_MAX_SHORT_PCT", "GAP_LARGE_SHORT_FILTER_ENABLED",
    "GAP_PREMARKET_FILTER_ENABLED",
    # Misc flags
    "EXIT_ON_KDJ_DEATH",
}


def _auth_configured() -> bool:
    return bool(cfg.totp_secret or cfg.dashboard_password)


def _require_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _auth_configured():
            return f(*args, **kwargs)
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        session.permanent = True
        return f(*args, **kwargs)
    return decorated


def _read_env() -> dict[str, str]:
    """Parse .env into ordered dict (only editable keys)."""
    result: dict[str, str] = {}
    if not _ENV_PATH.exists():
        return result
    for line in _ENV_PATH.read_text().splitlines():
        m = re.match(r"^\s*([A-Z_]+)\s*=\s*(.*)", line)
        if m and m.group(1) in _EDITABLE_KEYS:
            result[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return result


def _write_env_key(key: str, value: str) -> bool:
    """Update a single key in .env, preserving all other lines.

    Rejects values containing newlines/carriage returns — otherwise a value
    like "100\\nTRD_ENV=REAL" would inject a second, arbitrary KEY=VALUE line
    into .env outside the _EDITABLE_KEYS allowlist. Returns False (no write)
    if the value is rejected.
    """
    if key not in _EDITABLE_KEYS:
        return False
    if "\n" in value or "\r" in value:
        return False
    text = _ENV_PATH.read_text() if _ENV_PATH.exists() else ""
    lines = text.splitlines()
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    updated = False
    new_lines = []
    for line in lines:
        if pattern.match(line):
            new_lines.append(f"{key}={value}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{key}={value}")
    _ENV_PATH.write_text("\n".join(new_lines) + "\n")
    return True


def _kill_switch_state() -> dict[str, bool]:
    return {
        "STOP_TRADING": (_PROJECT_ROOT / "STOP_TRADING.txt").exists(),
        "STOP_SHORTS": (_PROJECT_ROOT / "STOP_SHORTS.txt").exists(),
    }




@app.route("/login", methods=["GET", "POST"])
def login() -> Response | str:
    if not _auth_configured():
        return redirect(url_for("index"))
    use_totp = bool(cfg.totp_secret)
    error = ""
    if request.method == "POST":
        _check_csrf()
        ip = _client_ip()
        blocked, retry_after = _login_blocked(ip)
        if blocked:
            mins = (retry_after + 59) // 60
            error = f"Too many attempts. Try again in {mins} minute{'s' if mins != 1 else ''}."
            _auth_log.warning("login blocked ip=%s retry_after=%ds", ip, retry_after)
        else:
            ok = False
            if use_totp:
                code = request.form.get("code", "").strip().replace(" ", "")
                ok = pyotp.TOTP(cfg.totp_secret).verify(code, valid_window=1)
                # Password fallback during TOTP bootstrap (when both are configured)
                if not ok and cfg.dashboard_password:
                    ok = hmac.compare_digest(request.form.get("code", ""), cfg.dashboard_password)
            else:
                ok = hmac.compare_digest(request.form.get("password", ""), cfg.dashboard_password)
            if ok:
                session["logged_in"] = True
                session.permanent = True
                _login_fails.pop(ip, None)
                _auth_log.info("login success ip=%s", ip)
                nxt = request.args.get("next", "")
                if not nxt.startswith("/") or nxt.startswith("//"):
                    nxt = url_for("index")
                return redirect(nxt)
            else:
                _login_fails.setdefault(ip, []).append(time.time())
                _auth_log.warning("login failed ip=%s total_fails=%d", ip, len(_login_fails[ip]))
                error = "Invalid code." if use_totp else "Wrong password."
    return render_template("login.html", error=error, use_totp=use_totp)


@app.route("/totp-setup")
@_require_login
def totp_setup() -> Response | str:
    """Shows QR code to scan into Authenticator. Only useful on first setup."""
    if not cfg.totp_secret:
        return "TOTP_SECRET not set in .env", 404
    totp = pyotp.TOTP(cfg.totp_secret)
    uri = totp.provisioning_uri(name="moomoo-trader", issuer_name="trading.flyboybyte.com")
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    return render_template("totp_setup.html", qr_b64=qr_b64, secret=cfg.totp_secret)


@app.route("/logout")
def logout() -> Response:
    session.clear()
    return redirect(url_for("index"))


@app.route("/api/stats")
def api_stats() -> Response:
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    cores = psutil.cpu_percent(percpu=True)
    load = psutil.getloadavg()
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
        try:
            raw_name = p.info["name"] or ""
            # For Python processes, show the script name instead of "python"
            if raw_name.lower().startswith("python"):
                try:
                    cmdline = p.cmdline()
                    # Find first non-interpreter argument (the script or -m module)
                    script = next(
                        (a for a in cmdline[1:] if not a.startswith("-")), None
                    )
                    if script:
                        import os
                        script_base = os.path.basename(script).replace(".py", "")
                        display_name = f"py:{script_base}"
                    else:
                        display_name = raw_name
                except (psutil.AccessDenied, psutil.ZombieProcess):
                    display_name = raw_name
            else:
                display_name = raw_name
            procs.append({
                "pid": p.info["pid"],
                "name": display_name[:24],
                "cpu": round(p.info["cpu_percent"] or 0, 1),
                "mem": round(p.info["memory_percent"] or 0, 1),
                "status": (p.info["status"] or "")[:1].upper(),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    procs.sort(key=lambda x: x["cpu"], reverse=True)
    return jsonify({
        "cores": [round(c, 1) for c in cores],
        "load": [round(x, 2) for x in load],
        "mem_used_gb": round(vm.used / 1e9, 2),
        "mem_total_gb": round(vm.total / 1e9, 2),
        "mem_pct": round(vm.percent, 1),
        "disk_used_gb": round(disk.used / 1e9, 2),
        "disk_total_gb": round(disk.total / 1e9, 2),
        "disk_pct": round(disk.percent, 1),
        "net_sent_mb": round(net.bytes_sent / 1e6, 1),
        "net_recv_mb": round(net.bytes_recv / 1e6, 1),
        "procs": procs[:12],
    })


def _net_of(t) -> float:
    """Net PnL for one eod_summary.TradeRecord, via the canonical cost model."""
    return costs.net_pnl(t.pnl, t.symbol, t.entry_price, t.qty or 1)


def _pf_json(values: list[float]) -> float | None:
    """Canonical PF, JSON-safe. inf is not valid JSON — send null and let the UI
    render it as ∞ rather than silently emitting NaN."""
    if not values:
        return None
    pf = profit_factor(values)
    return None if pf == float("inf") else round(pf, 3)


@app.route("/api/scoreboard")
def api_scoreboard() -> Response:
    """Per-strategy scorecard from all historical JSONL logs, gross AND net of costs.

    Accepts optional ?start=YYYY-MM-DD to limit the date range.

    Both views are returned deliberately. The whole finding of docs/research-reset.md
    Goal A is that the difference between them was the entire reported profit, so
    showing only one would hide the result — showing net alone hides how much of the
    edge the costs ate; showing gross alone is the bug this endpoint used to have.
    """
    start_str = request.args.get("start")
    trades = [t for t in load_trades(cfg.logs_dir, start=start_str) if t["closed"]]

    per: dict[str, list[dict]] = {}
    for t in trades:
        per.setdefault(t["strategy"] or "unknown", []).append(t)

    result = []
    for strat, ts in per.items():
        gross = [t["pnl"] for t in ts if t["pnl"] is not None]
        net = [t["pnl_net"] for t in ts if t["pnl_net"] is not None]
        bps_net = [t["bps_net"] for t in ts if t["bps_net"] is not None]
        wins = sum(1 for t in ts if t["pnl"] is not None and t["pnl"] > 0)
        last = max((t["close_ts"] or "" for t in ts), default="")

        # Bootstrap CI on the net PF. A strategy whose interval contains 1.0 is
        # consistent with zero edge no matter how good the point estimate looks —
        # the dashboard should say so rather than let a PF of 1.04 read as a result.
        lo, hi = stats.bootstrap_pf_ci(net) if len(net) >= 2 else (float("nan"),) * 2
        inconclusive = not (lo != lo) and lo <= 1.0 <= hi

        result.append({
            "strategy": strat,
            "trades": len(ts),
            "wins": wins,
            "win_pct": round(wins / len(ts) * 100, 1) if ts else 0.0,
            "gross_pnl": round(sum(gross), 4) if gross else 0.0,
            "net_pnl": round(sum(net), 4) if net else 0.0,
            "gross_pf": _pf_json(gross),
            "net_pf": _pf_json(net),
            "avg_bps_net": round(sum(bps_net) / len(bps_net), 1) if bps_net else None,
            "ci_lo": None if lo != lo else round(lo, 3),
            "ci_hi": None if hi != hi or hi == float("inf") else round(hi, 3),
            "inconclusive": inconclusive,
            "last_trade": last[:10] if last else "",
        })
    result.sort(key=lambda x: x["net_pnl"], reverse=True)
    return jsonify(result)


@app.route("/api/pnl_history")

def api_pnl_history() -> Response:
    """Cumulative P&L per strategy over time, from JSONL position_close events.

    Returns {strategy: [{date, pnl, cumulative, pnl_net, cumulative_net}]} by date.
    Accepts optional ?start=YYYY-MM-DD to limit date range.

    Carries both curves so the equity chart can show the cost drag as the gap
    between them — the single clearest picture of the Goal A finding.
    """
    start_str = request.args.get("start")
    by_strat: dict[str, list[dict]] = {}

    for t in load_trades(cfg.logs_dir, start=start_str):
        if not t["closed"] or t["pnl"] is None:
            continue
        by_strat.setdefault(t["strategy"] or "unknown", []).append(t)

    result: dict[str, list[dict]] = {}
    for strat, ts in by_strat.items():
        ts.sort(key=lambda t: t["close_ts"] or "")
        cum = cum_net = 0.0
        series = []
        for t in ts:
            pnl = t["pnl"]
            pnl_net = t["pnl_net"] if t["pnl_net"] is not None else pnl
            cum = round(cum + pnl, 4)
            cum_net = round(cum_net + pnl_net, 4)
            series.append({
                "date": (t["close_ts"] or "")[:10],
                "pnl": round(pnl, 4),
                "cumulative": cum,
                "pnl_net": round(pnl_net, 4),
                "cumulative_net": cum_net,
            })
        result[strat] = series

    return jsonify(result)


@app.route("/api/trades")

def api_trades() -> Response:
    """Recent closed trades from JSONL logs, paired with their entry data.

    Returns a list of trade dicts, newest first. Accepts:
      ?start=YYYY-MM-DD  — only include trades on or after this date
      ?limit=N           — max rows (default 200)
    """
    start_str = request.args.get("start")
    try:
        limit = int(request.args.get("limit", 200))
    except ValueError:
        limit = 200

    # Uses the canonical pairing (mm/trades.py) rather than a second, uncosted
    # implementation local to this file — which is what lived here until 2026-08-29
    # and is why the dashboard and analyze_trades.py disagreed about the same trades.
    closed = [t for t in load_trades(cfg.logs_dir, start=start_str) if t["closed"]]
    closed.sort(key=lambda t: t["close_ts"] or "", reverse=True)

    trades = [{
        "ts": t["close_ts"],
        "date": (t["close_ts"] or "")[:10],
        "symbol": t["symbol"],
        "strategy": t["strategy"],
        "direction": t["direction"],
        "entry": t["entry"],
        "exit": t["exit"],
        "qty": t["qty"],
        "pnl": t["pnl"],
        "pnl_net": t["pnl_net"],
        "bps": round(t["bps"], 1) if t["bps"] is not None else None,
        "bps_net": round(t["bps_net"], 1) if t["bps_net"] is not None else None,
        "hold_bars": t["hold_bars"] or 0,
        "reason": t["reason"] or "",
    } for t in closed[:limit]]

    return jsonify(trades)


@app.route("/api/today_summary")

def api_today_summary() -> Response:
    """Live today stats: P&L, win%, PF, regime, VIX. Polled by the dashboard JS every 30s."""
    summary = load_summary(_session_date())
    ct = summary.closed_trades
    # Canonical PF (mm/backtest.py) — this was one of three inline reimplementations
    # in this file, all using a `<= 0` loss convention that happened to match but was
    # never guarded. See docs/strategy_graveyard.md "Reimplemented-Metric Drift".
    pf = _pf_json([t.pnl for t in ct])
    net_pnls = [_net_of(t) for t in ct]
    net_pf = _pf_json(net_pnls)
    win_pct = round(summary.wins / len(ct) * 100, 1) if ct else 0.0

    regime = _load_regime_today()
    vix = _load_vix_latest()
    regime_label = regime.get("regime", "")
    skip_lbls = list(getattr(cfg, "regime_skip_labels", None) or [])
    regime_blocked = bool(getattr(cfg, "regime_gate_enabled", False) and regime_label in skip_lbls)

    return jsonify({
        "pnl": summary.realized_pnl,
        "pnl_net": round(sum(net_pnls), 4) if net_pnls else 0.0,
        "trades": len(ct),
        "wins": summary.wins,
        "losses": summary.losses,
        "win_pct": win_pct,
        "pf": pf,
        "net_pf": net_pf,
        "targets": summary.targets,
        "stops": summary.stops,
        "bar_evals": summary.bar_evals,
        "regime": regime_label,
        "regime_confidence": regime.get("confidence"),
        "regime_blocked": regime_blocked,
        "vix": vix,
    })


@app.route("/api/regime_history")

def api_regime_history() -> Response:
    """Per-day regime label + bb_kdj P&L. Used by the AI Gate panel."""
    start_str = request.args.get("start", "2024-01-01")
    regime_by_date: dict[str, dict] = {}
    for f in cfg.logs_dir.glob("regime_*.json"):
        try:
            date_str = f.stem.split("_", 1)[1]
            if date_str < start_str:
                continue
            d = json.loads(f.read_text())
            regime_by_date[date_str] = {"label": d.get("regime", ""), "confidence": d.get("confidence")}
        except Exception:
            continue

    pnl_by_date: dict[str, dict] = {}
    for f in sorted(cfg.logs_dir.glob("paper_US_*_????-??-??.jsonl")):
        date_part = f.stem.rsplit("_", 1)[-1]
        if date_part < start_str:
            continue
        try:
            for line in f.read_text().splitlines():
                if not line:
                    continue
                ev = json.loads(line)
                if ev.get("event") != "position_close":
                    continue
                if ev.get("strategy") not in ("bb_kdj", "bb_kdj_loose"):
                    continue
                pnl = float(ev.get("pnl", 0))
                s = pnl_by_date.setdefault(date_part, {"pnl": 0.0, "trades": 0, "gross_win": 0.0, "gross_loss": 0.0})
                s["pnl"] = round(s["pnl"] + pnl, 4)
                s["trades"] += 1
                if pnl > 0:
                    s["gross_win"] = round(s["gross_win"] + pnl, 4)
                else:
                    s["gross_loss"] = round(s["gross_loss"] - pnl, 4)
        except Exception:
            continue

    skip_lbls = list(getattr(cfg, "regime_skip_labels", None) or [])
    regime_enabled = bool(getattr(cfg, "regime_gate_enabled", False))
    all_dates = sorted(set(list(regime_by_date) + list(pnl_by_date)))

    history = []
    for d in all_dates:
        r = regime_by_date.get(d, {})
        p = pnl_by_date.get(d, {})
        label = r.get("label", "")
        blocked = regime_enabled and label in skip_lbls
        history.append({
            "date": d,
            "label": label,
            "confidence": r.get("confidence"),
            "blocked": blocked,
            "trades": p.get("trades", 0),
            "pnl": p.get("pnl", 0.0),
            "gross_win": p.get("gross_win", 0.0),
            "gross_loss": p.get("gross_loss", 0.0),
        })

    return jsonify({"history": history, "skip_labels": skip_lbls})


@app.route("/api/orb_scorer_history")

def api_orb_scorer_history() -> Response:
    """ORB scorer confidence scores from signal_skip(orb_claude_score) events."""
    start_str = request.args.get("start", "")
    setups: list[dict] = []

    for f in sorted(cfg.logs_dir.glob("paper_US_*_????-??-??.jsonl")):
        date_part = f.stem.rsplit("_", 1)[-1]
        if start_str and date_part < start_str:
            continue
        try:
            for line in f.read_text().splitlines():
                if not line:
                    continue
                ev = json.loads(line)
                if ev.get("event") != "signal_skip":
                    continue
                if ev.get("reason") != "orb_claude_score":
                    continue
                conf = ev.get("confidence") or ev.get("score")
                if conf is not None:
                    setups.append({"date": date_part, "confidence": float(conf)})
        except Exception:
            continue

    avg = round(sum(s["confidence"] for s in setups) / len(setups), 3) if setups else None
    threshold = getattr(cfg, "orb_entry_min_confidence", None)
    above = sum(1 for s in setups if s["confidence"] >= (threshold or 0.5)) if setups else 0

    return jsonify({
        "setups": setups[-200:],
        "avg_confidence": avg,
        "threshold": threshold,
        "above_threshold": above,
    })


@app.route("/market_conditions_frag")

def market_conditions_frag() -> str:
    """HTML fragment for the market conditions card, polled by JS every 30s."""
    latest = _load_latest_evals_by_symbol()
    skips = _load_recent_skips()
    gap_status = _load_gap_fade_status()
    date_str = _session_date().strftime("%Y-%m-%d")
    bar_time_label = date_str
    return render_template("partials/market_conditions.html",
                           latest=latest, skips=skips, gap_status=gap_status,
                           bar_time_label=bar_time_label)


_CFG_BOOL_KEYS = {
    "REGIME_GATE_ENABLED", "ORB_SETUP_SCORER_ENABLED",
    "FRACTIONAL_SHARES", "ORB_SHORTS_ENABLED", "EXIT_ON_KDJ_DEATH",
    "GAP_LARGE_SHORT_FILTER_ENABLED", "GAP_PREMARKET_FILTER_ENABLED",
}
_CFG_MULTISELECT_KEYS = {
    "STRATEGIES", "SYMBOLS", "VWAP_PB_SYMBOLS", "ORB_SHORT_SYMBOLS",
    "REGIME_GATE_STRATEGIES", "REGIME_SKIP_LABELS",
}
_CFG_NUMERIC_KEYS = {
    "MAX_DAILY_LOSS", "MAX_POSITION_DOLLARS", "MAX_TRADES_PER_DAY",
    "MAX_TRADES_PER_STRATEGY", "MIN_SIGNAL_SCORE", "ATR_STOP_MULT",
    "KDJ_WINDOW_BARS", "ORB_MINUTES", "ORB_VOL_MULT", "ORB_TARGET_MULT",
    "ORB_ENTRY_MIN_CONFIDENCE", "GAP_MAX_SHORT_PCT",
    "VWAP_PB_MAX_CROSSES", "VWAP_PB_STOP_MULT", "TOTAL_CAPITAL",
}


@app.route("/config", methods=["GET", "POST"])
@_require_login
def config_editor() -> Response | str:
    msg = ""
    msg_type = "ok"

    if request.method == "POST":
        _check_csrf()
        action = request.form.get("action", "")

        if action == "toggle_stop_trading":
            p = _PROJECT_ROOT / "STOP_TRADING.txt"
            if p.exists():
                p.unlink()
                msg = "STOP_TRADING.txt removed — trading resumed."
            else:
                p.write_text("stop\n")
                msg = "STOP_TRADING.txt created — trading paused."

        elif action == "toggle_stop_shorts":
            p = _PROJECT_ROOT / "STOP_SHORTS.txt"
            if p.exists():
                p.unlink()
                msg = "STOP_SHORTS.txt removed — shorts re-enabled."
            else:
                p.write_text("stop\n")
                msg = "STOP_SHORTS.txt created — ORB shorts disabled."

        elif action == "restart_runner":
            try:
                result = subprocess.run(
                    ["systemctl", "--user", "restart", "moomoo-paper"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    msg = "moomoo-paper.service restarted."
                else:
                    msg = f"Restart failed: {escape(result.stderr.strip())}"
                    msg_type = "err"
            except Exception as e:
                msg = f"Restart error: {escape(str(e))}"
                msg_type = "err"

        elif action == "save_config":
            changed = []
            rejected = []
            existing = _read_env()
            for key in _CFG_BOOL_KEYS:
                val = "true" if request.form.get(key) else "false"
                if val == existing.get(key):
                    continue
                if _write_env_key(key, val):
                    changed.append(key)
                else:
                    rejected.append(key)
            for key in _CFG_MULTISELECT_KEYS:
                val = ",".join(request.form.getlist(key))
                if val == existing.get(key, ""):
                    continue
                if _write_env_key(key, val):
                    changed.append(key)
                else:
                    rejected.append(key)
            for key in _CFG_NUMERIC_KEYS:
                if key not in request.form:
                    continue
                val = request.form[key].strip()
                if val == existing.get(key, ""):
                    continue
                if _write_env_key(key, val):
                    changed.append(key)
                else:
                    rejected.append(key)
            if rejected:
                msg = f"Rejected (invalid value): {', '.join(sorted(rejected))}."
                msg_type = "err"
            elif changed:
                msg = f"Saved: {', '.join(sorted(changed))}. Restart runner to apply."
            else:
                msg = "No changes submitted."

    current = _read_env()
    kills = _kill_switch_state()

    # Fill in live cfg defaults for keys absent from .env so UI reflects reality
    _cfg_defaults: dict[str, str] = {
        "STRATEGIES":             ",".join(cfg.active_strategies),
        "SYMBOLS":                ",".join(cfg.symbols),
        "VWAP_PB_SYMBOLS":        ",".join(cfg.vwap_pb_symbols),
        "ORB_SHORT_SYMBOLS":      ",".join(cfg.orb_short_symbols),
        "REGIME_GATE_STRATEGIES": ",".join(cfg.regime_gate_strategies),
        "REGIME_SKIP_LABELS":     ",".join(cfg.regime_skip_labels),
        # Only ORB_SHORTS_ENABLED has a non-False default; include it so the toggle
        # shows ON when the key is absent from .env (matching live cfg behaviour).
        "ORB_SHORTS_ENABLED":     "true" if cfg.orb_shorts_enabled else "false",
    }
    for k, v in _cfg_defaults.items():
        if k not in current:
            current[k] = v

    def _is_true(key: str) -> bool:
        return current.get(key, "false").lower() in ("true", "1", "yes")

    def _csv_set(key: str) -> set[str]:
        return {v.strip() for v in current.get(key, "").split(",") if v.strip()}

    return render_template("config.html",
        msg=msg, msg_type=msg_type, kills=kills,
        current=current, is_true=_is_true, csv_set=_csv_set,
    )



def _load_regime_today() -> dict:
    try:
        f = cfg.logs_dir / f"regime_{_session_date().strftime('%Y-%m-%d')}.json"
        return json.loads(f.read_text()) if f.exists() else {}
    except Exception:
        return {}


def _load_vix_latest() -> float | None:
    try:
        f = cfg.logs_dir / "vix_daily.jsonl"
        lines = [l for l in f.read_text().splitlines() if l]
        return json.loads(lines[-1]).get("vix_prev_close") if lines else None
    except Exception:
        return None


def _load_gap_fade_status() -> dict[str, dict]:
    date_str = _session_date().strftime("%Y-%m-%d")
    result: dict[str, dict] = {}
    for f in sorted(cfg.logs_dir.glob(f"paper_US_*_{date_str}.jsonl")):
        sym = f.stem.removeprefix("paper_").removesuffix(f"_{date_str}").replace("_", ".", 1)
        rec: dict = {"status": "watching", "direction": None, "pnl": None,
                     "reason": None, "entry": None, "stop": None, "close": None}
        has_gap_fade_data = False
        for line in f.read_text().splitlines():
            try:
                ev = json.loads(line)
                if ev.get("strategy") != "gap_fade":
                    continue
                has_gap_fade_data = True
                event = ev.get("event")
                if event == "bar_eval":
                    rec["close"] = ev.get("close")
                elif event == "position_open":
                    rec["status"] = "in_trade"
                    rec["direction"] = ev.get("direction")
                    rec["entry"] = ev.get("entry")
                    rec["stop"] = ev.get("stop")
                elif event == "position_close":
                    rec["status"] = "done"
                    rec["reason"] = ev.get("reason")
                    rec["pnl"] = ev.get("pnl")
                elif event == "signal_skip" and rec["status"] == "watching":
                    rec["status"] = "skipped"
                    rec["reason"] = ev.get("reason")
            except json.JSONDecodeError:
                pass
        if has_gap_fade_data:
            result[sym] = rec
    return result


def _session_date() -> date:
    """Return the session date — ?date= param → --date override → today."""
    if _date_override is not None:
        return _date_override
    try:
        d_str = request.args.get("date")
        if d_str:
            return date.fromisoformat(d_str)
    except RuntimeError:
        pass  # no Flask request context (e.g. called outside a request)
    except ValueError:
        pass  # malformed ?date= — bug fix 2026-06-18: this used to 500 the
              # request instead of falling back to today
    return clock.today()  # ET trading-day date, not local system date


def _available_dates() -> list[date]:
    """Sorted descending list of dates that have at least one JSONL log file."""
    dates: set[date] = set()
    for f in cfg.logs_dir.glob("paper_US_*_*.jsonl"):
        parts = f.stem.rsplit("_", 1)
        if len(parts) == 2:
            try:
                dates.add(date.fromisoformat(parts[1]))
            except ValueError:
                pass
    return sorted(dates, reverse=True)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _load_recent_evals(n: int = 20) -> list[dict]:
    date_str = _session_date().strftime("%Y-%m-%d")
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
    date_str = _session_date().strftime("%Y-%m-%d")
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
    date_str = _session_date().strftime("%Y-%m-%d")
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
        age = clock.now_et() - last_ts
        secs = int(age.total_seconds())
        if secs < 180:
            return f"ALIVE  ({secs}s ago)", "#4caf50"
        if secs < 600:
            return f"STALE  ({secs // 60}m ago)", "#ff9800"
        return f"DEAD  ({secs // 60}m ago)", "#f44336"
    except (KeyError, ValueError):
        return "UNKNOWN", "#888"


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@app.route("/")

def index() -> str:
    avail = _available_dates()
    sess_date = _session_date()
    is_today = sess_date == clock.today()
    summary = load_summary(sess_date)
    evals = _load_recent_evals()
    latest = _load_latest_evals_by_symbol()
    skips = _load_recent_skips()
    regime = _load_regime_today()
    vix = _load_vix_latest()
    gap_status = _load_gap_fade_status()

    # Runner status
    last_eval = evals[-1] if evals else None
    status_label, status_color = _runner_status(last_eval)
    if "#4caf50" in status_color:
        status_pill_cls = "alive"
    elif "#ff9800" in status_color:
        status_pill_cls = "stale"
    else:
        status_pill_cls = "dead"

    # Date nav
    prev_date = next((d for d in avail if d < sess_date), None)
    next_date = next((d for d in reversed(avail) if d > sess_date), None)

    # Summary stats
    ct = summary.closed_trades
    pnl = summary.realized_pnl
    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
    # Net of transaction costs — the headline number the header shows. Gross is kept
    # beside it rather than replaced, because the gap between them IS the finding.
    _net_pnls = [_net_of(t) for t in ct]
    pnl_net = round(sum(_net_pnls), 2) if _net_pnls else 0.0
    pnl_net_str = f"+${pnl_net:.2f}" if pnl_net >= 0 else f"-${abs(pnl_net):.2f}"
    _pf = _pf_json([t.pnl for t in ct])
    _net_pf = _pf_json(_net_pnls)
    _win_pct = round(summary.wins / len(ct) * 100, 1) if ct else 0.0
    pf_str = f"{_pf:.2f}" if _pf is not None else "∞"
    net_pf_str = f"{_net_pf:.2f}" if _net_pf is not None else ("∞" if ct else "—")
    # Colour off the NET PF: a gross PF of 1.2 that is 0.95 net is not a green number.
    pf_color = ("var(--green)" if (_net_pf is None or _net_pf >= 1.5)
                else "var(--orange)" if _net_pf >= 1.0 else "var(--red)")

    # Regime
    regime_label = regime.get("regime", "")
    skip_lbls = list(getattr(cfg, "regime_skip_labels", None) or [])
    regime_blocked = bool(getattr(cfg, "regime_gate_enabled", False) and regime_label in skip_lbls)
    regime_enabled = bool(getattr(cfg, "regime_gate_enabled", False))

    # Open position unrealized P&L
    open_pos_last = "—"
    open_pos_unreal_str = "—"
    open_pos_unreal_color = "var(--muted)"
    if summary.open_at_close:
        pos = summary.open_at_close[0]
        sym_evals = latest.get(pos.symbol, {})
        sym_last = (max(sym_evals.values(), key=lambda e: e.get("ts", ""))
                    if sym_evals else None)
        if sym_last:
            open_pos_last = f"${sym_last['close']:.3f}"
            is_short = pos.direction == "short"
            unreal = ((pos.entry_price - sym_last["close"]) if is_short
                      else (sym_last["close"] - pos.entry_price)) * pos.qty
            open_pos_unreal_str = f"+${unreal:.2f}" if unreal >= 0 else f"-${abs(unreal):.2f}"
            open_pos_unreal_color = "var(--green)" if unreal >= 0 else "var(--red)"

    # Market conditions partial (initial render; JS polls every 30s for updates)
    date_str = sess_date.strftime("%Y-%m-%d")
    market_cond_html = render_template(
        "partials/market_conditions.html",
        latest=latest, skips=skips, gap_status=gap_status, bar_time_label=date_str,
    )

    # Gate progress text
    gate_progress = ""
    try:
        from weekly_report import build_report
        gate_progress = build_report().replace("**", "")
    except Exception as e:
        gate_progress = f"unavailable: {e}"

    now_str = datetime.now().strftime("%H:%M:%S")

    return render_template("index.html",
        sess_date=sess_date,
        is_today=is_today,
        avail=avail,
        prev_date=prev_date,
        next_date=next_date,
        summary=summary,
        evals=evals,
        pnl=pnl,
        pnl_str=pnl_str,
        pnl_net=pnl_net,
        pnl_net_str=pnl_net_str,
        win_pct=_win_pct,
        pf_str=pf_str,
        net_pf_str=net_pf_str,
        pf_color=pf_color,
        status_label=status_label,
        status_pill_cls=status_pill_cls,
        regime=regime,
        regime_label=regime_label,
        regime_blocked=regime_blocked,
        regime_enabled=regime_enabled,
        vix=vix,
        open_pos_last=open_pos_last,
        open_pos_unreal_str=open_pos_unreal_str,
        open_pos_unreal_color=open_pos_unreal_color,
        market_cond_html=market_cond_html,
        gate_progress=gate_progress,
        now_str=now_str,
    )


# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="moomoo-trader web dashboard")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address (default 127.0.0.1 — use nginx for external access)")
    parser.add_argument("--date", help="Session date YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    global _date_override
    if args.date:
        _date_override = date.fromisoformat(args.date)

    print(f"Dashboard running at http://{args.host}:{args.port}")
    print(f"Session date: {_session_date()}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()

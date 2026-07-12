#!/usr/bin/env python3
"""Flask web dashboard — reads today's JSONL and serves at :8080.

Usage:
    python scripts/web_dashboard.py
    python scripts/web_dashboard.py --port 8080
    python scripts/web_dashboard.py --date 2026-06-01   # review past session
"""
import argparse
import hmac
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
from flask import Flask, Response, abort, jsonify, redirect, render_template_string, request, session, url_for
from markupsafe import escape
from mm import clock
from mm.config import cfg
from eod_summary import SessionSummary, load_summary

_PROJECT_ROOT = Path(__file__).parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

app = Flask(__name__)
# Random per-process secret: sessions reset on restart (deploys), which is fine.
# Never derive this from the password — the derivation scheme is public in this
# repo, so a deterministic key would turn any captured session cookie into
# offline brute-force material against the password.
app.secret_key = secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True  # only sent over HTTPS — nginx terminates TLS
_date_override: date | None = None

# In-memory login rate limit: max 5 failed attempts per IP per 15 minutes.
_LOGIN_MAX_FAILS = 5
_LOGIN_WINDOW_S = 900
_login_fails: dict[str, list[float]] = {}


def _client_ip() -> str:
    # X-Real-IP is set by nginx from $remote_addr (trusted upstream).
    # Never read X-Forwarded-For — clients can spoof it to bypass rate limiting.
    return request.headers.get("X-Real-IP", request.remote_addr or "?")


def _login_blocked(ip: str) -> bool:
    fails = [t for t in _login_fails.get(ip, []) if time.time() - t < _LOGIN_WINDOW_S]
    _login_fails[ip] = fails
    return len(fails) >= _LOGIN_MAX_FAILS

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
    "MAX_DAILY_LOSS", "MAX_POSITION_DOLLARS", "MAX_TRADES_PER_DAY",
    "MAX_TRADES_PER_STRATEGY", "MIN_SIGNAL_SCORE", "KDJ_WINDOW_BARS",
    "KDJ_WINDOW_OVERRIDES", "STRATEGIES", "SYMBOLS", "SYMBOL_SIZE_OVERRIDES",
    "ORB_MINUTES", "ORB_MINUTES_OVERRIDES", "ORB_VOL_MULT", "ORB_TARGET_MULT",
    "ORB_SHORTS_ENABLED", "TOTAL_CAPITAL", "FRACTIONAL_SHARES",
    "VWAP_PB_SYMBOLS", "VWAP_PB_MAX_CROSSES", "VWAP_PB_STOP_MULT",
    "ATR_STOP_MULT", "EXIT_ON_KDJ_DEATH",
}


def _require_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not cfg.dashboard_password:
            return f(*args, **kwargs)
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
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


_CSS_BASE = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: monospace; background: #111; color: #ddd; padding: 24px; font-size: 14px; }
h1 { font-size: 18px; margin-bottom: 20px; color: #fff; }
h2 { font-size: 13px; color: #666; letter-spacing: 1px; margin: 20px 0 10px; }
.card { background: #1a1a1a; border-radius: 6px; padding: 16px 18px; margin-bottom: 16px; }
input[type=password], input[type=text] {
  background: #222; border: 1px solid #333; color: #ddd; padding: 8px 10px;
  border-radius: 4px; font-family: monospace; font-size: 13px; width: 100%;
}
input[type=password]:focus, input[type=text]:focus {
  border-color: #555; outline: none;
}
button, .btn {
  background: #2a2a2a; border: 1px solid #444; color: #ddd; padding: 7px 14px;
  border-radius: 4px; font-family: monospace; font-size: 13px; cursor: pointer;
}
button:hover, .btn:hover { background: #333; border-color: #666; }
.btn-danger { border-color: #f44336; color: #f44336; }
.btn-danger:hover { background: #1a0000; }
.btn-warn { border-color: #ff9800; color: #ff9800; }
.btn-warn:hover { background: #1a0f00; }
.btn-ok { border-color: #4caf50; color: #4caf50; }
.btn-ok:hover { background: #001a00; }
.msg { padding: 8px 12px; border-radius: 4px; margin-bottom: 14px; font-size: 13px; }
.msg-ok { background: #001a00; border: 1px solid #4caf50; color: #4caf50; }
.msg-err { background: #1a0000; border: 1px solid #f44336; color: #f44336; }
.kv-row { display: grid; grid-template-columns: 220px 1fr 90px; gap: 8px;
           align-items: center; margin-bottom: 6px; }
.kv-label { color: #888; font-size: 12px; }
.switch-row { display: flex; gap: 10px; align-items: center; margin-bottom: 8px; }
a { color: #888; text-decoration: none; }
a:hover { color: #ddd; }
"""


@app.route("/login", methods=["GET", "POST"])
def login() -> Response | str:
    if not cfg.dashboard_password:
        return redirect(url_for("index"))
    error = ""
    if request.method == "POST":
        _check_csrf()
        ip = _client_ip()
        if _login_blocked(ip):
            error = "Too many attempts. Try again in 15 minutes."
        elif hmac.compare_digest(request.form.get("password", ""), cfg.dashboard_password):
            session["logged_in"] = True
            _login_fails.pop(ip, None)
            # only same-site relative redirects (block open-redirect via ?next=)
            nxt = request.args.get("next", "")
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = url_for("index")
            return redirect(nxt)
        else:
            _login_fails.setdefault(ip, []).append(time.time())
            error = "Wrong password."
    return render_template_string(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Login</title>
<style>{_CSS_BASE}</style></head>
<body>
  <h1>moomoo-trader</h1>
  <div class="card" style="max-width:340px">
    <h2>DASHBOARD LOGIN</h2>
    {('<div class="msg msg-err">' + error + '</div>') if error else ''}
    <form method="POST">
      <input type="hidden" name="_csrf_token" value="{_csrf_token()}">
      <input type="password" name="password" placeholder="Password" autofocus style="margin-bottom:10px">
      <button type="submit" style="width:100%">Sign in</button>
    </form>
  </div>
</body></html>""", error=error)


@app.route("/logout")
def logout() -> Response:
    session.clear()
    return redirect(url_for("index"))


@app.route("/api/stats")
@_require_login
def api_stats() -> Response:
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    cores = psutil.cpu_percent(percpu=True)
    load = psutil.getloadavg()
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
        try:
            procs.append({
                "pid": p.info["pid"],
                "name": (p.info["name"] or "")[:20],
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


@app.route("/config", methods=["GET", "POST"])
@_require_login
def config_editor() -> Response | str:
    if not cfg.dashboard_password:
        return render_template_string(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Config — moomoo-trader</title>
<style>{_CSS_BASE}</style></head>
<body>
  <h1>moomoo-trader &nbsp;<span style="color:#555;font-size:13px">/ config</span></h1>
  <a href="/">← back to dashboard</a>
  <div class="card" style="margin-top:20px;border-left:3px solid #f44336">
    <h2 style="color:#f44336">CONFIG EDITOR DISABLED</h2>
    <p style="margin-top:10px;color:#aaa">
      Set <code>DASHBOARD_PASSWORD=yourpassword</code> in <code>.env</code> and restart
      the dashboard service to enable the config editor.<br><br>
      Without a password the editor is open to anyone who can reach port 8080.
    </p>
  </div>
</body></html>""")
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
            for key in _EDITABLE_KEYS:
                if key in request.form:
                    val = request.form[key].strip()
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

    def _field(key: str) -> str:
        val = escape(current.get(key, ""))
        return (f'<div class="kv-row">'
                f'<span class="kv-label">{key}</span>'
                f'<input type="text" name="{key}" value="{val}" form="cfg-form">'
                f'</div>')

    numeric_keys = [
        "MAX_DAILY_LOSS", "MAX_POSITION_DOLLARS", "MAX_TRADES_PER_DAY",
        "MAX_TRADES_PER_STRATEGY", "MIN_SIGNAL_SCORE", "ATR_STOP_MULT",
        "KDJ_WINDOW_BARS", "ORB_MINUTES", "ORB_VOL_MULT", "ORB_TARGET_MULT",
        "VWAP_PB_MAX_CROSSES", "VWAP_PB_STOP_MULT", "TOTAL_CAPITAL",
    ]
    list_keys = [
        "STRATEGIES", "SYMBOLS", "VWAP_PB_SYMBOLS",
        "KDJ_WINDOW_OVERRIDES", "ORB_MINUTES_OVERRIDES", "SYMBOL_SIZE_OVERRIDES",
    ]
    bool_keys = [
        "FRACTIONAL_SHARES", "ORB_SHORTS_ENABLED", "EXIT_ON_KDJ_DEATH",
    ]

    fields_numeric = "\n".join(_field(k) for k in numeric_keys)
    fields_list = "\n".join(_field(k) for k in list_keys)
    fields_bool = "\n".join(_field(k) for k in bool_keys)

    stop_btn_cls = "btn-danger" if not kills["STOP_TRADING"] else "btn-ok"
    stop_btn_lbl = "Pause Trading (create STOP_TRADING.txt)" if not kills["STOP_TRADING"] else "Resume Trading (remove STOP_TRADING.txt)"
    stop_active = '<span style="color:#f44336">ACTIVE — trading paused</span>' if kills["STOP_TRADING"] else '<span style="color:#4caf50">inactive</span>'

    shorts_btn_cls = "btn-warn" if not kills["STOP_SHORTS"] else "btn-ok"
    shorts_btn_lbl = "Disable ORB Shorts (create STOP_SHORTS.txt)" if not kills["STOP_SHORTS"] else "Re-enable ORB Shorts (remove STOP_SHORTS.txt)"
    shorts_active = '<span style="color:#ff9800">ACTIVE — shorts disabled</span>' if kills["STOP_SHORTS"] else '<span style="color:#4caf50">inactive</span>'

    msg_html = f'<div class="msg msg-{escape(msg_type)}">{escape(msg)}</div>' if msg else ""

    return render_template_string(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Config — moomoo-trader</title>
<style>{_CSS_BASE}</style></head>
<body>
  <h1>moomoo-trader &nbsp;<span style="color:#555;font-size:13px">/ config</span></h1>
  <a href="/" style="font-size:12px">← back to dashboard</a>
  &nbsp;&nbsp;
  <a href="/logout" style="font-size:12px">logout</a>

  {msg_html}

  <!-- System stats (htop-style, toggle on/off) -->
  <div class="card" id="stats-card">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
      <h2 style="margin:0">SYSTEM</h2>
      <button id="stats-toggle" onclick="toggleStats()"
              class="btn btn-ok" style="font-size:11px;padding:4px 10px">▶ Start Live Feed</button>
    </div>
    <div id="stats-body" style="display:none">
      <!-- CPU cores -->
      <div style="margin-bottom:14px">
        <div class="kv-label" style="margin-bottom:6px">CPU CORES &nbsp;<span id="s-load" style="color:#666"></span></div>
        <div id="s-cores" style="display:flex;flex-wrap:wrap;gap:4px"></div>
      </div>
      <!-- Mem / Disk / Net row -->
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:14px">
        <div>
          <div class="kv-label" style="margin-bottom:4px">MEMORY</div>
          <div class="stat-bar-track"><div id="s-mem-bar" class="stat-bar" style="width:0%"></div></div>
          <div id="s-mem-lbl" style="font-size:11px;color:#888;margin-top:3px">—</div>
        </div>
        <div>
          <div class="kv-label" style="margin-bottom:4px">DISK</div>
          <div class="stat-bar-track"><div id="s-disk-bar" class="stat-bar" style="width:0%"></div></div>
          <div id="s-disk-lbl" style="font-size:11px;color:#888;margin-top:3px">—</div>
        </div>
        <div>
          <div class="kv-label" style="margin-bottom:4px">NETWORK (total)</div>
          <div id="s-net" style="font-size:12px;color:#aaa;margin-top:4px">—</div>
        </div>
      </div>
      <!-- Top processes -->
      <div>
        <div class="kv-label" style="margin-bottom:6px">TOP PROCESSES</div>
        <table id="s-procs" style="width:100%;border-collapse:collapse;font-size:12px">
          <thead><tr style="color:#555">
            <th style="text-align:left;padding:2px 6px">PID</th>
            <th style="text-align:left;padding:2px 6px">NAME</th>
            <th style="text-align:right;padding:2px 6px">CPU%</th>
            <th style="text-align:right;padding:2px 6px">MEM%</th>
            <th style="text-align:right;padding:2px 6px">S</th>
          </tr></thead>
          <tbody id="s-procs-body"></tbody>
        </table>
      </div>
    </div>
  </div>
  <style>
  .stat-bar-track {{ background:#222; border-radius:3px; height:10px; overflow:hidden; }}
  .stat-bar {{ background:#4caf50; height:10px; border-radius:3px; transition:width 0.4s; }}
  .stat-bar.warn {{ background:#ff9800; }}
  .stat-bar.crit {{ background:#f44336; }}
  .core-bar {{ display:inline-flex;flex-direction:column;align-items:center;gap:2px; }}
  .core-track {{ width:18px;height:60px;background:#222;border-radius:2px;display:flex;flex-direction:column;justify-content:flex-end;overflow:hidden; }}
  .core-fill {{ width:100%;background:#4caf50;transition:height 0.4s; }}
  .core-fill.warn {{ background:#ff9800; }}
  .core-fill.crit {{ background:#f44336; }}
  .core-lbl {{ font-size:9px;color:#555; }}
  </style>
  <script>
  var _statsInterval = null;

  function toggleStats() {{
    var btn = document.getElementById("stats-toggle");
    var body = document.getElementById("stats-body");
    if (_statsInterval) {{
      clearInterval(_statsInterval);
      _statsInterval = null;
      btn.textContent = "▶ Start Live Feed";
      btn.className = "btn btn-ok";
    }} else {{
      body.style.display = "block";
      fetchStats();
      _statsInterval = setInterval(fetchStats, 2000);
      btn.textContent = "■ Stop";
      btn.className = "btn btn-danger";
    }}
  }}

  function bar(pct) {{
    var cls = pct >= 90 ? "crit" : pct >= 70 ? "warn" : "";
    return cls;
  }}

  function fetchStats() {{
    fetch("/api/stats").then(r => r.json()).then(d => {{
      // CPU cores
      var cDiv = document.getElementById("s-cores");
      cDiv.innerHTML = "";
      d.cores.forEach(function(c, i) {{
        var cls = bar(c);
        cDiv.innerHTML += '<div class="core-bar">'
          + '<div class="core-track"><div class="core-fill ' + cls + '" style="height:' + c + '%"></div></div>'
          + '<div class="core-lbl">' + c.toFixed(0) + '</div>'
          + '</div>';
      }});
      document.getElementById("s-load").textContent = "load " + d.load[0] + " " + d.load[1] + " " + d.load[2];

      // Memory
      var mb = document.getElementById("s-mem-bar");
      mb.style.width = d.mem_pct + "%";
      mb.className = "stat-bar " + bar(d.mem_pct);
      document.getElementById("s-mem-lbl").textContent = d.mem_used_gb + " / " + d.mem_total_gb + " GB (" + d.mem_pct + "%)";

      // Disk
      var db = document.getElementById("s-disk-bar");
      db.style.width = d.disk_pct + "%";
      db.className = "stat-bar " + bar(d.disk_pct);
      document.getElementById("s-disk-lbl").textContent = d.disk_used_gb + " / " + d.disk_total_gb + " GB (" + d.disk_pct + "%)";

      // Network
      document.getElementById("s-net").textContent = "↑ " + d.net_sent_mb + " MB  ↓ " + d.net_recv_mb + " MB";

      // Processes
      var tbody = document.getElementById("s-procs-body");
      tbody.innerHTML = "";
      d.procs.forEach(function(p) {{
        var cpu_color = p.cpu > 50 ? "#f44336" : p.cpu > 20 ? "#ff9800" : "#aaa";
        tbody.innerHTML += "<tr style='border-top:1px solid #1f1f1f'>"
          + "<td style='padding:3px 6px;color:#555'>" + p.pid + "</td>"
          + "<td style='padding:3px 6px;color:#ccc'>" + p.name + "</td>"
          + "<td style='padding:3px 6px;text-align:right;color:" + cpu_color + "'>" + p.cpu + "</td>"
          + "<td style='padding:3px 6px;text-align:right;color:#888'>" + p.mem + "</td>"
          + "<td style='padding:3px 6px;text-align:right;color:#555'>" + p.status + "</td>"
          + "</tr>";
      }});
    }}).catch(function() {{}});
  }}
  </script>

  <!-- Kill switches -->
  <div class="card">
    <h2>KILL SWITCHES</h2>
    <div class="switch-row">
      <form method="POST">
        <input type="hidden" name="_csrf_token" value="{_csrf_token()}">
        <input type="hidden" name="action" value="toggle_stop_trading">
        <button type="submit" class="btn {stop_btn_cls}">{stop_btn_lbl}</button>
      </form>
      <span style="font-size:12px">STOP_TRADING.txt: {stop_active}</span>
    </div>
    <div class="switch-row">
      <form method="POST">
        <input type="hidden" name="_csrf_token" value="{_csrf_token()}">
        <input type="hidden" name="action" value="toggle_stop_shorts">
        <button type="submit" class="btn {shorts_btn_cls}">{shorts_btn_lbl}</button>
      </form>
      <span style="font-size:12px">STOP_SHORTS.txt: {shorts_active}</span>
    </div>
  </div>

  <!-- Restart -->
  <div class="card">
    <h2>RUNNER CONTROL</h2>
    <form method="POST">
      <input type="hidden" name="_csrf_token" value="{_csrf_token()}">
      <input type="hidden" name="action" value="restart_runner">
      <button type="submit" class="btn btn-warn">Restart moomoo-paper.service</button>
    </form>
    <div style="color:#555;font-size:11px;margin-top:6px">Config changes only take effect after restart.</div>
  </div>

  <!-- .env editor -->
  <form id="cfg-form" method="POST">
    <input type="hidden" name="_csrf_token" value="{_csrf_token()}">
    <input type="hidden" name="action" value="save_config">

    <div class="card">
      <h2>RISK / SIZING</h2>
      {fields_numeric}
    </div>

    <div class="card">
      <h2>STRATEGY / SYMBOL LISTS</h2>
      {fields_list}
    </div>

    <div class="card">
      <h2>FLAGS (true/false)</h2>
      {fields_bool}
    </div>

    <button type="submit" form="cfg-form" class="btn btn-ok"
            style="padding:10px 24px;font-size:14px">Save to .env</button>
    <span style="color:#555;font-size:11px;margin-left:10px">
      Writes to .env only — restart runner to apply.
    </span>
  </form>
</body></html>""")


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


def _render_gate_progress() -> str:
    """Gate-progress card: confirmed-fill trades vs pre-registered gate samples."""
    try:
        from weekly_report import build_report
        body = build_report().replace("**", "")
    except Exception as e:
        body = f"unavailable: {e}"
    return ('<div class="card"><div class="card-title">GATE PROGRESS '
            '<span style="color:#555;font-size:11px">(pre-registered, confirmed fills only)</span></div>'
            f'<pre style="margin:0;color:#aaa;font-size:12px;line-height:1.6">{body}</pre></div>')


def _render(summary: SessionSummary, evals: list[dict], market_cond_html: str = "",
            available_dates: list[date] | None = None,
            latest: dict | None = None) -> str:
    last_eval = evals[-1] if evals else None
    status_label, status_color = _runner_status(last_eval)
    now_str = datetime.now().strftime("%H:%M:%S")
    sess_date = _session_date()
    date_str = sess_date.strftime("%Y-%m-%d (%A)")
    is_today = sess_date == clock.today()

    # Date nav
    avail = available_dates or []
    prev_date = next((d for d in avail if d < sess_date), None)
    next_date = next((d for d in reversed(avail) if d > sess_date), None)
    prev_link = f'<a href="/?date={prev_date}" style="color:#555;text-decoration:none" title="Previous session">◀</a>' if prev_date else '<span style="color:#2a2a2a">◀</span>'
    next_link = f'<a href="/?date={next_date}" style="color:#555;text-decoration:none" title="Next session">▶</a>' if next_date else ('<a href="/" style="color:#555;text-decoration:none" title="Today">▶</a>' if not is_today else '<span style="color:#2a2a2a">▶</span>')
    today_link = '' if is_today else '<a href="/" style="font-size:11px;color:#555;margin-left:4px" title="Jump to today">today</a>'
    date_opts = "".join(
        f'<option value="{d}" {"selected" if d == sess_date else ""}>{d.strftime("%Y-%m-%d (%a)")}</option>'
        for d in avail
    )
    date_picker = f"""<span class="meta" style="display:flex;align-items:center;gap:5px">
      {prev_link}
      <form method="GET" style="display:inline;margin:0">
        <select name="date" onchange="this.form.submit()" style="background:#1a1a1a;border:1px solid #333;color:#aaa;font-family:monospace;font-size:12px;padding:2px 4px;border-radius:3px">
          {date_opts}
        </select>
      </form>
      {next_link}{today_link}
    </span>"""
    auto_refresh = '<meta http-equiv="refresh" content="30">' if is_today else ''

    last_score = str(last_eval.get("signal_score", "—")) if last_eval else "—"
    last_close = "—"

    ct = summary.closed_trades
    pnl = summary.realized_pnl
    pnl_str = _fmt_pnl(pnl)
    pnl_col = _pnl_color(pnl)

    # Open position block
    open_html = ""
    if summary.open_at_close:
        tr = summary.open_at_close[0]
        is_short = tr.direction == "short"
        unrealized = ""
        # Look up last close for the open position's symbol specifically.
        # last_eval is the most recent eval across all symbols (wrong for P&L).
        sym_evals = (latest or {}).get(tr.symbol, {})
        sym_last = (max(sym_evals.values(), key=lambda e: e.get("ts", ""))
                    if sym_evals else None)
        if sym_last:
            unreal = ((tr.entry_price - sym_last["close"]) if is_short
                      else (sym_last["close"] - tr.entry_price)) * tr.qty
            unrealized = f'<span style="color:{_pnl_color(unreal)}">{_fmt_pnl(unreal)} unrealized</span>'
        last_close = f"${sym_last['close']:.3f}" if sym_last else "—"
        dir_badge = (f'<span style="color:#f44336;font-weight:bold">SHORT</span>' if is_short
                     else f'<span style="color:#4caf50;font-weight:bold">LONG</span>')
        open_html = f"""
        <div class="card open-pos">
          <div class="card-title">OPEN POSITION</div>
          <table><tr>
            <td>Symbol</td><td><b>{tr.symbol}</b> {dir_badge}</td>
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
            # Slippage: 0.0 in SIMULATE, non-zero when live
            slip = tr.exit_slippage_bps
            slip_col = "#f44336" if slip > 5 else "#ff9800" if slip > 1 else "#555"
            slip_str = f"{slip:+.1f}" if slip != 0.0 else "—"
            strat_short = tr.strategy[:3].upper() if tr.strategy else "?"
            dir_badge = (' <span style="color:#f44336;font-size:11px" title="short">▼S</span>'
                         if tr.direction == "short" else "")
            rows += f"""<tr>
              <td>{tr.symbol.replace("US.", "")} <span style="color:#555;font-size:11px">{strat_short}</span>{dir_badge}</td>
              <td>{et}</td><td>{xt}</td>
              <td>${tr.entry_price:.3f}</td><td>${tr.exit_price:.3f}</td>
              <td style="color:{col}"><b>{_fmt_pnl(tr.pnl)}</b></td>
              <td>{icon} {tr.exit_reason}</td>
              <td>{tr.hold_minutes}m</td>
              <td style="color:{slip_col};font-size:11px" title="exit slippage bps">{slip_str}</td>
            </tr>"""
        trades_html = f"""
        <div class="card">
          <div class="card-title">TRADES</div>
          <table>
            <tr class="th"><th>Symbol</th><th>Entry</th><th>Exit</th>
            <th>Entry$</th><th>Exit$</th><th>P&L</th><th>Reason</th>
            <th>Hold</th><th title="Exit slippage (basis points). — = 0 in SIMULATE.">Slip</th></tr>
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
  {auto_refresh}
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
    <span class="runner-status">{status_label if is_today else f'HISTORY · {date_str}'}</span>
    {date_picker}
    <span class="meta">mode: {cfg.strategy_mode}</span>
    <span class="meta">symbol: {', '.join(cfg.symbols)}</span>
    <span class="meta">last price: {last_close}  score: {last_score}</span>
    <span class="meta" style="margin-left:auto">updated {now_str} · refreshes every 30s</span>
    <a href="/config" style="font-size:11px;color:#555;margin-left:8px;text-decoration:none"
       title="Config editor">⚙</a>
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

  {_render_gate_progress()}

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
    avail = _available_dates()
    summary = load_summary(_session_date())
    evals = _load_recent_evals()
    latest = _load_latest_evals_by_symbol()
    skips = _load_recent_skips()
    market_cond_html = _render_market_conditions(latest, skips)
    return _render(summary, evals, market_cond_html, available_dates=avail, latest=latest)


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

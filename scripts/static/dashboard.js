/* moomoo-trader dashboard JS */
"use strict";

// ── Constants ───────────────────────────────────────────────────────────────

const STRAT_COLORS = {
  bb_kdj:       "#3fb950",
  bb_kdj_loose: "#56d364",
  orb:          "#58a6ff",
  vwap_pb:      "#d29922",
  gap_fade:     "#db61a2",
  vwap:         "#bc8cff",
  unknown:      "#8b949e",
};

// ── Utilities ────────────────────────────────────────────────────────────────

function fmtPnl(v) {
  if (v === null || v === undefined) return "—";
  return (v >= 0 ? "+$" : "-$") + Math.abs(v).toFixed(2);
}

function pnlColor(v) {
  if (v === null || v === undefined) return "#8b949e";
  return v >= 0 ? "var(--green)" : "var(--red)";
}

function pfColor(v) {
  if (v === null) return "var(--green)";
  return v >= 1.5 ? "var(--green)" : v >= 1.0 ? "var(--orange)" : "var(--red)";
}

function pfStr(v) {
  return v === null ? "∞" : v.toFixed(2);
}

function setEl(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function setStyle(id, prop, val) {
  const el = document.getElementById(id);
  if (el) el.style[prop] = val;
}

function nowHMS() {
  const d = new Date();
  const p = n => String(n).padStart(2, "0");
  return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
}

function daysAgoDate(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  const p = n => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
}

// ── Tab switching ────────────────────────────────────────────────────────────

let _currentTab = "today";
let _scorecardLoaded = false;
let _aiGateLoaded = false;
let _tradeLogLoaded = false;

function switchTab(name) {
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  const panel = document.getElementById("tab-" + name);
  const btn = document.querySelector('[data-tab="' + name + '"]');
  if (panel) panel.classList.add("active");
  if (btn) btn.classList.add("active");
  _currentTab = name;

  if (name === "scorecard" && !_scorecardLoaded) {
    loadScoreboard(0);
    loadPnlChart(0);
    _scorecardLoaded = true;
    _tradeLogLoaded = true;
    loadTradeLog(0);
  }
  if (name === "ai-gate" && !_aiGateLoaded) {
    loadAiGate();
    _aiGateLoaded = true;
  }
}

// ── Live polling ─────────────────────────────────────────────────────────────

let _isToday = false;  // set by template

function pollSummary() {
  fetch("/api/today_summary").then(r => r.json()).then(function(d) {
    // Stats
    // Headline figures are NET of transaction costs; gross sits underneath so the
    // cost drag stays visible rather than being silently swapped in or out.
    const pnlNet = (d.pnl_net !== undefined && d.pnl_net !== null) ? d.pnl_net : d.pnl;
    const pEl = document.getElementById("stat-pnl");
    if (pEl) { pEl.textContent = fmtPnl(pnlNet); pEl.style.color = pnlColor(pnlNet); }
    setEl("stat-pnl-gross", "gross " + fmtPnl(d.pnl));

    setEl("stat-winpct", (d.win_pct || 0).toFixed(1) + "%");

    const netPf = (d.net_pf !== undefined) ? d.net_pf : d.pf;
    const pfEl = document.getElementById("stat-pf");
    if (pfEl) { pfEl.textContent = pfStr(netPf); pfEl.style.color = pfColor(netPf); }
    setEl("stat-pf-gross", "gross " + pfStr(d.pf));

    setEl("stat-trades", d.trades);
    setEl("stat-wins", d.wins);
    setEl("stat-losses", d.losses);
    setEl("stat-targets", d.targets);
    setEl("stat-stops", d.stops);
    setEl("stat-bars", d.bar_evals);

    // Regime badge in header
    const rEl = document.getElementById("regime-badge");
    if (rEl && d.regime) {
      const conf = d.regime_confidence ? " " + Math.round(d.regime_confidence * 100) + "%" : "";
      const icon = d.regime_blocked ? "⊘" : "◉";
      rEl.textContent = icon + " " + d.regime + conf;
      rEl.className = "regime-badge " + (d.regime_blocked ? "blocked" : "open");
    }

    // VIX badge
    const vEl = document.getElementById("vix-badge");
    if (vEl && d.vix !== null && d.vix !== undefined) {
      vEl.textContent = "VIX " + d.vix.toFixed(1);
      const col = d.vix >= 25 ? "var(--red)" : d.vix >= 20 ? "var(--orange)" : d.vix >= 15 ? "var(--yellow)" : "var(--green)";
      vEl.style.color = col;
    }

    // Updated timestamp
    setEl("last-updated", "updated " + nowHMS());
  }).catch(function() {});
}

function pollMarketConditions() {
  fetch("/market_conditions_frag").then(r => r.text()).then(function(html) {
    const el = document.getElementById("market-cond-container");
    if (el) el.innerHTML = html;
  }).catch(function() {});
}

// ── P&L chart (Chart.js) ─────────────────────────────────────────────────────

let _pnlChart = null;
let _pnlDays = 0;

let _pnlMode = "net";   // "net" | "gross"

function setPnlMode(mode) {
  _pnlMode = mode;
  document.querySelectorAll(".pnl-mode-btn").forEach(b =>
    b.classList.toggle("active", b.dataset.mode === mode));
  loadPnlChart(_pnlDays);
}

function loadPnlChart(days) {
  _pnlDays = days;
  document.querySelectorAll(".pnl-range-btn").forEach(b =>
    b.classList.toggle("active", parseInt(b.dataset.days) === days));
  document.querySelectorAll(".pnl-mode-btn").forEach(b =>
    b.classList.toggle("active", b.dataset.mode === _pnlMode));

  const url = days > 0 ? "/api/pnl_history?start=" + daysAgoDate(days) : "/api/pnl_history";
  fetch(url).then(r => r.json()).then(function(data) {
    const strategies = Object.keys(data);
    if (!strategies.length) return;

    const allDates = [...new Set(
      strategies.flatMap(s => data[s].map(p => p.date))
    )].sort();

    // Net is the default view. Gross is one click away rather than shown alongside —
    // five strategies × two curves is ten lines and reads as noise.
    const key = (_pnlMode === "gross") ? "cumulative" : "cumulative_net";
    const datasets = strategies.map(function(s) {
      const byDate = {};
      data[s].forEach(p => { byDate[p.date] = (p[key] !== undefined) ? p[key] : p.cumulative; });
      let last = 0;
      const points = allDates.map(d => {
        if (byDate[d] !== undefined) last = byDate[d];
        return last;
      });
      return {
        label: s,
        data: points,
        borderColor: STRAT_COLORS[s] || "#8b949e",
        backgroundColor: "transparent",
        tension: 0.1,
        pointRadius: 0,
        pointHoverRadius: 4,
        borderWidth: 1.5,
      };
    });

    const canvas = document.getElementById("pnl-canvas");
    if (!canvas) return;

    if (_pnlChart) _pnlChart.destroy();
    _pnlChart = new Chart(canvas, {
      type: "line",
      data: { labels: allDates.map(d => d.slice(5)), datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            labels: { color: "#8b949e", font: { family: "monospace", size: 11 }, boxWidth: 12 },
          },
          tooltip: {
            backgroundColor: "#161b22",
            borderColor: "#30363d",
            borderWidth: 1,
            titleColor: "#e6edf3",
            bodyColor: "#8b949e",
            callbacks: {
              label: ctx => " " + ctx.dataset.label + ": " + fmtPnl(ctx.raw),
            },
          },
        },
        scales: {
          x: {
            ticks: { color: "#4a5568", maxTicksLimit: 10, font: { family: "monospace", size: 10 } },
            grid: { color: "#21262d" },
          },
          y: {
            ticks: {
              color: "#8b949e",
              font: { family: "monospace", size: 10 },
              callback: v => "$" + v.toFixed(0),
            },
            grid: { color: "#21262d" },
          },
        },
      },
    });
  }).catch(function() {});
}

// ── Scorecard table ───────────────────────────────────────────────────────────

let _scoreDays = 0;

function loadScoreboard(days) {
  _scoreDays = days;
  document.querySelectorAll(".score-range-btn").forEach(b =>
    b.classList.toggle("active", parseInt(b.dataset.days) === days));

  const url = days > 0 ? "/api/scoreboard?start=" + daysAgoDate(days) : "/api/scoreboard";
  const NCOL = 10;
  const tbody = document.getElementById("scorecard-tbody");
  const span = (cls, msg) =>
    `<tr><td colspan="${NCOL}" class="${cls}" style="padding:8px 10px">${msg}</td></tr>`;
  if (tbody) tbody.innerHTML = span("muted", "Loading…");

  fetch(url).then(r => r.json()).then(function(rows) {
    if (!tbody) return;
    if (!rows.length) { tbody.innerHTML = span("muted", "No trades yet."); return; }
    tbody.innerHTML = rows.map(r => {
      const stCol = STRAT_COLORS[r.strategy] || "#8b949e";
      // A CI straddling 1.0 means the sample cannot distinguish this strategy from
      // no edge at all. Dim the row and mark it, so a flattering point estimate
      // can't be read as a result — every live strategy currently qualifies.
      const dim = r.inconclusive ? ' class="inconclusive"' : "";
      const ci = (r.ci_lo === null || r.ci_lo === undefined)
        ? '<span class="muted">n&lt;2</span>'
        : `[${r.ci_lo.toFixed(2)}, ${r.ci_hi === null ? "∞" : r.ci_hi.toFixed(2)}]`;
      const flag = r.inconclusive
        ? ' <span class="zero-edge" title="95% CI contains 1.0 — consistent with zero edge">⚠</span>'
        : "";
      const bps = (r.avg_bps_net === null || r.avg_bps_net === undefined)
        ? "—"
        : (r.avg_bps_net > 0 ? "+" : "") + r.avg_bps_net.toFixed(1);
      return `<tr${dim}>
        <td><span class="strat-badge ${r.strategy}" style="color:${stCol};border-color:${stCol}">${r.strategy}</span></td>
        <td class="right num">${r.trades}</td>
        <td class="right num">${r.win_pct}%</td>
        <td class="right num muted">${pfStr(r.gross_pf)}</td>
        <td class="right num" style="color:${pfColor(r.net_pf)}">${pfStr(r.net_pf)}${flag}</td>
        <td class="right num" style="font-size:11px">${ci}</td>
        <td class="right num" style="color:${pnlColor(r.avg_bps_net)}">${bps}</td>
        <td class="right num muted">${fmtPnl(r.gross_pnl)}</td>
        <td class="right num" style="color:${pnlColor(r.net_pnl)}"><b>${fmtPnl(r.net_pnl)}</b></td>
        <td class="right muted" style="font-size:11px">${r.last_trade}</td>
      </tr>`;
    }).join("");
  }).catch(function() {
    if (tbody) tbody.innerHTML = span("muted", "Failed to load.");
  });
}

// ── Trade log ─────────────────────────────────────────────────────────────────

let _tradeRows = [];
let _tradeSortKey = "ts";
let _tradeSortAsc = false;
let _tradeDays = 0;

function loadTradeLog(days) {
  _tradeDays = days;
  document.querySelectorAll(".trade-range-btn").forEach(b =>
    b.classList.toggle("active", parseInt(b.dataset.days) === days));

  const url = days > 0 ? "/api/trades?start=" + daysAgoDate(days) : "/api/trades";
  fetch(url).then(r => r.json()).then(function(rows) {
    _tradeRows = rows;
    _tradeSortKey = "ts";
    _tradeSortAsc = false;
    renderTradeLog();
  }).catch(function() {
    const tb = document.getElementById("tradelog-tbody");
    if (tb) tb.innerHTML = '<tr><td colspan="9" class="muted" style="padding:8px 10px">Failed to load.</td></tr>';
  });
}

function sortTradeLog(key) {
  if (_tradeSortKey === key) _tradeSortAsc = !_tradeSortAsc;
  else { _tradeSortKey = key; _tradeSortAsc = key !== "ts"; }
  renderTradeLog();
}

function renderTradeLog() {
  const rows = _tradeRows.slice().sort(function(a, b) {
    const av = a[_tradeSortKey] === null ? "" : a[_tradeSortKey];
    const bv = b[_tradeSortKey] === null ? "" : b[_tradeSortKey];
    if (av < bv) return _tradeSortAsc ? -1 : 1;
    if (av > bv) return _tradeSortAsc ? 1 : -1;
    return 0;
  });
  setEl("tradelog-sort-label", "sort: " + _tradeSortKey + " " + (_tradeSortAsc ? "▲" : "▼"));
  const tbody = document.getElementById("tradelog-tbody");
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="11" class="muted" style="padding:8px 10px">No trades.</td></tr>';
    return;
  }
  const stCol = s => STRAT_COLORS[s] || "#8b949e";
  tbody.innerHTML = rows.map(r => {
    const pnl = r.pnl !== null ? r.pnl : 0;
    const net = (r.pnl_net !== null && r.pnl_net !== undefined) ? r.pnl_net : pnl;
    const bpsn = (r.bps_net !== null && r.bps_net !== undefined)
      ? (r.bps_net > 0 ? "+" : "") + r.bps_net.toFixed(1) : "—";
    const reasonCls = r.reason === "TARGET" ? "TARGET" : r.reason === "STOP" ? "STOP" : "TIME_STOP";
    // Gross is muted, net is bold: costs are not optional, so net is the number
    // that should catch the eye. A trade that flips sign between them is the
    // whole point of showing both.
    return `<tr>
      <td class="muted">${r.date || "?"}</td>
      <td><b>${(r.symbol || "").replace("US.", "")}</b></td>
      <td><span class="strat-badge ${r.strategy}" style="color:${stCol(r.strategy)};border-color:${stCol(r.strategy)}">${r.strategy || "?"}</span></td>
      <td><span class="dir-badge ${r.direction || "long"}">${(r.direction || "long").toUpperCase()}</span></td>
      <td class="right num">${r.entry !== null ? r.entry.toFixed(2) : "—"}</td>
      <td class="right num">${r.exit !== null ? r.exit.toFixed(2) : "—"}</td>
      <td class="right num muted">${fmtPnl(pnl)}</td>
      <td class="right num" style="color:${pnlColor(net)}"><b>${fmtPnl(net)}</b></td>
      <td class="right num" style="color:${pnlColor(net)}">${bpsn}</td>
      <td class="right muted">${r.hold_bars || 0}</td>
      <td><span class="reason-badge ${reasonCls}">${r.reason || "?"}</span></td>
    </tr>`;
  }).join("");
}

// ── AI Gate ───────────────────────────────────────────────────────────────────

let _regimeHistory = [];
let _skipLabels = [];

function loadAiGate() {
  fetch("/api/regime_history").then(r => r.json()).then(function(data) {
    _regimeHistory = data.history;
    _skipLabels = data.skip_labels;
    renderRegimeBars();
    renderRegimeCalendar();
    renderGateValue();
  }).catch(function() {});

  loadOrbScorer();
}

function renderGateValue() {
  const history = _regimeHistory;
  if (!history.length) return;

  let blockedDays = 0, blockedPnl = 0, openDays = 0, openPnl = 0;
  history.forEach(d => {
    if (d.blocked) { blockedDays++; blockedPnl += d.pnl || 0; }
    else if (d.label) { openDays++; openPnl += d.pnl || 0; }
  });

  setEl("gv-blocked-days", blockedDays + "d");
  const saved = document.getElementById("gv-pnl-avoided");
  if (saved) {
    saved.textContent = fmtPnl(blockedPnl);
    saved.style.color = blockedPnl <= 0 ? "var(--green)" : "var(--red)";
  }
  const openEl = document.getElementById("gv-open-pnl");
  if (openEl) {
    openEl.textContent = fmtPnl(openPnl);
    openEl.style.color = pnlColor(openPnl);
  }
}

function renderRegimeBars() {
  const container = document.getElementById("regime-bars");
  if (!container) return;

  const byLabel = {};
  _regimeHistory.forEach(d => {
    if (!d.label) return;
    const s = byLabel[d.label] = byLabel[d.label] || { days: 0, trades: 0, gross_win: 0, gross_loss: 0 };
    s.days++;
    s.trades += d.trades || 0;
    s.gross_win += d.gross_win || 0;
    s.gross_loss += d.gross_loss || 0;
  });

  const skipSet = new Set(_skipLabels);
  const labels = Object.keys(byLabel).sort();
  if (!labels.length) {
    container.innerHTML = '<div class="muted" style="font-size:12px;padding:8px 0">No regime data yet.</div>';
    return;
  }

  // Max PF for bar scaling
  const allPfs = labels.map(l => {
    const s = byLabel[l];
    return s.gross_loss > 0 ? s.gross_win / s.gross_loss : (s.gross_win > 0 ? 3 : 1);
  });
  const maxPf = Math.max(2, ...allPfs);

  const LABEL_COLORS = {
    neutral: "var(--green)", choppy: "var(--orange)",
    trending_up: "var(--red)", trending_down: "var(--red)",
    risk_off: "var(--red)",
  };

  container.innerHTML = labels.map(label => {
    const s = byLabel[label];
    const blocked = skipSet.has(label);
    const pf = s.gross_loss > 0 ? s.gross_win / s.gross_loss : null;
    const pfVal = pf !== null ? pf.toFixed(2) : (s.gross_win > 0 ? "∞" : "—");
    const pfPct = pf !== null ? Math.min(100, (pf / maxPf) * 100) : (s.gross_win > 0 ? 100 : 5);
    const col = LABEL_COLORS[label] || "var(--blue)";
    const statusTxt = blocked ? "BLOCKED" : "OPEN";
    const pfClr = pf === null ? "var(--green)" : pf >= 1.5 ? "var(--green)" : pf >= 1.0 ? "var(--orange)" : "var(--red)";
    return `<div class="regime-bar-row">
      <div class="regime-bar-label" style="color:${col}">${label}</div>
      <div class="regime-bar-track">
        <div class="regime-bar-fill" style="width:${pfPct}%;background:${pfClr}"></div>
      </div>
      <div class="regime-bar-stats">PF <span style="color:${pfClr}">${pfVal}</span> &nbsp;·&nbsp; ${s.days}d ${s.trades}t</div>
      <div class="regime-bar-status" style="color:${blocked ? "var(--red)" : "var(--green)"}">${statusTxt}</div>
    </div>`;
  }).join("");
}

function renderRegimeCalendar() {
  const container = document.getElementById("regime-calendar");
  if (!container) return;

  const skipSet = new Set(_skipLabels);
  const LABEL_COLORS = {
    neutral: "#3fb950", choppy: "#d29922",
    trending_up: "#f85149", trending_down: "#f85149",
    risk_off: "#f85149",
  };

  const history = _regimeHistory.slice(-90);
  if (!history.length) {
    container.innerHTML = '<div class="muted" style="font-size:12px">No data.</div>';
    return;
  }

  container.innerHTML = history.map(d => {
    const col = d.label ? (LABEL_COLORS[d.label] || "#8b949e") : "#30363d";
    const blocked = d.blocked;
    const opacity = blocked ? "1" : (d.label ? "0.45" : "0.3");
    const border = blocked ? `2px solid ${col}` : "2px solid transparent";
    const pnlStr = fmtPnl(d.pnl || 0);
    const tip = `${d.date}: ${d.label || "no data"} · ${d.trades || 0}t ${pnlStr}` +
                (blocked ? " [BLOCKED]" : "");
    return `<div class="cal-day" style="background:${col};opacity:${opacity};border:${border}" title="${tip}"></div>`;
  }).join("");
}

// ── ORB scorer ────────────────────────────────────────────────────────────────

function loadOrbScorer() {
  fetch("/api/orb_scorer_history").then(r => r.json()).then(function(data) {
    renderOrbScorer(data);
  }).catch(function() {
    const el = document.getElementById("orb-scorer-section");
    if (el) el.style.display = "none";
  });
}

function renderOrbScorer(data) {
  if (!data || !data.setups || !data.setups.length) {
    const el = document.getElementById("orb-scorer-section");
    if (el) el.innerHTML = '<div class="muted" style="font-size:12px;padding:8px 0">No ORB scorer data yet (shadow mode).</div>';
    return;
  }

  setEl("scorer-total", data.setups.length);
  setEl("scorer-avg", data.avg_confidence !== null ? data.avg_confidence.toFixed(2) : "—");
  setEl("scorer-threshold", data.threshold !== null ? data.threshold.toFixed(2) : "—");
  setEl("scorer-above", data.above_threshold);

  // Histogram
  const hist = document.getElementById("score-histogram");
  if (!hist) return;
  const buckets = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9];
  const counts = new Array(10).fill(0);
  data.setups.forEach(s => {
    const idx = Math.min(9, Math.floor(s.confidence * 10));
    counts[idx]++;
  });
  const maxCount = Math.max(1, ...counts);
  hist.innerHTML = buckets.map((b, i) => {
    const h = Math.round((counts[i] / maxCount) * 56);
    const cls = b >= (data.threshold || 0.5) ? "above-threshold" : "";
    return `<div class="score-bar-wrap">
      <div class="score-bar ${cls}" style="height:${h}px"></div>
      <div class="score-bar-lbl">${b.toFixed(1)}</div>
    </div>`;
  }).join("");
}

// ── System stats (config panel) ───────────────────────────────────────────────

let _statsInterval = null;

function toggleStats() {
  const btn = document.getElementById("stats-toggle");
  const body = document.getElementById("stats-body");
  if (_statsInterval) {
    clearInterval(_statsInterval);
    _statsInterval = null;
    if (btn) { btn.textContent = "▶ Start Live Feed"; btn.className = "btn ok"; }
    if (body) body.style.display = "none";
  } else {
    if (body) body.style.display = "block";
    fetchSysStats();
    _statsInterval = setInterval(fetchSysStats, 2000);
    if (btn) { btn.textContent = "■ Stop"; btn.className = "btn danger"; }
  }
}

function fetchSysStats() {
  fetch("/api/stats").then(r => r.json()).then(function(d) {
    const sysLoad = document.getElementById("sys-load");
    if (sysLoad) sysLoad.textContent = "load " + d.load.join(" ");

    const cores = document.getElementById("sys-cores");
    if (cores) {
      cores.innerHTML = d.cores.map(c => {
        const h = Math.round(c * 0.56);
        const col = c >= 90 ? "var(--red)" : c >= 70 ? "var(--orange)" : "var(--green)";
        return `<div class="core-col">
          <div class="core-track"><div class="core-fill" style="height:${h}px;background:${col}"></div></div>
          <div style="font-size:9px;color:var(--muted);font-family:monospace">${c.toFixed(0)}</div>
        </div>`;
      }).join("");
    }

    const barFill = function(id, pct) {
      const el = document.getElementById(id);
      if (!el) return;
      el.style.width = pct + "%";
      el.className = "sys-bar-fill " + (pct >= 90 ? "red" : pct >= 70 ? "orange" : "green");
    };
    barFill("sys-mem-bar", d.mem_pct);
    setEl("sys-mem-lbl", d.mem_used_gb + " / " + d.mem_total_gb + " GB");
    barFill("sys-disk-bar", d.disk_pct);
    setEl("sys-disk-lbl", d.disk_used_gb + " / " + d.disk_total_gb + " GB");
    setEl("sys-net", "↑ " + d.net_sent_mb + " MB  ↓ " + d.net_recv_mb + " MB");

    const tbody = document.getElementById("sys-procs-body");
    if (tbody) {
      tbody.innerHTML = d.procs.map(p => {
        const cc = p.cpu > 50 ? "var(--red)" : p.cpu > 20 ? "var(--orange)" : "var(--muted)";
        return `<tr>
          <td class="muted" style="padding:3px 8px">${p.pid}</td>
          <td style="padding:3px 8px;font-family:monospace">${p.name}</td>
          <td class="right" style="padding:3px 8px;color:${cc}">${p.cpu}</td>
          <td class="right muted" style="padding:3px 8px">${p.mem}</td>
          <td class="right muted" style="padding:3px 8px">${p.status}</td>
        </tr>`;
      }).join("");
    }
  }).catch(function() {});
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", function() {
  // Default tab = today
  switchTab("today");

  if (_isToday) {
    setInterval(pollSummary, 30000);
    setInterval(pollMarketConditions, 30000);
  }
});

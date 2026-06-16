# Deep Research Briefing — Moomoo Paper Trading Lab
**Date:** 2026-06-16  
**Purpose:** Comprehensive context document for deep research engines (ChatGPT, Claude). This file is self-contained. Reference files in this directory provide supplemental detail.

---

## 1. What This Project Is

A Python-based intraday paper trading research system running on a VPS, connected to the Moomoo brokerage API (US equities, SIMULATE mode only — never real capital). The goal is not to "get rich now" but to build a **truth machine**: a system whose paper trading behavior matches its backtesting behavior closely enough that when we eventually deploy real capital, we have genuine confidence.

The system runs three concurrent mean-reversion/breakout strategies on SPY, QQQ, and IWM (US ETFs) using 5-minute candles. It is in a **live paper testing phase** — strategies are backtested and validated, but still accumulating live paper trades to confirm the backtest edge survives real execution.

**Key constraint:** Every strategy is tested against OOS (out-of-sample) data before deployment. We have a pre-registered evaluation criteria document that specifies in advance what live results would cause us to change or suspend a strategy — to prevent rationalizing failures after the fact.

---

## 2. Tech Stack

- **Language:** Python 3.12, package `mm/`
- **Broker API:** Moomoo OpenD (local daemon) via `moomoo-api` Python package
- **Data:** 5-minute OHLCV candles from Moomoo/OpenD for US.SPY, US.QQQ, US.IWM
- **Historical data on disk:** 86,412 candles per symbol (2022-01-03 to 2026-06-09, combined CSV)
- **Live logging:** JSONL event logs (position_open, position_close, bar_eval, signal_skip, risk_block, order_attempt, order_result) — structured for analysis
- **Infrastructure:** VPS running two systemd services (paper runner + web dashboard), Discord webhook for alerts, Flask dashboard on port 8080
- **Testing:** 173 unit tests, replay harness that runs live runner code on historical candles with a fake broker

---

## 3. Current Data Pipeline

```
OpenD (127.0.0.1:11111)
    │
    ▼
mm/data.py — fetch_candles() → DataFrame (time_key, open, high, low, close, volume)
    │         [5-min bars, labeled at END time e.g. "09:35" = 9:30-9:35 bar]
    │
    ▼
mm/indicators.py — add_all() computes:
    │   Bollinger Bands (20,2): bb_upper, bb_middle, bb_lower
    │   ATR (14-period)
    │   KDJ (9,3): kdj_k, kdj_d, kdj_j, kdj_golden_cross, kdj_death_cross
    │   RSI (14-period)
    │   ADX (14-period)
    │   VWAP (session, resets at 9:30 ET)
    │   EMA5, EMA20
    │   volume_ma (20-bar)
    │   bb_width_pct (rolling percentile of BB width)
    │
    ▼
mm/evals.py — per-strategy signal evaluation every 60 seconds
```

**What we do NOT currently have:**
- Pre-market candles (4:00am–9:30am ET)
- Level 2 / order book depth
- Tick data or time & sales
- Options chain data
- Futures data (ES, NQ) alongside cash ETFs
- Any alternative data (VIX term structure, options flow, economic calendar)

This is the core limitation driving this research.

---

## 4. Active Strategies — Full Results

### Strategy 1: BB+KDJ Mean Reversion

**Logic:** 5-min close ≤ Bollinger lower band (20,2) AND KDJ golden cross within prior 3 bars AND bonus score ≥ 2 (needs 2 of: RSI<35, ADX<25 regime, volume spike >1.5×MA). Exit: close ≥ BB middle (target) or close < entry − ATR (stop).

**Key parameters (frozen — do not re-tune without live gate):**
- `KDJ_WINDOW_BARS=3` (IWM/QQQ), `=0` (SPY)
- `MIN_SIGNAL_SCORE=2`
- `ATR_STOP_MULT=1.0`

**Backtest results (2022-2025, SPY+QQQ+IWM, 5-min):**
| Symbol | Trades | Win% | Total PnL | PF |
|--------|--------|------|-----------|-----|
| SPY | 29 | 41.4% | +$2.34 | ~1.3 |
| QQQ | 21 | 42.9% | +$4.21 | ~1.4 |
| IWM | 27 | 59.3% | +$8.95 | ~1.9 |
| Combined | 77 | 48.1% | +$15.49 | 1.843 |

**Walk-forward:** OOS (train 2022-23, test 2024-25): PF=1.843 confirmed.

**Live status:** 0 confirmed live trades so far (low-frequency strategy, conditions haven't aligned). Gate: 30 live trades before strategy-level conclusions.

**KDJ dilution finding (important):** Same-bar KDJ cross (w=0) has PF=2.131 on 82 trades over 4 years — genuine edge. w=3 dilutes to 10x more trades but PF drops to 1.107. Currently deployed at w=3 for frequency; may switch to w=0 if PF gate trips.

**IWM outperformance root cause:** Lower stop rate (38% vs 50-58% for SPY/QQQ), faster reversals (132 min avg hold vs 309/507). IWM's BB+KDJ signal is more predictive. Reason not fully understood — may relate to smaller-cap mean reversion dynamics.

---

### Strategy 2: ORB (Opening Range Breakout)

**Logic:** First 15 min of session (9:30-9:45 ET) defines OR high/low. After cutoff, if close breaks above OR high with volume > 1.2× MA → long. If close breaks below OR low → short. Stop at opposite OR boundary. Target: 1.5× OR range from entry. Time stop: 15:45 ET. IWM uses 30-min OR instead of 15-min.

**Key parameters (frozen):**
- `ORB_MINUTES=15` (SPY/QQQ), `=30` (IWM override)
- `ORB_TARGET_MULT=1.5`
- `ORB_VOL_MULT=1.2`
- `ORB_SHORTS_ENABLED=true`

**Backtest results (2022-2025, combined):** PF=1.215, 54.5% win rate, ~0.9 trades/day combined.

**Live execution issue identified (2026-06-16):** Entry limit placed AT signal bar close. True breakouts continue moving away from the close → unfilled. Reversals come back → filled with negative slippage. Fill rate was only 38.9% (7/18 attempts), all fills with negative slippage. **Fix deployed:** Entry limit now `close × 1.001` for longs, `close × 0.999` for shorts (chases the breakout 0.1%).

**Live status:** 7 confirmed fills. Gate: 30 trades. ORB short code is deployed but first live short has not fired yet — the SELL_SHORT API path is unverified in practice.

**Most execution-sensitive strategy in the set.** The backtest assumes fills at signal close; live execution adds 60-second polling lag. ORB is likely the strategy most affected by execution quality.

---

### Strategy 3: VWAP Pullback (Flush-and-Reclaim)

**Logic:** 5-min candle wicks below VWAP (low < vwap) but closes above it. Session cross count ≤ 1 (no-chop filter — critical). Volume below MA on entry bar (quiet pullback). No entry before 10:00 ET. Exit: close < VWAP (level lost), ATR stop (1.0×), or 15:45 time stop. SPY/QQQ only — IWM fails OOS.

**Key parameters (frozen):**
- `VWAP_PB_MAX_CROSSES=1` (strict no-chop filter)
- `VWAP_PB_MIN_ENTRY_TIME=10:00`
- `VWAP_PB_STOP_MULT=1.0`

**Backtest results:**
| Symbol | OOS PF |
|--------|---------|
| SPY | 1.655 |
| QQQ | 1.072 |
| IWM | negative (excluded) |

**Live status:** 4 confirmed trades (all losses, all VWAP_LOST). But the 4 pre-filter losses were 9:50 ET opening noise under the old 9:45 filter — not counted against the gate. Gate counter at 0/20 post-filter deployment. Needs more live data.

**Root cause of 4 losses:** All were 9:50 ET opening-noise entries before the 10:00 filter was deployed. The filter fix is structural, not a strategy change.

---

### Strategy 4: Gap Fade (BUILT 2026-06-16, not yet deployed live)

**Logic:** Overnight gap = (today's first bar open − yesterday's last close) / yesterday's last close. If abs(gap) ≥ 0.3% and ≤ 2.0%, and the first 5-min bar closes AGAINST the gap direction (gap up + red first bar → short; gap down + green first bar → long), enter at first bar close (9:35 ET). Stop: first bar extreme × (1 ± 0.1%). Target: 50% gap fill. Time stop: 11:00 ET.

**Walk-forward results (0.3% min gap, 50% fill target):**
| Symbol | Train 2022-23 | OOS 2024-25 | 2026 YTD |
|--------|---------|---------|---------|
| IWM | PF=1.031, 136 tr | PF=**1.938**, 164 tr, 72%WR | PF=2.163, 33 tr |
| SPY | PF=1.022, 147 tr | PF=1.326, 108 tr, 60%WR | — |
| QQQ | PF=1.029, 156 tr | PF=1.022, 143 tr | excluded |

**Strongest OOS result in the portfolio.** IWM OOS PF=1.938 on 164 trades is larger sample and stronger edge than any other strategy. Consistent across all parameter combinations (sweep tested min_gap 0.2-1.0%, fill 30-100%: every IWM cell PF > 1.38).

**Why training is weak (PF≈1.02 across all three symbols in 2022-23):** The 2022-2023 bear market produced large, meaningful overnight gaps driven by real macro information (Fed hikes, SVB). Gaps that represent genuine information don't fade. The 2024-2025 OOS improvement is structural (lower volatility, more "noise" gaps). Regime risk: if volatility returns to 2022 levels, the strategy may degrade.

**Enablement gates:** ORB short must fire live at least once first (same SELL_SHORT code path). Then 15 live paper trades minimum before drawing conclusions.

**Why this matters for data research:** This strategy is the one most obviously improved by pre-market data. Currently we measure the gap from yesterday's 4pm close to the 9:35 bar — we're blind to what happened overnight. A gap that's already been 70% filled by 9:25 AM in pre-market trading looks identical to an intact gap in our current data but behaves completely differently.

---

## 5. Portfolio Correlation

Analyzed using backtest engines on 4 years of combined data (5,363 trades across all strategies and symbols, 1,111 trading days).

**Pairwise daily PnL correlation:**
| Pair | Pearson r | Interpretation |
|------|-----------|----------------|
| bb_kdj × orb | 0.031 | Independent |
| bb_kdj × vwap_pb | 0.078 | Independent |
| orb × vwap_pb | 0.060 | Independent |

**Effective independent strategies: 2.9 / 3.0.** The diversification is real — three strategies that fire on genuinely different market conditions.

**Worst day (Jan 26, 2022): −$24.86 per share** — all three strategies lost simultaneously. This demonstrates that macro stress creates correlation even between otherwise independent strategies. Normal market conditions: 45% of trading days are losing days at portfolio level, avg +$0.41/day.

**Max drawdown (4-year backtest): −$56.64 per share**, trough May 2025, 122 active days underwater.

**62% of entries happen while another position is open.** ORB and VWAP PB overlap most (1,711 times) since both trade SPY/QQQ through the day, but PnL correlation is still near zero.

---

## 6. What We've Tested and Rejected

*(Full details in strategy_graveyard.md — this is the summary)*

| Idea | Why Dead |
|------|----------|
| VWAP crossover (momentum) | PF 0.877-1.024 across all combos. VWAP crosses at 5-min are pure noise |
| VWAP mean-reversion (price below = buy) | 42% win, PF≈1.0. Price below VWAP is continuation not reversion |
| EMA5/EMA20 momentum breakout | Uniformly negative (PF 0.3-0.93). Stop parameter inert |
| VIX daily regime filter | All filtered variants worse than baseline. High-VIX days are IWM's BEST entries |
| ORB afternoon cutoff | 2026 YTD data showed afternoon ORB −$93/75 trades. But 2022-2025 OOS shows afternoon ORB +$65/698 trades PF=1.16. Not structural — rejected |
| KDJ death cross exit | Re-enabling flips SPY PnL from +$2.34 to −$0.83. Cuts winning trades too early |
| Session filter (block certain hours) | No hour is universally safe to block. Small sample makes per-hour deltas unreliable |
| ADX trailing stops | BB middle is cleaner and has proven OOS edge. Trailing stop adds parameter and risk of premature exit |
| VIX 3-tier strategy switching | Unvalidated assumption; VIX not predictive (see VIX filter above) |
| Symbol expansion (DIA, TLT, XLK, XLF) | Every new symbol needs full backtest + OOS cycle. No edge hypothesis |

---

## 7. Current Limitations of 5-min OHLCV Data

This is the core subject of the research agenda.

**What candles don't tell you:**

1. **Intrabar sequence:** A 5-min bar with open=100, high=102, low=99, close=101 could represent: (a) immediately selling off to 99 then recovering to 101, or (b) rallying to 102 then selling back to 101. These have completely different implications for the next bar's likely direction. Candles are lossy.

2. **Pre-market activity:** The "overnight gap" we measure is from yesterday's 4pm close to today's 9:35 bar. But the actual gap forms continuously from 4pm to 9:30am. A gap that's been 80% closed by 9:20am in pre-market trading is qualitatively different from one that's fully intact at the open. We can't distinguish them.

3. **Order flow / who is buying vs. selling:** A 5-min bar with high volume could be aggressive buyers absorbing sellers (bullish), or aggressive sellers overwhelming buyers (bearish). Volume alone doesn't tell you directionality. Tick data (uptick/downtick) does.

4. **Level 2 / liquidity distribution:** Where do large bid/ask walls sit? ORB breakouts that hit a large ask wall immediately after the OR high are much less likely to continue than breakouts into thin air. We're blind to this.

5. **Options market information:** Dealer gamma positioning creates predictable "gravity" toward major strike prices at expiration. If SPY is above a major gamma strike, dealers hedging dynamically can dampen volatility and suppress our ORB and VWAP PB signals. We don't account for this at all.

6. **Correlation to macro catalysts:** We don't know if a bar occurs 5 minutes before a Fed announcement. FOMC, CPI, NFP events systematically change intraday behavior. Our strategies have no calendar awareness.

---

## 8. Research Questions

### Track 1 — Moomoo API Capabilities (most actionable, zero cost)

*If Moomoo already exposes this data, implementation is days not months.*

1. Does the Moomoo OpenD API expose pre-market and after-hours candles? What ktype parameter? What are the time boundaries (4am? 7am?)?
2. Does `quote_context()` expose Level 2 order book depth (bid/ask size at multiple price levels)? What is the `StockQuoteHandlerBase` WebSocket handler's full data schema?
3. Does Moomoo expose tick data or time & sales via any API call? What is the historical tick data retention period?
4. Does Moomoo expose options chain data (strikes, implied volatility, open interest, volume) for SPY/QQQ/IWM? What calls are available?
5. Does Moomoo expose futures data (ES, NQ, RTY)? Can these be fetched alongside the cash ETFs?
6. What is the exact data schema for `get_rt_data()`, `get_broker_queue()`, `get_order_book()` — do these exist in the Python API?

### Track 2 — Pre-Market Gap Characterization

*Directly improves gap fade strategy. Strong empirical research base exists.*

1. What does the academic/practitioner literature say about the relationship between pre-market gap size and gap fill rates? Are pre-market partially-filled gaps less likely to complete filling at the open?
2. Is there evidence that ES/NQ futures premium at 9:29 ET (last minute before cash open) is predictive of gap fade success/failure?
3. What is the practitioner consensus on classifying gaps as "informational" (driven by real news, unlikely to fade) vs "noise" (liquidity gap, likely to fade)? What metrics distinguish them?
4. For small-cap ETFs specifically (like IWM), is there evidence that overnight gaps behave differently from large-cap (SPY/QQQ)? The IWM gap fade shows 72% win rate OOS while SPY/QQQ are marginal — is there a structural reason for this?
5. What pre-market volume threshold (if any) has empirical support as a filter for gap fade strategies?

### Track 3 — Options Flow as Intraday Regime Filter

*Orthogonal to all existing signals. Could improve all three current strategies.*

1. **GEX (Dealer Gamma Exposure):** What is GEX, how is it calculated, and what does the academic and practitioner literature say about its predictive power for intraday ETF range and direction? What is the evidence for "gamma pinning" near major strikes?
2. **0DTE options flow on SPY:** Is there peer-reviewed or practitioner evidence that same-day options flow (volume, put/call ratio, net delta) leads or lags the underlying? On what timeframe?
3. **OpEx calendar effects:** Is there systematic evidence that options expiration days (monthly, weekly) produce different intraday behavior for SPY/QQQ/IWM? Specifically: does volatility compress or expand? Does mean reversion or breakout edge increase/decrease?
4. **Practical data access:** What is the cheapest/most accessible source for real-time or delayed GEX data? SpotGamma, SqueezeMetrics, CBOE — what do they cost, what do they expose, what are the API options?
5. **Regime filter application:** How do practitioners actually incorporate options data as a regime filter for intraday equity strategies? Is there a standard approach?

### Track 4 — Alternative Data Cost Landscape

*Determines what's feasible to add to the pipeline without significant ongoing cost.*

1. **Polygon.io:** What does the "Stocks Starter" vs "Stocks Developer" plan provide? Does it include: pre-market candles, tick data, Level 2, options chain? What is the actual cost per month? What is the Python client API like?
2. **Databento:** What does historical tick data for SPY/QQQ/IWM cost going back to 2022? What about real-time? What is the data format and Python API?
3. **CBOE DataShop:** What is available for free vs paid? Is there a free options data feed with sufficient granularity for GEX calculation?
4. **FirstRate Data:** What does their 1-min and tick data cost for US ETFs? Is pre-market included?
5. **Free alternatives:** What data is genuinely available for free with sufficient quality for research? FRED, Yahoo Finance, CBOE website — what are the limits?
6. **Moomoo data quality vs alternatives:** Is there a known quality comparison between Moomoo-sourced 5-min candle data and Polygon/Databento for the same symbols and time periods? Are there known data issues with Moomoo's historical data?

---

## 9. What Good Research Outputs Look Like

For each track, what we need the research to return:

**Track 1:** A complete list of Moomoo OpenD Python API calls that expose data beyond OHLCV. Specifically: does pre-market exist, does L2 exist, does options exist. Include the exact Python method names and key parameters.

**Track 2:** A summary of empirical evidence (with citations if possible) on pre-market gap behavior and gap fill rates. A specific recommendation on whether pre-market candles would materially improve a gap fade strategy, and if so, what the key signal would be (e.g., "if gap is >70% filled in pre-market, skip the fade").

**Track 3:** An explanation of GEX mechanics accessible to a quant who understands derivatives but hasn't used GEX specifically. Evidence for or against OpEx calendar effects on intraday ETF behavior. Practical recommendation on whether options flow is worth incorporating at our current scale (10-50 live trades).

**Track 4:** A comparison table of data vendors with: what they offer, cost, Python API quality, and a recommendation for our use case (small retail paper trader, research focus, willing to pay up to $100/month for genuinely useful data).

---

## 10. Project Constraints and Context

**What we will NOT do:**
- Change to real capital trading (SIMULATE mode only, hard-coded safety checks)
- Add a strategy without backtest + OOS validation
- Re-tune strategy parameters on live data (pre-registered evaluation criteria)
- Expand to new symbols without a specific edge hypothesis and full backtest cycle
- Build ML models before having minimum 500 live trades as training data

**What we're optimizing for:**
- Evidence-based confidence that the strategies work
- Execution quality (fill rate, slippage measurement)
- Operational reliability (the runner needs to survive market days without manual intervention)

**The honest state of live evidence:**
~10 confirmed live paper trades across all strategies. Everything else is backtests and replay harness. The system is well-built but in the early evidence-accumulation phase. Research into better data is the right parallel track while live trades accumulate at market speed.

**Why IWM keeps outperforming:**
Across all three active strategies, IWM consistently shows better OOS results than SPY or QQQ. BB+KDJ IWM: PF=1.9 vs SPY=1.3, QQQ=1.4. Gap fade IWM OOS: PF=1.938 vs SPY=1.326, QQQ=1.022. ORB IWM (30-min): PF=1.217. The reason is not fully understood — likely relates to small-cap ETF dynamics (higher noise-to-signal ratio at the individual stock level cancels to create more predictable ETF-level reversions). This pattern should inform which symbols are prioritized in future strategy development.

---

## 11. Reference Files in This Directory

- `ARCHITECTURE.md` — system data flow diagram, active strategies table, key config vars, kill switches
- `strategy_graveyard.md` — everything tested, found dead, built dark, or on hold with full findings
- `evaluation_criteria.md` — pre-registered gates for each live strategy (read this to understand what would trigger a strategy change)
- `PROJECT_MAP.md` — full file inventory, script descriptions, test suite, VPS config

---

*This document was prepared to brief deep research engines with full project context. The researcher should treat the strategy results and portfolio findings as directional, not definitive — sample sizes are modest and the live evidence is early. The data research agenda is independent of live trading progress and can proceed in parallel.*

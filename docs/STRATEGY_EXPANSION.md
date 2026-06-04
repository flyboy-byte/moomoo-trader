# Strategy Expansion: From Conservative to Comprehensive

This document outlines the architectural and quantitative roadmap for the next phase of the `moomoo` trading system. It addresses the transition from a "long-only, polling-based" system to a "direction-agnostic, event-driven" platform.

---

## 1. Shorting Capability: Closing the Opportunity Gap

Current research shows that the Opening Range Breakout (ORB) strategy generates signals in both directions. By remaining long-only, we are discarding ~50% of the strategy's statistical edge.

### Implementation Blueprint
Shorting in the Moomoo API (and paper trading) requires distinct side flags:
*   **Entry:** `TrdSide.SELL_SHORT` (equivalent to `SELL` but for opening a position).
*   **Exit:** `TrdSide.BUY_BACK` (equivalent to `BUY` but for closing a short).

**Risk Considerations:**
*   **Margin Check:** Paper accounts typically have $1M+, but for live scaling, we must verify `can_short` status per symbol.
*   **Stop Management:** Short stops are price-above entries. The `PaperPosition` class needs a `direction` field to flip stop logic (e.g., `if close >= stop_price` for shorts).

---

## 2. VIX Regime Filtering: Strategic Switching

The "Strategy Graveyard" identifies that Trend Following (TF) often fails in choppy markets, while Mean Reversion (MR) thrives. Instead of running all strategies with fixed parameters, we should use the **VIX Index** as a master regime switch.

### The Switching Model
| Regime | VIX Level | Primary Strategy | Logic |
| :--- | :--- | :--- | :--- |
| **Stable (Trend)** | < 15 | **ORB** (Long/Short) | Markets exhibit persistent follow-through. |
| **Active (Mixed)** | 15–28 | **VWAP Pullback** | Institutional levels are respected; wicks are meaningful. |
| **Crisis (Mean-Rev)** | > 30 | **BB+KDJ** (Relaxed) | Panic creates extremes that "snap back" reliably. |

### Addressing "Over-Carefulness"
To increase trade frequency without losing quality, we implement **Conditional Permissiveness**:
*   **High VIX (>30):** Drop `MIN_SIGNAL_SCORE` for BB+KDJ from 2 to 1. In high-volatility environments, the "reversion force" is stronger, making secondary filters less necessary.
*   **Low VIX (<15):** Increase `ORB_TARGET_MULT` from 1.5 to 2.0 to capture the extended trends characteristic of "quiet" bull markets.

---

## 3. Symbol Scaling: Diversifying the Universe

Scaling beyond SPY/QQQ/IWM requires selecting symbols that respond differently to market regimes.

### Recommended Symbol Additions
1.  **DIA (Dow Jones):** Lower beta than QQQ. Excellent for BB+KDJ during rotation periods where tech (QQQ) is being dumped.
2.  **XLK (Tech) / XLF (Finance):** Sector-specific volatility often leads or lags the broad index.
3.  **TLT (20+ Yr Treasury):** Inversely correlated to equities during "Flight to Quality." A great candidate for ORB when stocks are flat.

**Adaptive Selection Logic:**
Implement a `SymbolRegimeMap` that disables VWAP PB on IWM (as research shows it fails OOS) but enables it on DIA.

---

## 4. Execution Refinement: Moving to Push Notifications

The current 60s polling creates a "Lag Tax." For ORB, a 60s delay can mean the difference between a 1:1.5 RR and a 1:0.8 RR.

### The Push Architecture
Transitioning from `fetch_candles` (polling) to `OpenQuoteContext` (push):
1.  **Stateful Cache:** Maintain a `PriceCache` in memory that is updated via `StockQuoteHandlerBase`.
2.  **Intra-Bar Exits:** Stops and targets should check the *latest price push* every second, rather than waiting for the 5-min bar to close.
3.  **Signal Stability:** Continue to use 5-min closed bars for *entries* (to avoid "noise" entries), but use push data for *exits* to minimize slippage.

---

## 5. Observability: Dashboard & Signal Transparency

To support this expansion, we must move from a "PnL Tracker" to a **"System Diagnostic Tool"** by enhancing both the log files and the Web Dashboard.

### A. The "Market Conditions" Card (Log + UI)
Surface the internal variables currently hidden:
*   **Regime Display:** Record/Show current VIX level and active regime (e.g., `REGIME: CRISIS`).
*   **Time Block Status:** Visual indicator if the system is currently in a `BLOCKED_HOUR`.
*   **Volatility Metrics:** Record/Show ATR Percentile and ADX value for the active symbol.

### B. The "Why No Entry" Feed
The most common question during a quiet session is "Why didn't we trade?"
*   **Live Signal Scoreboard:** A real-time table of all 5 signals (BB Touch, KDJ Cross, etc.) showing ✓ or ✗ for the current bar.
*   **Skip Reasons:** Display the reason for the last "Signal Skip" in the logs and UI (e.g., `REASON: Score 1 < 2` or `REASON: ORB Vol < 1.2x`).

### C. Execution Health
*   **Slippage Tracker:** Calculate and display the `slippage_bps` (difference between order price and fill price) to monitor the health of the push architecture.
*   **Heartbeat Monitor:** A "Pulse" indicator that flashes when a `bar_eval` event is received, confirming the loop is active.

---

## 6. Safety Gating Protocol: Protecting the Production Runner

**Safety Gating** is the mandatory decoupling of high-risk architectural changes from the stable production environment. For this project, a feature is "Gated" if it requires a pilot phase before integration.

### The Three Gates
1.  **Isolated Pilot (Shadow Mode):** The feature must first run as a standalone script (e.g., `scripts/live_price_monitor.py`). It has **zero authority** to place orders. It logs performance and stability data only.
2.  **Deterministic Stress Testing:** The feature must be subjected to simulated failures—specifically, how it handles WebSocket disconnects, OpenD restarts, and stale/missing data. It must demonstrate a clean "reconnect or fail-safe" behavior.
3.  **Measurable Edge Proof:** Before merging into `paper.py`, the data from the pilot must prove the change is beneficial. For example, Step 5 (Push API) must prove that the reduction in `slippage_bps` outweighs the increased complexity and potential for WebSocket "chatter."

---

## 7. Strategy Hardening: Beyond the Basics

To move from "profitable" to "robust," we must address the "wrong" ways of trading (e.g., fixed targets in variable markets).

### A. Dynamic ATR-Based Profit Taking
Fixed targets (e.g., BB Middle) can be too rigid.
*   **Mean Reversion:** Implement a "Stretch Exit"—if price overshoots the BB Middle with high momentum, use a **1.5x ATR Trailing Stop** to capture the "pierce" rather than exiting exactly at the mean.
*   **ORB:** Use a **2.0x ATR multiplier** as a "Hard Target" when the OR range is unusually small, preventing the strategy from aiming for a target that is statistically improbable given the day's volatility.

### B. Active Window Optimization (Time-of-Day)
Research in the "Graveyard" shows that BB+KDJ is a "trap" during the 10:00–11:00 AM ET window (post-open chop).
*   **Hard Blackouts:** Implement `BLOCKED_HOURS=10,11` for BB+KDJ.
*   **The "Golden Hour":** Focus ORB execution strictly between 9:45 AM and 11:30 AM ET. Any breakouts after 1:00 PM ET are often "low-conviction" moves and should be sized 50% smaller.

### C. Economic Event Gating
Large "Black Swan" moves (CPI, FOMC) destroy technical indicators.
*   **Manual Gate:** Create a `STOP_FOR_NEWS.txt` flag that pauses entries for 30 minutes surrounding major prints.
*   **Volatility Spike Filter:** If 1-minute ATR is > 3x the 60-minute average, pause all new entries (automatic "News detection").

---

## 8. Advanced Risk: Volatility-Adjusted Sizing

Currently, we use a fixed dollar cap. This is "wrong" because a $900 position in a high-volatility environment is much riskier than the same $900 in a quiet market.

### The "Dollar-at-Risk" Model
Instead of `MAX_POSITION_DOLLARS`, Claude should implement **ATR Sizing**:
1.  **Risk per Trade:** Define a fixed dollar risk (e.g., $10 per trade).
2.  **Qty Formula:** `Qty = Risk_Dollars / (Stop_Distance_in_Price)`.
3.  **Benefit:** This automatically buys *fewer* shares when stops are wide (high vol) and *more* shares when stops are tight (low vol), keeping your equity curve smooth.

---

## 9. Senior Engineer Priority Ranking

If building this in phases, I recommend this order based on **ROI (Return on Effort)** and **System Stability**:

| Rank | Feature | Impact | Effort | Why |
| :--- | :--- | :--- | :--- | :--- |
| **1** | **ORB Shorts** | ⭐⭐⭐⭐⭐ | Low | Immediately doubles your opportunity set on a validated edge. |
| **2** | **Volatility Sizing** | ⭐⭐⭐⭐⭐ | Med | Critical for "hardening." Smooths the equity curve by normalizing risk. |
| **3** | **VIX Regime Filter** | ⭐⭐⭐⭐ | Med | Adds "intelligence." Prevents strategy mismatch during market shifts. |
| **4** | **Time-of-Day Gating** | ⭐⭐⭐ | Low | "Low hanging fruit." Eliminates known traps (10-11 AM chop). |
| **5** | **Push API (Exits)** | ⭐⭐⭐ | High | High technical lift, but essential to eliminate the "Lag Tax" on stops. |
| **6** | **Dynamic Targets** | ⭐⭐ | Med | Refinement. Adaptive exits improve win rate in "pierce" scenarios. |
| **7** | **News Gating** | ⭐⭐ | Low | Pure safety. Protects against black swans/CPI prints. |

---

## Summary of Action Items

1.  [ ] **Enable ORB Shorts:** Update `paper.py` to support `SELL_SHORT` and flip stop logic.
2.  [ ] **VIX Integration:** Add `yfinance` to `risk.py` to pull the VIX index at session open.
3.  [ ] **Push Notification Pilot:** Create a `scripts/live_price_monitor.py` to test WebSocket stability before integrating into the runner.
4.  [ ] **Relaxed MR Mode:** Implement the `VIX > 30` logic to drop the BB+KDJ score requirement automatically.

*Research conducted on June 4, 2026. This plan prioritizes statistical edge expansion over simple frequency increase.*

# Senior Engineer Master Audit & Scaling Roadmap

**Date:** June 16, 2026  
**Auditor:** AI-assisted research

---

## 1. Executive Context: The "Scientific Lab" Vision
*This section provides the high-level "Why" to keep project management aligned with technical execution.*

### The Big Picture (The "Lab" Phase)
This project is currently a **Scientific Laboratory**. We have built a **Robot Scientist** that watches the market every day and writes down exactly what happens in its notebook (the JSONL logs). 
*   **The Goal:** We aren't trying to "get rich" today. We are trying to prove that our **Robot's Reality** (Paper Trading) matches the **History Books** (Backtesting). If they match, we have a "Truth Machine" that we can trust with real capital later.

### Risk Sizing (The "Poker" Analogy)
We recently implemented **ATR-Sizing**. In plain English: 
*   If the market is wild and dangerous, the bot bets a small amount (e.g., $2). 
*   If the market is calm, the bot bets a larger amount (e.g., $10). 
*   **The Result:** Every time the bot loses, it loses roughly the **same amount of money**. This protects the account from "Black Swan" events that could wipe out weeks of progress in one day.

---

## 2. Technical Red-Team Audit (Critical Flaws)

I have analyzed the execution plumbing with a destructive mindset. Here are the specific areas where the bot will fail as you scale.

### I. The "Netting Deletion" Bug (Critical)
In `mm/execution.py: _reconcile_positions`, the logic is: "If broker has 0 shares of X, delete all local positions of X."
*   **The Scenario:** You run `bb_kdj` (Long) and `gap_fade` (Short) on SPY. Your broker net position is **0 shares**.
*   **The Failure:** The reconciliation loop will see 0 shares at the broker, assume they are "ghosts," and **delete both local state files**. 
*   **The Result:** You now have two unmanaged "virtual" trades running in your bot's head that have no exit logic, while the broker is flat. This makes multi-strategy running on the same asset mathematically dangerous.

### II. The "Zombie Order" Race Condition
`_execute_entry` is a blocking poll. 
*   **The Failure:** If the script or VPS crashes *after* the order fills at Moomoo but *before* the `_save_position` call, the bot loses its memory of the trade.
*   **The Result:** You wake up to a "Zombie Position" that the bot doesn't know exists. While the new reconciliation logic *warns* about orphans, it doesn't "adopt" them or close them automatically.

### III. Indicator Performance Bottleneck
`mm/evals.py` calls `add_all(df_raw)` every 60 seconds.
*   **The Debt:** You are currently re-calculating Bollinger Bands and KDJ for **86,000 bars** every minute. 
*   **The Result:** As your CSV data grows, the "Lag Tax" will increase from 1 second to 10+ seconds just to compute math that was already computed 60 seconds ago.

---

## 3. Strategic Vision: From "Bot" to "Fund"

### I. The "Machine Learning" Feedback Loop
You are sitting on a goldmine of JSONL data (`signal_skip`, `bar_eval`). 
*   **The Vision:** We should build a **"Meta-Filter."** This is a small ML model (XGBoost/RandomForest) that looks at the 20 bars *before* a trade. 
*   **The Goal:** The bot says "I see a BB+KDJ signal," but the Meta-Filter says "Wait, every time the 50-SMA is sloping down this fast, this signal fails. SKIP." This turns your "Scientific Lab" into a "Self-Correcting System."

### II. Global Exposure Management (The Portfolio Move)
Currently, risk is managed *per trade*.
*   **The Vision:** We need a **Portfolio Layer**. It should look at the "Correlation" of your symbols.
*   **The Goal:** If SPY, QQQ, and Mag-7 are all 95% correlated, the bot shouldn't be allowed to go MAX long on all of them at once. It should calculate a **Net Portfolio Delta** and cap your total account risk.

---

## 4. Expansion Roadmap (The "Magnificent" Scale)

### Phase 1: The Universe Manager
*   **Expansion:** Move away from hardcoded `SYMBOLS=SPY,QQQ,IWM`.
*   **Task:** Create a script that scans the top 50 high-volume ETFs every morning and picks the top 5 with the best "Mean Reversion Score."

### Phase 2: Multi-Timeframe Confluence
*   **Expansion:** The bot is currently "blind" to the big picture (1-hour or 4-hour charts).
*   **Task:** Implement a "Trend Guard." If the 1-hour chart is in a death spiral, the 5-min BB+KDJ "Long" signal should be ignored.

---

## 5. Immediate Engineering Mandate for Claude

**Do not just "fix bugs." Re-engineer for scale.**

1.  **Fix Reconciliation:** Re-write `_reconcile_positions` to check the **Net Virtual Position** against the **Broker Net Position**. If they don't match, trigger a "Position Sync" instead of a "Delete State."
2.  **Optimize TA Engine:** Update `mm/indicators.py` to support **incremental updates** (only calculate the last bar) or at least prune the input dataframe to the last 500 bars for calculation.
3.  **Per-Symbol Error Handling:** Move the error backoff logic from the global loop to a per-symbol level so a failure in one asset doesn't stop the whole system.
4.  **Harden the JSONL Schema:** Add a `meta_features` key to `bar_eval` that captures 10-bar slope, volatility, and volume-at-time-of-day. This is your "Training Data" for the future ML phase.

---

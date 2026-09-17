# Scouting — where the machinery could go next (2026-09-17)

**Status:** input for a user decision; nothing chosen. Context: two preregistered scans on 85 US
symbols were null (graveyard § "Wide Scan", § "Route 3"). The user chose to park this universe and
point the engine somewhere else. This doc compares the candidates so that choice can be made with
facts.

**Evidence tags** (as in `playbat/docs/ledger.md`):
- **VERIFIED** — checked live this session.
- **REPORTED** — from a web source, not checked here.
- **INFERRED** — reasoning, not a source.

**Network note:** during this pass, most direct API probes from this machine failed at the
connection level (curl `000`, including outside the sandbox), and SSH to the VPS timed out before
the banner. Only `data.binance.vision` answered. Every API-availability claim below other than
Binance's archive is therefore REPORTED and needs a live re-check before any build.

## What carries over

| Part | Portable? |
|---|---|
| `mm/stats.py` (day-block bootstrap), `mm/scan.py` rules (BH, finalists, holdout), preregistration workflow | Yes, unchanged |
| `mm/daily_scan.py`, the fast bar engines (bb_kdj, orb, vwap_pb) | Yes, for anything with OHLCV bars. The session logic (09:30 open, 15:45 signal) must be generalized for 24/7 markets |
| `mm/costs.py` | Pattern yes; the per-symbol table must be rebuilt per market |
| `mm/data.py`, `mm/bulk_fetch.py`, OpenD, the live runner, the dashboard | No, moomoo-specific. A new market needs its own fetcher and (if wanted) its own paper runner |

## Candidates

### 1. Crypto (spot, maybe perpetual futures)

| | |
|---|---|
| **Data** | Binance's public archive `data.binance.vision`, no account needed: BTCUSDT 5-min monthly files exist from **2017-08** to **2026-08** (VERIFIED, HTTP 200 on both). Perpetual funding-rate files are also in the archive (REPORTED; the probe failed with the network issue). |
| **Costs** | Binance spot at the base tier is ~10 bps per side (INFERRED from widely published schedule; not re-checked). Alpaca crypto is 15 bps maker / 25 bps taker at entry tier ([REPORTED](https://docs.alpaca.markets/docs/crypto-trading)). **Round trip ≈ 20–50 bps**, 10–30× the US ETF cost table. |
| **Paper trading** | Alpaca's paper API likely covers crypto (REPORTED, unconfirmed). Binance.com is unavailable to US residents (INFERRED); archive data is fine for research either way. |
| **Crowding** | Less efficient than US ETFs historically, but heavily botted now (INFERRED). |
| **Fit** | Best fit for the existing engine: same bar shape, deep free history, many symbols, no quota. |
| **Main risk** | Costs. Intraday edges here would need to clear 20–50 bps, which kills most 5-min ideas before they start. Daily/weekly horizons (trend and momentum are the documented crypto effects) or funding-rate carry fit the cost structure better. |

### 2. Prediction markets (Kalshi; Polymarket US)

| | |
|---|---|
| **Data** | Kalshi public market data (series, markets, trades, candlesticks at 1-min / 1-hour / 1-day) needs no authentication. Settled markets move to `/historical/` endpoints. History since ~2021 ([REPORTED](https://docs.kalshi.com/api-reference/market/get-market-candlesticks), [guide](https://www.predictionhunt.com/blog/kalshi-api-getting-started-guide)). Polymarket US is CFTC-regulated since late 2025, and its API needs KYC. Its historical depth is disputed between sources ([REPORTED](https://www.quantvps.com/blog/polymarket-us-api-available)). |
| **Costs** | Kalshi taker fee = ceil(0.07 × C × P × (1−P)), max 1.75¢ per contract at 50¢. Maker fees are mostly 0, with exceptions on big events ([REPORTED](https://whirligigbear.substack.com/p/makertaker-math-on-kalshi)). At P = 0.5 that is ~3.5% of the stake per side. Cheaper near 0 or 1. |
| **Paper trading** | Kalshi has a demo environment (INFERRED from common reports; unconfirmed). |
| **Crowding** | Least crowded of the options by institutional quants (INFERRED). Documented anomalies exist in the betting literature, e.g. the favourite–longshot bias (INFERRED from general literature, not checked here). |
| **Fit** | Weakest engine fit. Contracts are binary and expire; there are no long continuous price series per symbol. The stats and preregistration machinery transfers well; the bar engines mostly don't. |
| **Main risk** | New domain modelling (calibration, event data), thin liquidity per market, fees that are large per side. |

### 3. Smaller US stocks via moomoo

| | |
|---|---|
| **Data** | Same OpenD path. The 100-symbols-per-30-days history quota is the constraint: 82 slots are spent until ~2026-10-17 (VERIFIED earlier, Step 9 ledger). |
| **Costs** | The frozen formula already scales with price and liquidity, so small caps get higher hurdles automatically (INFERRED from `docs/wide_scan_methodology.md`). |
| **Paper trading** | The existing runner works as is. |
| **Crowding** | Less than mega-caps (INFERRED). |
| **Fit** | Highest code reuse (zero new plumbing), lowest novelty. It is the same kind of rules on the same kind of bars that just came back null twice. |
| **Main risk** | The quota makes a universe build take months. Higher costs likely offset the lower crowding. |

### 4. US index futures (micro contracts)

Moomoo futures quotes need a paid permission: `get_future_info(['US.VXmain'])` returned
"Insufficient quote permission" (VERIFIED 2026-08-25, `playful-honking-crayon` plan). **Out
unless the user pays for quotes.**

### 5. Not a market

The preregistration, bootstrap and cost-honest reporting machinery applies to any "does this
rule beat a baseline" question (sports statistics, A/B-style tests, other projects). It has the
highest intellectual reuse and zero trading risk, and it is a different project.

## Comparison

| | Data (free, deep) | Cost hurdle | Engine reuse | Crowding | Novelty vs the nulls |
|---|---|---|---|---|---|
| Crypto | ✅ 2017→ (verified) | ❌ 20–50 bps | ✅ high | 🚧 medium | 🚧 medium |
| Prediction markets | 🚧 2021→ (reported) | ❌ up to ~3.5%/side | ❌ low | ✅ low | ✅ high |
| Small US stocks | 🚧 quota-limited | 🚧 higher than ETFs | ✅ highest | 🚧 medium | ❌ low |
| Micro futures | ❌ paid | ✅ low | ✅ high | ❌ high | ❌ low |
| Not a market | n/a | n/a | 🚧 method only | n/a | ✅ high |

## Claude's read (INFERRED, for the user to accept or not)

- **Crypto is the natural pilot.** The data is verified, free and deep, and the engine drops in.
  Aim it at **daily-horizon** rules, where 20–50 bps round trips are affordable, not at 5-min
  bars. `mm/daily_scan.py` plus a 24/7 session definition is most of the work.
- **Prediction markets are the most interesting** and the least crowded, but they are a
  modelling project more than an engine port.
- Small US stocks mainly repeat what already failed.

**Next step if crypto is chosen:** a preregistration (universe, costs, windows, rules) committed
before any archive is downloaded, then a pilot inside `moomoo` in its own `logs/crypto/` folder.
Rename or re-scope the repo only if the pilot is worth continuing (discussed with the user
2026-09-17).

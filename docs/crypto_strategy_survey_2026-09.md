# Crypto strategy survey — what's already documented (2026-09-17)

**Status:** input for the crypto pilot's preregistration; nothing tested here yet.

**Setup (user decision 2026-09-17):** Binance's public archive for research data, Alpaca paper
for any trading. The Alpaca paper account is verified: crypto is active, 36 tradable `/USD`
pairs, BTC spread 2.0 bps and ETH 1.2 bps at the time of the check.

**Evidence tags:**
- **REPORTED** — a paper or article claims it; not checked here.
- **INFERRED** — reasoning.
- **VERIFIED** — checked live.

## The constraints that decide what's testable

These do more to decide what's worth testing than any paper does.

1. **Long-only spot.** Alpaca crypto is spot, and short selling is not supported (INFERRED from
   Alpaca's spot-only crypto offering; confirm before relying on it). Long-short and short-leg
   strategies can be *studied* on Binance data but not paper-traded.
2. **Costs of ~45–55 bps per round trip** at market: Alpaca's 15/25 bps maker/taker fees plus the
   spread ([Alpaca](https://docs.alpaca.markets/docs/crypto-trading), REPORTED; spread VERIFIED).
   This is ~30× the US ETF table. Anything that trades daily or faster needs a huge gross edge.
3. **Universe:** coins tradable on Alpaca ∩ Binance archive, minus stablecoins and PAXG. That is
   roughly 25–30 large-cap coins, so the illiquid-small-coin effects in the literature don't apply.
4. **History:** Binance 5-min data from 2017-08 (VERIFIED). Many alts listed later. That argues
   for a BTC/ETH-first design and a coin-inception rule.

## Documented effects, ranked for these constraints

| # | Effect | What the literature says | Fits our constraints? |
|---|---|---|---|
| 1 | **Time-series trend / momentum** (long when the coin's own trend is up, else flat) | The strongest crypto result. Time-series momentum is strong while cross-sectional is weak, and costs cut many momentum portfolios to insignificance ([Han, Kang & Ryu, SSRN 4675565](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4675565)). One recent study claims intermediate-frequency trend beats both faster and slower variants after costs, with Sharpe 2.41 for 2022–2024 ([arXiv 2602.11708](https://arxiv.org/abs/2602.11708), REPORTED; the number is unusually high, so treat it skeptically). Bitcoin *intraday* time-series momentum is also documented ([Reading](https://centaur.reading.ac.uk/100181/3/21Sep2021Bitcoin%20Intraday%20Time-Series%20Momentum.R2.pdf)). | ✅ **Best fit.** Long/flat, low turnover, daily horizon. Note the same idea (200-day SMA) failed on US equities in Route 3, but the crypto evidence is much stronger. |
| 2 | **Cross-sectional momentum** (hold recent winners) | Market, size and momentum explain crypto cross-sectional returns ([Liu, Tsyvinski & Wu, J. Finance 2022](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.13119)). The *largest* coins show daily momentum, not reversal ([Int. Rev. Fin. Analysis 2021](https://www.sciencedirect.com/science/article/pii/S1057521921002349)). But Han et al. find cross-sectional momentum weak under realistic assumptions. | 🚧 **Long-only top-N only** (no short leg). Weekly rebalance keeps turnover affordable. Mixed evidence. |
| 3 | **Intraday / weekly seasonality** | Returns cluster in specific hours, e.g. 21:00–23:00 UTC and a "Monday Asia open" effect. BTC's intraday/overnight split flips on NYSE-closed days ([Quantpedia](https://quantpedia.com/are-there-seasonal-intraday-or-overnight-anomalies-in-bitcoin/), [Concretum](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/), [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10015199/), REPORTED). At hourly resolution, day-of-week patterns mostly vanish ([mlquants](https://mlquants.substack.com/p/are-day-of-the-week-effects-in-cryptocurrencies)). | ❌ **Probably cost-killed.** One round trip a day at ~50 bps is the US overnight result again. Worth a *gross-only* look, or as a timing filter for #1, not as a standalone strategy. |
| 4 | **Funding-rate carry** (long spot, short perpetual) | Schmeling, Schrimpf & Todorov's carry has had very high Sharpe since 2020, but it has decayed: lower from 2024 and **negative in 2025** ([arXiv 2510.14435](https://arxiv.org/pdf/2510.14435); [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2096720925000818), REPORTED). | ❌ **Not tradable on Alpaca** (needs perps), and the edge has decayed. Research only. |
| 5 | **Short-term reversal** | Strong across 3,600+ coins, but driven by illiquid coins; large coins show momentum instead ([same 2021 paper](https://www.sciencedirect.com/science/article/pii/S1057521921002349)). There is a small, fast 15-minute mean-reversion signal ([arXiv 2608.21888](https://arxiv.org/html/2608.21888v1)). | ❌ Wrong universe, and too fast for these costs. |
| 6 | **Size premium** | Strong ([Liu et al.](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.13119); [Emerald 2025](https://www.emerald.com/cafr/article/27/4/493/1271913/Unravelling-cross-sectional-patterns-in)) | ❌ Small coins aren't on Alpaca. |
| 7 | **Pairs / cointegration** | Copula and cointegration pair strategies are reported profitable ([Financial Innovation 2024](https://link.springer.com/article/10.1186/s40854-024-00702-7), [SSRN 5128964](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5128964), REPORTED) | ❌ Needs a short leg. Pair studies are also notoriously overfit (INFERRED). |

## Suggested pilot shape (INFERRED; for the preregistration to adopt or change)

- **Primary:** R-C1, time-series trend on each coin (long/flat) at a daily horizon, with 2–3
  lookbacks fixed in advance (not swept).
- **Secondary:** R-C2, long-only top-N cross-sectional momentum with a weekly rebalance.
- **Diagnostic only:** gross hour-of-day and weekday return profile for BTC and ETH, to decide
  whether a timing filter is worth a later, separate preregistration.
- **Benchmarks:** buy-and-hold BTC, and an equal-weight basket of the universe. As in Route 3,
  the question is whether timing beats holding the same average exposure.
- **Costs:** Alpaca taker 25 bps per side plus the measured spread, with a maker-fill (15 bps)
  scenario as sensitivity, not as the base case.
- **Split:** an early window for development and a later window as a sealed holdout (dates to be
  chosen in the preregistration, after checking listing dates, before any returns are computed).
  Crypto regimes (2018 and 2022 bear markets) make the split choice consequential.

# Follow-up Research on Moomoo Data, Vendor Access, and Opening-Microstructure Questions
*Source: ChatGPT Deep Research, 2nd revision, 2026-06-16*

## Bottom line
The highest-confidence result is that Moomoo's accessible public docs and the py-futu-api/OpenD surface clearly separate historical candlesticks from real-time high-frequency feeds: official docs describe historical k-line access and historical candlestick quotas, while the SDK README and quote docs expose get_rt_ticker() as a high-frequency real-time interface alongside get_order_book(), get_rt_data(), and get_broker_queue(). No documented or community-confirmed historical tick-by-tick pull was found in the accessible Moomoo docs, changelog, or SDK-facing materials. Evidence points to "real-time tick yes, historical tick not publicly documented."

For data vendors, Polygon's current public docs are much clearer than Databento's pricing pages in a non-JavaScript environment. Polygon's stock bars docs explicitly say aggregate bars cover pre-market, regular market, and after-hours sessions, with plan matrix: Stocks Starter $29/mo, Developer $79/mo, Advanced $199/mo. Bars: Starter = 15-min delayed + 5yr history, Developer = 15-min delayed + 10yr history, Advanced = real-time + all history. Historical stock trades require Developer+; historical/streaming NBBO quotes require Advanced.

Databento uses usage-based pricing ($/GB), no monthly subscription fee on that path (separate subscription/live-license flow also exists in the portal). Supports equities from 15 exchanges + 30 ATSs, schemas: tick trades, L1, L2, L3, OHLCV, auction imbalance. Exact current flat monthly live-equities price and exact per-GB price for SPY/QQQ/IWM-relevant datasets could not be extracted from static public pages — Databento's own docs point to `metadata.list_unit_prices()` / `metadata.get_cost()` for exact pricing (i.e., cleanest path is programmatic).

## Moomoo historical tick support and futures symbol syntax
- `get_rt_ticker(code)` = real-time tick prints, grouped with other "high-frequency" interfaces (`get_order_book()`, `get_rt_data()`, `get_broker_queue()`). Historical access shown via k-lines only — no historical ticker endpoint found.
- **Treat "Moomoo historical tick" as unverified and not implementation-safe for planning.**
- Futures: `get_future_info(code_list)` documented, fields `code`, `origin_code`, `exchange`, `last_trade_time`. Example uses HK codes (`HK.MPImain`, origin `HK.MPI2112`) — main/current/next-month aliases don't carry `last_trade_time`. Changelog confirms expanded US futures (LV2 depth, `OpenFutureTradeContext()`).
- **Open: exact ES/NQ/RTY symbol strings not verified.** Working theory: same `...main` alias + month-specific origin_code pattern as HK, but exact strings (`US.ESmain`? `US.ES2509`?) unconfirmed.

## Polygon vs Databento for this use case
- **Polygon**: bars endpoint explicitly covers pre/regular/after-hours, ET intervals. For 1-5min extended-hours SPY/QQQ/IWM bars only, Starter ($29) or Developer ($79) suffices depending on history needed. Trades need Developer+; NBBO quotes need Advanced ($199) — that's the tier for slippage/fill modeling or top-of-book work.
- **Databento**: technically sufficient (more than) for premarket bars, tick research, book-based filters, opening-auction work — but pricing not reducible to a single sticker price from static docs; needs programmatic costing.
- **Recommended sequencing**: exhaust Moomoo's own extended-hours/real-time fields first (cheapest, already integrated). If/when historical tick or opening-auction microstructure data is needed, go to a vendor — Polygon if you just want a clean monthly bar bill, Databento if you want the full research ceiling (bars → trades → L1/L2/L3 → imbalance) without switching vendors later.

## Premarket retracement threshold (gap fade filter)
**No sourced universal threshold found** (no "skip if premarket retraced >X%" rule in practitioner or academic sources accessible this pass). Supporting microstructure: opening indicative price is strongly mean-reverting because imbalance itself mean-reverts (auction research) — this is the mechanism that makes "gap already repaired pre-bell" meaningfully different from "gap intact at 9:30," but no specific cutoff is literature-backed.
**Recommendation**: treat any specific threshold (50%, 70%, etc.) as a testable house rule to learn from your own data, not an imported fact. Starter variables to test: % of overnight gap retraced by 9:29 ET, premarket volume ratio vs normal, opening auction imbalance state.

## IWM vs SPY/QQQ at the open
**No direct evidence found** comparing IWM specifically against SPY/QQQ on opening-auction mean-reversion. Nearby supporting evidence: opening auction imbalance mean-reverts (general); short-horizon reversal linked to temporary liquidity imbalance/bid-ask bounce, concentrated in the first hour. IWM small-cap-basket-noisier-open theory remains plausible but unproven — still a hypothesis, not a stylized fact. Suggested test: use a vendor with direct-feed equities + auction imbalance data (Databento) to test IWM vs SPY/QQQ open reversion directly rather than relying on market-cap-tier inference.

## Open questions / unresolved
1. Exact Moomoo/OpenD symbol syntax for ES/NQ/RTY futures.
2. Databento's exact current flat monthly live-equities price and exact per-GB price for SPY/QQQ/IWM datasets (need programmatic `metadata.get_cost()` call to resolve).
3. No sourced practitioner consensus on a universal premarket retracement skip threshold.
4. No direct published comparison proving IWM has stronger opening mean-reversion than SPY/QQQ — mechanism is supported, the specific claim is not.

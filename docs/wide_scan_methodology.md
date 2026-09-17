# Wide-scan universe and cost preregistration

**Frozen: 2026-09-16, before any wide-scan strategy returns were fetched or calculated.**

This document closes the ordering hole between PLAN Steps 3 and 8. A per-symbol cost table cannot
be frozen until the symbols it covers exist, so the universe specification is frozen first. This
does not spend OpenD history quota and does not authorize the bulk fetch.

## Universe

The explicit 97-slot list is `docs/wide_scan_universe.csv`:

- 60 primary ETFs spanning broad US and international equity, sectors and industries, style and
  factors, rates and credit, and real assets;
- 25 primary highly liquid US large/mega-cap single names with sector coverage; and
- 12 ordered reserves, eight ETFs and four single names.

The list is a replication universe, not an investment recommendation or a claim that 97 symbols
are 97 independent observations. Correlated same-day trades will remain in the same bootstrap
block under PLAN Step 4.

### Inclusion rules

1. US-listed instrument with an expected Moomoo code of `US.<ticker>`.
2. Ordinary unlevered ETF or common stock. No inverse/leveraged funds, volatility products, OTC
   instruments, options, or crypto proxies.
3. At least 225 valid daily sessions from 2025-09-17 through 2026-09-15.
4. Median adjusted close at least $5 and median daily dollar volume at least $25 million over that
   window.
5. Coverage is chosen by economic segment before any strategy return is inspected. Duplicate
   index exposures are intentional replication checks across issuers and weighting methods.

If a primary symbol fails availability or the mechanical liquidity screen, replace it with the
first reserve of the same asset class whose segment best preserves coverage. Record the
substitution before fetching five-minute history. Do not replace a symbol because its strategy
result is poor.

The selection is survivorship-biased: symbols were selected for liquidity in 2026 and then will be
tested backward. Results must be described as performance on today's liquid survivors, not as the
historical opportunity set available to a 2019 trader.

## Cost method

Daily bars cannot reveal the true bid/ask spread or passive-limit adverse selection. A trial of the
Corwin-Schultz [high/low estimator](https://doi.org/10.1111/j.1540-6261.2012.01729.x) was rejected
before adoption because it implied roughly 17-33
bps monthly-median spreads for SPY/QQQ/IWM over the frozen window, far outside both their quoted
spread regime and this project's existing 1.5/1.5/2.5-bps all-in assumptions. The estimator is
useful in many low-frequency settings, but it is not credible here as a literal cost for highly
liquid ETFs. The rejected check did not inspect strategy returns.

The adopted value is explicitly a conservative **heuristic hurdle**, not an observed spread:

```text
tick_bps       = 100 / median_adjusted_close
liquidity_bps  = max(0, sqrt($5bn / median_daily_dollar_volume) - 0.40)
raw_bps        = 1.25 + tick_bps + liquidity_bps
round_trip_bps = raw_bps rounded upward to the next 0.5 bps, clamped to [1.5, 12.0]
```

The $0.01 tick term makes lower-priced instruments more expensive. The inverse-dollar-volume term
makes less liquid instruments more expensive without assigning a cost merely because a symbol is
a stock rather than an ETF. The common 1.25-bps buffer covers passive-fill adverse selection,
slippage, and optimistic bar-path assumptions. The coefficients were fixed while looking only at
market-data inputs and the project's existing SPY/QQQ/IWM cost anchors; they were not fit to PnL.

`scripts/build_wide_scan_costs.py` downloads adjusted daily close and volume from Yahoo Finance and
writes every input and component to `docs/wide_scan_cost_inputs.csv`. It never reads strategy data
or calls OpenD. The CSV is the audit record; `mm/wide_scan_cost_table.py` is the generated table
and `mm/costs.py` remains the runtime interface. Costs are frozen for the first wide scan.
Sensitivity output at 0/1/2/5 bps remains available, but only the frozen per-symbol values decide
the primary net gate.

## Falsifiable comparison

The prior wording predicted that single names would look worse after assigning them a larger flat
haircut. That was circular. The preregistered comparison is now:

> Compare ETF and single-name **gross bps**, frozen modeled cost bps, and residual net bps
> separately. The claim that single names are less suitable survives only if their gross return
> deficit exceeds the cost differential assigned by the frozen model. If gross performance is
> comparable and only the modeled haircut creates a gap, report a cost-model result rather than a
> strategy result.

No asset-class conclusion may be based only on pooled trade count. Report symbol medians and a
day-blocked interval, and retain every included symbol whether its outcome is good or bad.

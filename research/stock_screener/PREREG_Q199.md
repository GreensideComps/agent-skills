# Q199 pre-registration: the system's own stock screener, "pick-1" (3 Nov 2026, 08:40Z)

Owner request 3 Nov 2026 08:22Z (cmsg_01U4KMvkBYNknqm4HRVie8uvLAYHVczU5Z4wDrEM5PNsD1): the system should pick
individual stocks from a screener it designs. Written before any pick-1 score or return was computed.

## Screen (one config, one trial)
Universe each January (decision month = December month-end data, PIT via monthly_metrics `last_filed`):
US filers in prices_monthly, market cap >= $2bn (large + mid), close >= $5, excluding SIC 6000-6799
(financials, where FCF and debt are not comparable) and SIC 4900-4999 (utilities).

Gates (all must hold):
1. TTM free cash flow (ocf - capex) > 0 and TTM operating income > 0.
2. Net debt / EBITDA < 3, where EBITDA = TTM operating income + D&A (net cash passes).
3. Shares outstanding up no more than 2% vs 12 months earlier (no heavy dilution).
4. Equity > 0.

Rank: equal-weight mean of cross-sectional z-scores (clipped +-3) within the gated universe of
- quality: TTM gross profit / total assets
- value: TTM FCF / enterprise value (mcap + debt - cash)
- trend: 12-1 month price return (months t-12..t-1, skip the latest month)

Hold the top 15 by score, max 3 names per 2-digit SIC, equal weight, buy-and-hold 12 months, rebalance
each January. Cost 0.30% one way on turnover (xsection.COST_PER_TURNOVER: 0.15% FX + 0.15% spread).

## Period and benchmarks
Exploration only: decisions Dec 2014 .. Dec 2021, outcomes Jan 2015 .. Dec 2022 (96 months). No 2023+ data.
- B1 (selection skill, main stat): excess vs the equal-weight gated+ungated universe (all names passing the
  size/price/sector filters). Survivor bias affects both sides.
- B2 (what the owner cares about): excess vs VWRL/VWRP in GBP (stock returns converted from USD with
  gbpusd daily, month-end). Survivor bias favours the screen here; stated, not corrected.

## Tests (robustness views of the one config, not new hunting)
T2 thirds, T3 bull/bear (universe vs its 10-month average), T4 faster (rebalance every 6 months),
T5 second universe (large caps >= $10bn only), T6 costs x2 and one-month lag (February rebalance).

## Pass rule (standing LOOP.md rule)
DSR > 0.95 at current N on B1, 2 of 3 thirds positive, costs x2 > 0, lag > 0, trade-level gross
average > cost. Additionally B2 mean excess > 0.

## What happens either way
Pass: send the office thread a demo tag `stock_screen` (2%/name, 30-trade kill rule) with live picks.
Fail: the screen still goes to the demo as a LOW-CONFIDENCE forward test because the owner explicitly
asked for live individual picks; this is recorded here BEFORE the result so the decision cannot depend on
it. Same 2%/name sizing, max 15 names, same 30-closed-trade / 730-day kill rule vs VWRP. It counts in
scoreboard REGISTERED (raises go-live k by 1).

# Pre-registration: does the Master Stock Screener's score predict returns? (M8, test 1)

Written and committed **before** any backtest result was computed. Single test; trial count 1.

## Hypothesis
Among US-listed industrial companies that file with the SEC, a higher `screen-1.0` total score at a decision
date is followed by a higher 12-month total return. Rationale: the score rewards FCF per share growth, quality
(ROIC, margins, cash conversion), cheapness (FCF and EBIT yield) and low dilution and leverage, all of which have
published evidence as return predictors (profitability, value, net share issuance). The other side: investors who
extrapolate recent growth or prefer stories over cash flows.

## Frozen method
- Score: `equity/config/screener.json` exactly as committed (git blob `e1c30aa667c3101dc7043095814a5b2233f689ad`), via `screener.score_company`.
  No weight, scale or gate is changed for this test.
- Point in time: every XBRL fact is kept only if its `filed` date is on or before the decision date, then the
  normal `fundamentals.analyse(facts, today=decision date)` runs. Restated values are therefore seen as they were
  first known. Shares outstanding come from cover pages filed by then.
- Prices: Yahoo chart monthly bars (unofficial, free). Market cap uses the unadjusted close at the decision date
  (split-adjusted close times the splits that happened later) times point-in-time shares. Returns use the
  dividend-adjusted close (total return).
- Decision dates: the April month-end close of each year 2012-2025; the holding period runs to the next April
  month-end close. The 2025 cohort ends at April 2026.
- Universe: a random sample of 600 companies (seed 7) from the 5,472 companies the security master links to SEC
  with high confidence. Companies need a USD price at the decision date to count.
- Benchmark: SPY total return over the same windows, and the equal-weighted mean of all scored companies.

## Measures and pass condition
1. Information coefficient (IC): the Spearman rank correlation, each year, between the total score and the forward
   return, over companies with a total score. Report the mean IC and its t-statistic across years.
2. Ranked basket: equal-weighted forward return of companies passing every gate (as the live screen ranks them),
   minus the equal-weighted return of all scored companies, per year.
3. Top quintile minus bottom quintile of total score, per year.

**Pass:** mean IC > 0 with t >= 2, **and** the ranked basket beats all scored companies in at least 60% of years.
Anything else reads as "no evidence the score adds information over the universe". In that case the weights do not
change automatically; changing screen methodology is the owner's decision.

## Known biases, stated in advance
- **Survivorship:** the universe is companies listed on Trading 212 today. Companies that went bust or were
  delisted are missing, so absolute returns are overstated. The cross-sectional tests (1-3) are less affected,
  but the losing tail is truncated, which can bias the IC either way.
- Small cross-sections in early years, because XBRL coverage starts around 2009-2011.
- No trading costs: annual rebalancing makes them small relative to the effects tested.
- Yahoo prices are unofficial. A company with a missing or non-USD price is dropped for that year, not imputed.

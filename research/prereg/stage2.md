# Stage 2 pre-registration: cross-sectional signal tests

Written and committed 2026-10-14, **before any Stage 2 result was computed**. The code that implements it
is `research/stage2.py` at the same commit. Git history is the proof of order.

## Question

For US large caps (point-in-time market cap over $10bn), does each signal rank next-month returns well enough to
improve stock selection after Trading 212 costs? Each signal is tested alone. Nothing is combined in Stage 2.

## Data and window

- Dataset: Stage 1 (`python -m equity research-data`). Fundamentals are as filed on or before each month-end.
  Prices come from Yahoo monthly. The market cap is cover-page shares × the raw close.
- Decisions run monthly from 2015-01 to 2022-11; the outcome is the following month's total return.
- **Holdout:** 2023-01 to 2026-09 is not read by any Stage 2 computation. It is used once, after a combined
  model is frozen (STRATEGY_V2 §2.2).
- **Universe each month:** filing within 15 months, price ≥ $1, a next-month return, and a market cap band.
  Large caps (≥ $10bn) decide pass or fail. Mid and small caps are reported for information.
- **Known bias:** survivorship on the price side (Stage 1 report). It is stated on every result.

## Trials (11; every one is counted in the deflated Sharpe)

| Id | Family | Definition | Higher is better |
|---|---|---|---|
| S1a | Valuation | (TTM operating cash flow − TTM capex) / market cap. Ranked within SIC group. Financials excluded. | yes |
| S1b | Valuation | TTM operating income / EV. EV = market cap + debt − cash and short-term investments, and must be > 0. Ranked within SIC group. Financials excluded. | yes |
| S2a | Quality | Gross profit / total assets. Ranked within SIC group. Financials excluded. | yes |
| S2b | Quality | −(TTM net income − TTM operating cash flow) / total assets. Financials excluded. | yes |
| S3a | Fundamental momentum | TTM revenue / TTM revenue 12 months earlier − 1 | yes |
| S3b | Fundamental momentum | S3a now − S3a three months earlier | yes |
| S4 | Earnings surprise | Change in TTM diluted EPS when a new quarter arrives (the new quarter minus the same quarter a year earlier), ÷ the standard deviation of the company's previous changes (36 months, at least 6). Only within 75 days of the period end. | yes |
| S5a | Capital allocation | −[log(market cap ÷ cap 12 months earlier) − log(total-return price ÷ 12 months earlier)]: net issuance, split-proof. Dividends bias it by about the yield. | yes |
| S5b | Capital allocation | −(total assets ÷ total assets 12 months earlier − 1) | yes |
| S6a | Price momentum | Total-return price one month ago ÷ 12 months ago − 1 | yes |
| S6b | Price momentum | Total-return price ÷ its maximum over the last 12 month-ends | yes |

**SIC groups (14):**
- agriculture
- mining and energy
- construction
- chemicals and pharma
- computers (3570–3579)
- electronics and semis (3600–3699)
- instruments and medtech (3800–3899)
- other manufacturing
- transport, utilities and telecom
- trade and retail
- finance (6000–6799)
- software and IT (7370–7379)
- other services
- other

Codes are matched in that order, so a specific range wins over "other manufacturing".

**Not run in Stage 2:**
- S6c residual momentum, which needs per-stock factor betas.
- S7 insider buying, which needs Form 4 data built first.
- S8 estimate revisions, which needs paid data.
- S9 expectations gap, which needs the Stage 3 engine.

Each of these gets its own pre-registration later and adds to the trial count.

## Measurements

- **Information coefficient:** monthly Spearman IC between the score and next-month return, with a Newey-West
  t-statistic (3 lags).
- **Spread and top quintile:** top-minus-bottom decile return, and the equal-weighted top quintile minus the
  universe.
- **Costs:** turnover-based, at 0.30% one way (0.15% FX plus about 0.15% spread), charged on top-quintile turnover
  in and out.
- **Deflated Sharpe:** Bailey and López de Prado (2014). It is computed on the monthly top-quintile-minus-universe
  return after costs, across all 11 trials.
- **For information only, not part of the pass rules:**
  - Fama-French five-factor plus momentum alpha, with a Newey-West t-statistic.
  - IC in up and down market months.
  - IC by sub-period third.
  - IC by sector group.

## Pass rules (from STRATEGY_V2 §2.2, unchanged)

**Pass** requires all of:
1. A large-cap IC t-statistic ≥ 2.
2. A deflated Sharpe ≥ 0.9.
3. The top quintile beats the universe after costs in at least 2 of 3 sub-periods.
4. The top quintile is still positive after costs at three times the cost assumption.

**Fail:** mean IC ≤ 0, or IC t < 1. **Inconclusive:** everything else.

A pass makes the signal evidence tier E3 for large caps only, and it may then enter the Stage 3 combination.
A fail or an inconclusive result keeps it at E1 or E0, so it does not drive rankings. Zero passes is an
acceptable, reportable outcome. In that case the kill rule in STRATEGY_V2 §2.5 applies.

## What changes count as new trials

Any of these counts as a new trial:
- a different definition, lag, window or neutralisation;
- a different universe filter or cost assumption;
- running on mid or small caps as the deciding band.

A new trial gets an id, is added to `TRIALS` in `stage2.py` with its date, and raises the count used by
the deflated Sharpe. Bug fixes that change no definition are noted in the results file with the commit.

## Addendum 1: S6c and S7 (written 2026-10-14, after the first 11 ran, before these three ran)

These are three new trials, which brings the trial count to 14. The deflated Sharpe for every trial is
recomputed with 14. The window, universe, costs and pass rules are unchanged.

| Id | Family | Definition | Higher is better |
|---|---|---|---|
| S6c | Price momentum | Residual momentum. Regress monthly excess returns on Fama-French Mkt-RF, SMB and HML over months t−36 to t−2, needing at least 24 months. The score is the mean residual over t−12 to t−2 divided by its standard deviation, needing at least 9 of the 11 months. | yes |
| S7a | Insider behaviour | Count distinct officers and directors with open-market purchases (Form 4, code P) and with open-market sales (code S), filed in months t−5 to t. The score is (buyers − sellers) / (buyers + sellers). Unscored when nobody traded. | yes |
| S7b | Insider behaviour | Value of officer and director open-market purchases filed in months t−5 to t, divided by market cap. Zero when there were none. | yes |

**Data:** SEC Form 3/4/5 quarterly data sets for 2014q1 to 2022q4, from
`python -m equity`'s `insiders.build`. Dated by filing date. Amendments (4/A) count as filings.

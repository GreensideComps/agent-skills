# Execution-price dataset integrity (edge-discovery Phase B, step B1)

First-trading-day closes for the next-day execution convention, decisions 2009-12 to 2022-11, cut at 2022-12-31 at the download itself. FAIL = do not use; WARN = a limitation to state.

| Check | Status | Detail |
|---|---|---|
| one row per company-month | **PASS** | 0 duplicate (cik, month) rows |
| strict cutoff: no date after 2022-12-31 | **PASS** | 0 dates after the cutoff; last decision month 2022-11-30 |
| execution date is the first US trading day after the month-end | **PASS** | 0 rows differ from the calendar; 0 not after the decision |
| decision close is on or before the month-end | **PASS** | 0 rows after |
| usable rows have positive prices | **PASS** | 0 'ok' rows with a missing or non-positive price |
| row status | **WARN** | invalid_price 314, missing_exec 11, ok 482,028, stale_month_end 4 |
| overnight moves over 50% (decision close to execution close) | **WARN** | 1299 of 482,028; median absolute move 1.265% |
| coverage of the research dataset's USD company-months | **PASS** | 452,334 of 453,181 (99.8%) have an 'ok' execution row |
| month-end returns agree with the research dataset (within 0.1 points) | **PASS** | 100.00% of 447,969 monthly returns agree |
| FX: positive, cut at 2022-12, source recorded | **PASS** | 3,430 days to 2022-12-30; Yahoo:GBPUSD=X 3,430 |
| FX: a rate within 7 days of every decision month-end | **PASS** | 0 months without |
| benchmarks: cut at 2022-12, positive | **PASS** | to 2022-12-30; first values VWRP 2019-07-25, VWRL 2012-05-22 |

## Files

| File | Rows | SHA-256 |
|---|---:|---|
| exec_prices_to_2022.csv.gz | 482,357 | `dd6608f62ae2676f…` |
| gbpusd_daily_to_2022.csv.gz | 3,430 | `fd9f8e7dc9214657…` |
| benchmarks_daily_gbp_to_2022.csv.gz | 2,681 | `0ec17f8631a17cc6…` |

Built 2026-10-15T09:04:00+00:00 from Yahoo chart (daily) and FRED; 5 of 4374 tickers returned no data.

Prices are for returns only: Yahoo adjusts history for splits and dividends known today. Survivorship bias is unchanged by this file (`edge_rules.STANDING_LIMITATIONS`).

# Execution-price dataset integrity (edge-discovery Phase B, step B1)

> **Survivorship (material, unbounded; added 2026-10-16 at the owner's request):** companies that delisted before the 2026 price download are missing from the universe entirely. The -30% and -100% missing-price rules do not address them and are not evidence that survivorship bias is bounded.

First-trading-day closes for the next-day execution convention, decisions 2009-12 to 2022-11, cut at 2022-12-31 at the download itself. FAIL = do not use; WARN = a limitation to state.

| Check | Status | Detail |
|---|---|---|
| one row per company-month | **PASS** | 0 duplicate (cik, month) rows |
| strict cutoff: no date after 2022-12-31 | **PASS** | 0 dates after the cutoff; last decision month 2022-11-30 |
| execution date is the first US trading day after the month-end | **PASS** | 0 rows differ from the calendar; 0 not after the decision |
| decision close is on or before the month-end | **PASS** | 0 rows after |
| usable rows have positive prices | **PASS** | 0 'ok' rows with a missing or non-positive price |
| row status | **WARN** | invalid_price 314, missing_exec 11, ok 482,028, stale_month_end 4 |
| overnight moves over 50% (decision close to execution close) | **WARN** | 1341 of 482,028; median absolute move 1.265% |
| coverage of the research dataset's USD company-months | **PASS** | 452,334 of 453,181 (99.8%) have an 'ok' execution row |
| month-end returns agree with the research dataset (within 0.1 points) | **PASS** | 100.00% of 447,969 monthly returns agree |
| FX: positive, cut at 2022-12, source recorded | **PASS** | 3,430 days to 2022-12-30; Yahoo:GBPUSD=X 3,430 |
| FX: a rate within 7 days of every decision month-end | **PASS** | 0 months without |
| benchmarks: cut at 2022-12, positive | **PASS** | to 2022-12-30; first values VWRP 2019-07-25, VWRL 2012-05-22 |

## Files

| File | Rows | SHA-256 |
|---|---:|---|
| exec_prices_to_2022.csv.gz | 482,357 | `dd6608f62ae2676fd4fd5b3b256105d5f52eb720ba3a10a2965cf504e17d47dc` |
| gbpusd_daily_to_2022.csv.gz | 3,430 | `fd9f8e7dc921465732460a507225778ea9d14437dfd5026f4b37f3dd54310d65` |
| benchmarks_daily_gbp_to_2022.csv.gz | 2,681 | `0ec17f8631a17cc6f7cc3ca7e1f8054437371e2012739926d4ccfffa0b1f6fc6` |
| nyse_calendar_to_2022.csv.gz | 3,314 | `58bde006e5b9685efaca2d481578764048dd7fb0388ffa1b8cc6e89bf13465db` |

Built 2026-10-15T09:04:00+00:00; 5 of 4374 tickers returned no data.

## Provenance

| Item | Source |
|---|---|
| exec_prices_to_2022.csv.gz | Yahoo Finance chart API v8, daily close and adjclose, first SEC ticker per company; requests ended at 2022-12-31 (Yahoo period2 = 2023-01-01T00:00Z, FRED coed = 2022-12-31) |
| nyse_calendar_to_2022.csv.gz | Yahoo Finance chart API v8, SPY trading days; requests ended at 2022-12-31 (Yahoo period2 = 2023-01-01T00:00Z, FRED coed = 2022-12-31) |
| benchmarks_daily_gbp_to_2022.csv.gz | Yahoo Finance chart API v8, VWRP.L and VWRL.L adjclose, currency as reported by Yahoo (GBP); requests ended at 2022-12-31 (Yahoo period2 = 2023-01-01T00:00Z, FRED coed = 2022-12-31) |
| gbpusd_daily_to_2022.csv.gz | FRED DEXUSUK first, Yahoo GBPUSD=X close where FRED has no value; source per day in column `source`; requests ended at 2022-12-31 (Yahoo period2 = 2023-01-01T00:00Z, FRED coed = 2022-12-31) |
| fred_status | not recorded at build; the stored FX file has 0 FRED days, so FRED supplied nothing |
| fx_days_by_source | {'Yahoo:GBPUSD=X': 3430} |
| fred_retry | 2026-10-15T12:52:10+00:00: FRED retried and failed (RuntimeError: failed to fetch https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXUSUK&cosd=2009-11-01&coed=2022-12-31: Remote end closed connection without response). Stored FX file unchanged. |

2026-10-15T12:52:14+00:00: annotate: provenance, calendar file, checks rerun on the stored files; data files unchanged (hashes verified).

Prices are for returns only: Yahoo adjusts history for splits and dividends known today. Survivorship bias is unchanged by this file (`edge_rules.STANDING_LIMITATIONS`).

# Research dataset integrity (edge-discovery Phase A)

Read-only checks. FAIL = a defect to fix before trusting results; WARN = a known limitation results must state. Returns are inspected only up to 2022-12.

| Check | Status | Detail |
|---|---|---|
| metrics: one row per company-month | **PASS** | 0 duplicate (cik, month) rows |
| metrics: months are month-ends | **PASS** | every month value is a calendar month-end |
| metrics: point in time (last filing on or before the month) | **PASS** | 0 rows use a filing dated after their month |
| metrics: TTM period ends on or before the month | **WARN** | 106 rows (15 companies) report a period ending after the month, though filed before it: mis-tagged XBRL period dates, not look-ahead |
| metrics: no negative share counts | **WARN** | 4 rows |
| prices: one USD row per company-month | **PASS** | 0 duplicates (xsection.load keeps the last) |
| prices: one ticker per company | **WARN** | 5,360 companies priced, 0 with more than one ticker. Each company is priced from the first ticker in today's SEC list (equity/monthly.py), so other share classes are ignored and a ticker since reused by another company can be mis-linked. |
| prices: non-USD rows excluded from tests | **WARN** | 0.0% of price rows are not USD |
| prices: positive prices | **FAIL** | 344 rows with a price <= 0 |
| prices: monthly moves over 100% (to 2022-12) | **WARN** | 3,864 of 453,156 monthly returns; largest +166666659944%, smallest -441%. Review before trusting small-cap results; large caps rarely move this much. |
| universe: share-count outliers in the large band (2015-01..2022-11) | **WARN** | 283 of 43,220 large-cap company-months (53 companies) have a share count over 10x or under 1/10 of the company's median, e.g. 1.9e14 shares. Most are XBRL scaling errors that inflate market cap and put a small company in the large band. |
| universe: negative adjusted prices in the large band (2015-01..2022-11) | **FAIL** | 4 large-cap company-months have an adjusted close <= 0 (a Yahoo adjustment error), so their returns are wrong |
| companies: SIC code is today's, not point in time | **WARN** | 17,489 companies have one SIC from today's SEC submissions. Sector-neutral signals and sector caps use today's industry, a mild look-ahead. |
| insiders: Form 4 data covers the holdout | **WARN** | filings 2014-01-02 to 2022-12-30. A confirmation run of any insider signal needs 2023-2026 quarters built first (`python -m equity research-data --step insiders`). |
| holdout: rows exist for a later confirmation run (counted, not read) | **PASS** | 346,024 metric rows and 213,349 price rows in 2023-01..2026-09 |

## Manifest

Results are reproducible only against these exact files; the monthly signal log rebuilds them.

| File | Rows | Months | SHA-256 (first 16) |
|---|---:|---|---|
| sec_facts_panel.csv.gz | 12,768,511 |  to  | `2a56736fdea78254` |
| sec_companies.csv.gz | 20,458 |  to  | `acf5e3f746c355aa` |
| monthly_metrics.csv.gz | 1,440,013 | 2009-12-31 to 2026-09-30 | `ae5429b661bd060d` |
| prices_monthly.csv.gz | 676,241 | 2011-01-31 to 2026-10-31 | `505115711f7ef59c` |
| insider_trades.csv.gz | 920,082 | 2014-01-02 to 2022-12-30 | `82e99ff117d2ec0c` |

# Research dataset integrity (edge-discovery Phase A)

Read-only checks. FAIL = a defect to fix before trusting results; WARN = a known limitation results must state. Returns are inspected only up to 2022-12.

Two kinds of check. **Source** checks describe the data files: a FAIL there is a defect in the data, which the programme may already neutralise. **Programme** checks ask whether a defect can still reach a programme result: a FAIL there means programme results cannot be trusted. The script exits 1 only on a programme FAIL.

## Programme exposure

| Check | Status | Detail |
|---|---|---|
| programme: quality flags computed without 2023-26 data | **PASS** | flags use the share-count median of 2022-12 and earlier only. Computed on the whole dataset, 626 banded company-months up to 2022-12 would have been flagged differently; the Phase A draft did that in its report, fixed on 2026-10-14 (exploration never used the exclusion before the fix). |
| programme: no return starts or ends on a price <= 0 | **PASS** | 302 month-to-month returns to 2022-12 touch a price <= 0 (CBIO, CODQL, DEC, LIANY, NFE, VATE); 4 of them cross the sign change and would be nonsense (a ratio of a positive and a negative price). `edge_split.forward_return` treats such prices as missing: 0 reach a programme return. |
| programme: company-months with a price <= 0 are never eligible | **PASS** | 263 such company-months to 2022-12 (4 in the large band) are flagged `bad_price`, so `quality_ok` is False; 0 would be eligible. A holding whose next price is invalid is treated as a missing price (`edge_rules.holding_return`). |

## Source data

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
| prices: no row labelled after the fetch date | **WARN** | 5,334 rows labelled 2026-10-31 in a file fetched 2026-10-14. The builder labels the unfinished month with its month-end, so these rows hold the price on the fetch date, not a month-end close. Not future data, but not a monthly return either: `edge_split.complete_months` drops them. Exploration (to 2022-12) and the holdout (to 2026-09) never reach them; the signal log only scores a month once it has ended. |
| prices: positive prices | **FAIL** | 344 rows with a price <= 0 |
| prices: monthly moves over 100% (to 2022-12) | **WARN** | 3,864 of 453,156 monthly returns; largest +166666659944%, smallest -441%. Review before trusting small-cap results; large caps rarely move this much. |
| universe: share-count outliers in the large band (2015-01..2022-11) | **WARN** | 253 of 43,220 large-cap company-months (53 companies) have a share count over 10x or under 1/10 of the company's median, e.g. 1.9e14 shares. Most are XBRL scaling errors that inflate market cap and put a small company in the large band. |
| universe: negative adjusted prices in the large band (2015-01..2022-11) | **FAIL** | 4 large-cap company-months have an adjusted close <= 0 (a Yahoo adjustment error: NFE's adjusted close is negative from 2019-01 to 2022-12). Stage 2 included them unchanged. Programme exposure: see the programme checks. |
| companies: SIC code is today's, not point in time | **WARN** | 17,489 companies have one SIC from today's SEC submissions. Sector-neutral signals and sector caps use today's industry, a mild look-ahead. |
| insiders: Form 4 data covers the holdout | **WARN** | filings 2014-01-02 to 2022-12-30. A confirmation run of any insider signal needs 2023-2026 quarters built first (`python -m equity research-data --step insiders`). |
| holdout: rows exist for a later confirmation run (counted, not read) | **PASS** | 346,024 metric rows and 213,349 price rows in 2023-01..2026-09 |

## Manifest

Results are reproducible only against these exact files; the monthly signal log rebuilds them.

| File | Rows | Months | Modified (UTC) | SHA-256 (first 16) |
|---|---:|---|---|---|
| sec_facts_panel.csv.gz | 12,768,511 |  to  | 2026-10-14T15:55:30+00:00 | `2a56736fdea78254` |
| sec_companies.csv.gz | 20,458 |  to  | 2026-10-14T15:55:25+00:00 | `acf5e3f746c355aa` |
| monthly_metrics.csv.gz | 1,440,013 | 2009-12-31 to 2026-09-30 | 2026-10-14T15:55:26+00:00 | `ae5429b661bd060d` |
| prices_monthly.csv.gz | 676,241 | 2011-01-31 to 2026-10-31 | 2026-10-14T16:23:57+00:00 | `505115711f7ef59c` |
| insider_trades.csv.gz | 920,082 | 2014-01-02 to 2022-12-30 | 2026-10-14T16:34:33+00:00 | `82e99ff117d2ec0c` |

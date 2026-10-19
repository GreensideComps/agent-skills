# B5 share-count point-in-time audit (2026-10-19)

No return, score, ranking or NAV computed. Each sampled company-month was rebuilt by `equity.monthly.company_months` from SEC fact rows filed on or before that month-end only, and compared with the stored `monthly_metrics.csv.gz` value used by identity rule C.

Rows: 4,878 ({'random': 3000, 'ratio>25': 1878}), companies: 816, rebuilt: 4,878.

| Field | Match | Mismatch | Rows where a later filing would give a different value |
|---|---:|---:|---:|
| `shares_out` | 4,878 | 0 | 756 |
| `shares_diluted` | 4,878 | 0 | 2,523 |
| `total_assets` | 4,878 | 0 | 3,022 |

The last column counts rows where allowing filings up to 2022-12-31 (for periods ending by the month) would change the value: the leak exists in the data, and the stored values do not take it.

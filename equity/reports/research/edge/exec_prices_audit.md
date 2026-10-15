# B1 execution prices: audit requested on 2026-10-15

Read-only; data to 2022-12-31 only. No signal or strategy return is computed.

## 1. Overnight moves over 50% (decision close to execution close)

1,341 usable rows of 482,028. Classes: `split_like` and `reversal` (and `extreme`) are probable data errors; `penny` rows (decision close under $1) are outside the universe; `plausible` moves are kept as genuine.

| Band | Quality ok | split_like | extreme | reversal | penny | plausible | Total |
|---|---|---:|---:|---:|---:|---:|---:|
| large | yes | 2 | 1 | 0 | 0 | 0 | 3 |
| mid | yes | 2 | 0 | 2 | 1 | 2 | 7 |
| small | no | 2 | 0 | 1 | 1 | 1 | 5 |
| small | yes | 2 | 0 | 3 | 0 | 12 | 17 |
| unbanded | n/a | 147 | 10 | 92 | 221 | 95 | 565 |
| unbanded | no | 28 | 3 | 18 | 52 | 7 | 108 |
| unbanded | yes | 115 | 9 | 120 | 310 | 82 | 636 |
| **all** | | 298 | 23 | 236 | 585 | 199 | 1341 |

In the programme's eligible universe (banded, quality ok): 27 rows; 12 probable data errors, 14 plausible, 1 penny.

Large and mid band rows, all listed:

| Ticker | Decision month | Band | Ratio | Next month-end vs decision | Class |
|---|---|---|---:|---:|---|
| ATLX | 2015-01-31 | large | 2.000 | +0.0% | split_like |
| ATLX | 2015-04-30 | large | 2.000 | +0.0% | split_like |
| ATXG | 2022-08-31 | large | 0.046 | -99.6% | extreme |
| BTCS | 2012-12-31 | mid | 2.000 | +100.0% | split_like |
| POSC | 2015-04-30 | mid | 1.750 | +100.0% | penny |
| LXRX | 2015-07-31 | mid | 1.611 | +41.5% | plausible |
| LVO | 2017-10-31 | mid | 0.333 | -66.7% | split_like |
| PPCB | 2018-08-31 | mid | 2.333 | +9.0% | reversal |
| MYGN | 2019-07-31 | mid | 1.545 | -19.3% | reversal |
| ADT | 2020-07-31 | mid | 1.566 | +23.7% | plausible |

Largest 10 absolute moves (all bands):

| Ticker | Decision month | Band | Ratio | Class |
|---|---|---|---:|---|
| WYGC | 2017-02-28 | unbanded | 1.34e+04 | extreme |
| ESSI | 2019-02-28 | unbanded | 0.000455 | extreme |
| LGVT | 2021-10-31 | unbanded | 0.00111 | extreme |
| BIXT | 2020-04-30 | unbanded | 0.012 | extreme |
| MLMC | 2015-09-30 | unbanded | 0.0153 | extreme |
| BIXT | 2020-07-31 | unbanded | 0.0214 | extreme |
| APSI | 2019-08-31 | unbanded | 42 | extreme |
| RAKR | 2016-02-29 | unbanded | 0.03 | extreme |
| GBUX | 2021-12-31 | unbanded | 27.9 | extreme |
| SRXH | 2014-10-31 | unbanded | 27.1 | extreme |

## 2. Coverage

Share of the research dataset's USD company-months (decisions 2009-12 to 2022-11) with a usable ('ok') execution row, by eligibility group:

| Band | Quality ok | Company-months | ok | missing_exec | invalid_price | stale_month_end | absent | Coverage |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| large | no | 588 | 584 | 0 | 4 | 0 | 0 | 99.32% |
| large | yes | 55,991 | 55,941 | 0 | 0 | 0 | 50 | 99.91% |
| mid | no | 293 | 269 | 0 | 24 | 0 | 0 | 91.81% |
| mid | yes | 83,030 | 83,005 | 0 | 0 | 0 | 25 | 99.97% |
| small | no | 557 | 529 | 0 | 28 | 0 | 0 | 94.97% |
| small | yes | 100,858 | 100,757 | 3 | 0 | 2 | 96 | 99.90% |
| unbanded | n/a | 53,931 | 53,816 | 3 | 40 | 2 | 70 | 99.79% |
| unbanded | no | 5,782 | 5,576 | 1 | 205 | 0 | 0 | 96.44% |
| unbanded | yes | 152,151 | 151,857 | 4 | 0 | 0 | 290 | 99.81% |

By month, eligible universe (banded, quality ok): minimum 99.79% (2022-09-30), median 99.93%; 0 of 143 months below 99%. Full table: `exec_prices_audit_coverage_by_month.csv`.

Large band, quality ok: minimum 99.58% (2012-04-30), 50 of 143 months below 100%.

## 3. Benchmark dates

| Series | First price | First month-end close | First full monthly return | First execution-date price |
|---|---|---|---|---|
| VWRP | 2019-07-25 | 2019-07-31 | 2019-08 | 2019-08-01 |
| VWRL | 2012-05-22 | 2012-05-31 | 2012-06 | 2012-06-01 |

VWRP's first price is 25 July 2019 and its first month-end close is 31 July 2019, so its first full monthly return is **August 2019** (31 July to 30 August). Earlier documents said September 2019; that was one month late and is corrected. On the backtester's execution dates the first VWRP period starts on 1 August 2019 (the first trading day after the July decision).

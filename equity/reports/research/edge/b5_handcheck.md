# B5 hand-check: real-data implementation (placebo score)

**Standing limitations (not solved by anything in this report):**

1. **Survivorship bias (material, unbounded).** Companies that stopped trading before the 2026 price download have no
   free prices, so they are missing from the universe entirely, even in the years they traded. The bias is of unknown
   size and is usually assumed to flatter results. The -30% and -100% missing-price rules apply only to companies
   that are in the data and later lose a price; **they do not address companies missing from the universe, and are
   not evidence that survivorship bias is bounded.** Accepted for exploration only (D13).
2. **Missing prices are indistinguishable.** Delistings, acquisitions and ticker changes all get the same
   conservative mark-down.
3. **The 2023-2026 holdout is partly seen**, so a holdout pass is weaker than a clean out-of-sample test.
4. **One ticker per company, today's SIC codes, unofficial free prices (Yahoo).**
5. **Benchmark:** actual VWRP only from 2019-08 (first full monthly return; first price 25 July 2019); VWRL (its distributing twin) before that.

Run 2026-10-16T12:37:14+00:00. Registry id `B5-HANDCHECK` (diagnostic, not counted). **Placebo score only:** no H1 or S2a score, ranking, return or NAV was computed. Inputs cut at 2022-12-31 on read.

## Verdict: **PASS**

### 1. Engine vs independent recomputation, every month of every tranche

| Configuration and tranche start | Months | Max NAV diff (USD, GBP) | Holdings equal | Max turnover diff | Max cost diff | Missing-price exits (equal) | Benchmark labels equal | Max benchmark diff | Last date | Pass |
|---|---:|---|---|---:|---:|---|---|---:|---|---|
| quarterly (H1 rules) | 2014-11-30 | 97 | 2.7e-15, 3.1e-15 | True | 6.9e-17 | 4.3e-19 | 0 (True) | True | 0.0e+00 | 2022-12-01 | True |
| quarterly (H1 rules) | 2014-12-31 | 96 | 4.4e-15, 5.3e-15 | True | 5.6e-17 | 2.4e-19 | 0 (True) | True | 0.0e+00 | 2022-12-01 | True |
| quarterly (H1 rules) | 2015-01-31 | 95 | 1.6e-15, 1.8e-15 | True | 6.9e-17 | 4.3e-19 | 0 (True) | True | 0.0e+00 | 2022-12-01 | True |
| 12-month (S2a rules) | 2014-02-28 | 106 | 3.6e-15, 4.4e-15 | True | 5.6e-17 | 2.2e-19 | 0 (True) | True | 0.0e+00 | 2022-12-01 | True |
| 12-month (S2a rules) | 2014-03-31 | 105 | 1.8e-15, 2.2e-15 | True | 6.9e-17 | 4.3e-19 | 0 (True) | True | 0.0e+00 | 2022-12-01 | True |
| 12-month (S2a rules) | 2014-04-30 | 104 | 8.9e-16, 1.3e-15 | True | 5.6e-17 | 3.3e-19 | 0 (True) | True | 0.0e+00 | 2022-12-01 | True |
| 12-month (S2a rules) | 2014-05-31 | 103 | 2.2e-15, 3.1e-15 | True | 8.3e-17 | 6.5e-19 | 0 (True) | True | 0.0e+00 | 2022-12-01 | True |
| 12-month (S2a rules) | 2014-06-30 | 102 | 8.9e-16, 1.3e-15 | True | 5.6e-17 | 4.3e-19 | 0 (True) | True | 0.0e+00 | 2022-12-01 | True |
| 12-month (S2a rules) | 2014-07-31 | 101 | 8.9e-16, 1.3e-15 | True | 5.6e-17 | 6.5e-19 | 0 (True) | True | 0.0e+00 | 2022-12-01 | True |
| 12-month (S2a rules) | 2014-08-31 | 100 | 3.6e-15, 4.4e-15 | True | 2.8e-17 | 2.2e-19 | 0 (True) | True | 0.0e+00 | 2022-12-01 | True |
| 12-month (S2a rules) | 2014-09-30 | 99 | 1.8e-15, 2.2e-15 | True | 2.8e-17 | 1.1e-19 | 0 (True) | True | 0.0e+00 | 2022-12-01 | True |
| 12-month (S2a rules) | 2014-10-31 | 98 | 2.7e-15, 3.6e-15 | True | 5.6e-17 | 6.5e-19 | 0 (True) | True | 0.0e+00 | 2022-12-01 | True |
| 12-month (S2a rules) | 2014-11-30 | 97 | 8.9e-16, 1.3e-15 | True | 8.3e-17 | 6.5e-19 | 0 (True) | True | 0.0e+00 | 2022-12-01 | True |
| 12-month (S2a rules) | 2014-12-31 | 96 | 1.6e-15, 1.8e-15 | True | 5.6e-17 | 2.2e-19 | 0 (True) | True | 0.0e+00 | 2022-12-01 | True |
| 12-month (S2a rules) | 2015-01-31 | 95 | 8.9e-16, 1.3e-15 | True | 5.6e-17 | 4.3e-19 | 0 (True) | True | 0.0e+00 | 2022-12-01 | True |

### 2. Tranche combination (`edge_b5.combine_tranches` vs an independent mean of rebased NAVs)

| Configuration | Periods | From | To | Max diff | Placebo combined NAV at end |
|---|---:|---|---|---:|---:|
| quarterly (H1 rules) | 94 | 2015-02-02 | 2022-12-01 | 3.1e-15 | 2.9666 |
| 12-month (S2a rules) | 94 | 2015-02-02 | 2022-12-01 | 8.9e-16 | 2.9441 |

The placebo NAV is shown only to prove the arithmetic runs end to end; it is a hash-ordered portfolio and carries no information about any trial.

### 3. Fixed dates and companies (chosen by rule; plan §2-3)

Recomputed from the raw CSV files: market cap and band. All rows consistent: **True**. Target weights sum to 1: **True**. Sector cap of 4 held: **True**.

| Config | Date | Tranche | Role | CIK | Rank | Eligible | Mcap raw ($bn) | Band (dataset / raw) | Weight before → after |
|---|---|---|---|---:|---:|---|---:|---|---|
| quarterly (H1 rules) | 2015-01-31 | 2015-01-31 | rank 1 | 40704 | 1 | True | 31.685 | large / large | 0.0 → 0.05 |
| quarterly (H1 rules) | 2015-01-31 | 2015-01-31 | rank 20 | 47111 | 20 | True | 22.875 | large / large | 0.0 → 0.05 |
| quarterly (H1 rules) | 2015-01-31 | 2015-01-31 | rank 21 | 27904 | 21 | True | 39.596 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2015-01-31 | 2015-01-31 | buffer hold | 313616 | 23 | True | 57.888 | large / large | 0.0 → 0.05 |
| quarterly (H1 rules) | 2015-01-31 | 2015-01-31 | sector-cap skip | 827052 | 17 | True | 22.204 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2015-01-31 | 2015-01-31 | excluded: price under $1 | 12239 |  | False | 0.027 | None / below large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2015-01-31 | 2015-01-31 | excluded: below $10bn | 1750 |  | False | 1.14 | small / below large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2015-01-31 | 2015-01-31 | excluded: financial | 4962 |  | False | 83.488 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2015-01-31 | 2015-01-31 | excluded: stale TTM | 16875 |  | False | 30.646 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2015-04-30 | 2015-01-31 | rank 1 | 40704 | 1 | True | 32.988 | large / large | 0.050421 → 0.05 |
| quarterly (H1 rules) | 2015-04-30 | 2015-01-31 | rank 20 | 827052 | 20 | True | 19.855 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2015-04-30 | 2015-01-31 | rank 21 | 1059556 | 21 | True | 22.977 | large / large | 0.057415 → 0.05 |
| quarterly (H1 rules) | 2015-04-30 | 2015-01-31 | buffer hold | 1059556 | 21 | True | 22.977 | large / large | 0.057415 → 0.05 |
| quarterly (H1 rules) | 2015-04-30 | 2015-01-31 | excluded: quality flag | 720762 |  | False | 16.592 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2015-04-30 | 2015-01-31 | excluded: price under $1 | 12239 |  | False | 0.021 | None / below large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2015-04-30 | 2015-01-31 | excluded: below $10bn | 1750 |  | False | 1.204 | small / below large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2015-04-30 | 2015-01-31 | excluded: financial | 4962 |  | False | 78.673 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2015-04-30 | 2015-01-31 | excluded: stale TTM | 16875 |  | False | 31.659 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2019-07-31 | 2015-01-31 | rank 1 | 40704 | 1 | True | 31.97 | large / large | 0.052678 → 0.05 |
| quarterly (H1 rules) | 2019-07-31 | 2015-01-31 | rank 20 | 1467373 | 20 | True | 125.205 | large / large | 0.053106 → 0.05 |
| quarterly (H1 rules) | 2019-07-31 | 2015-01-31 | rank 21 | 1318220 | 21 | True | 23.92 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2019-07-31 | 2015-01-31 | buffer hold | 789019 | 22 | True | 1044.212 | large / large | 0.053737 → 0.05 |
| quarterly (H1 rules) | 2019-07-31 | 2015-01-31 | excluded: quality flag | 1084267 |  | False | 27.045 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2019-07-31 | 2015-01-31 | excluded: price under $1 | 8504 |  | False | 0.004 | None / below large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2019-07-31 | 2015-01-31 | excluded: below $10bn | 1750 |  | False | 1.458 | small / below large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2019-07-31 | 2015-01-31 | excluded: financial | 4962 |  | False | 103.187 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2019-07-31 | 2015-01-31 | excluded: stale TTM | 16875 |  | False | 33.063 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2020-03-31 | 2014-12-31 | rank 1 | 40704 | 1 | True | 31.986 | large / large | 0.060066 → 0.05 |
| quarterly (H1 rules) | 2020-03-31 | 2014-12-31 | rank 20 | 1659166 | 20 | True | 18.567 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2020-03-31 | 2014-12-31 | rank 21 | 27904 | 21 | True | 18.262 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2020-03-31 | 2014-12-31 | buffer hold | 313616 | 23 | True | 96.366 | large / large | 0.048525 → 0.05 |
| quarterly (H1 rules) | 2020-03-31 | 2014-12-31 | excluded: quality flag | 827052 |  | False | 19865214.741 | large / large | 0.040725 → 0.0 |
| quarterly (H1 rules) | 2020-03-31 | 2014-12-31 | excluded: price under $1 | 8504 |  | False | 0.006 | None / below large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2020-03-31 | 2014-12-31 | excluded: below $10bn | 1750 |  | False | 0.623 | small / below large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2020-03-31 | 2014-12-31 | excluded: financial | 4962 |  | False | 69.176 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2020-03-31 | 2014-12-31 | excluded: stale TTM | 16875 |  | False | 30.029 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2022-11-30 | 2014-11-30 | rank 1 | 42888 | 1 | True | 11.792 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2022-11-30 | 2014-11-30 | rank 20 | 100885 | 20 | True | 133.676 | large / large | 0.045697 → 0.05 |
| quarterly (H1 rules) | 2022-11-30 | 2014-11-30 | rank 21 | 779152 | 21 | True | 13.813 | large / large | 0.047078 → 0.05 |
| quarterly (H1 rules) | 2022-11-30 | 2014-11-30 | buffer hold | 779152 | 21 | True | 13.813 | large / large | 0.047078 → 0.05 |
| quarterly (H1 rules) | 2022-11-30 | 2014-11-30 | excluded: quality flag | 1005210 |  | False | 1044.976 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2022-11-30 | 2014-11-30 | excluded: price under $1 | 8504 |  | False | 0.038 | None / below large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2022-11-30 | 2014-11-30 | excluded: below $10bn | 1750 |  | False | 1.633 | small / below large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2022-11-30 | 2014-11-30 | excluded: financial | 4962 |  | False | 117.756 | large / large | 0.0 → 0.0 |
| quarterly (H1 rules) | 2022-11-30 | 2014-11-30 | excluded: stale TTM | 16868 |  | False | 90.152 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2015-01-31 | 2015-01-31 | rank 1 | 40704 | 1 | True | 31.685 | large / large | 0.0 → 0.05 |
| 12-month (S2a rules) | 2015-01-31 | 2015-01-31 | rank 20 | 47111 | 20 | True | 22.875 | large / large | 0.0 → 0.05 |
| 12-month (S2a rules) | 2015-01-31 | 2015-01-31 | rank 21 | 27904 | 21 | True | 39.596 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2015-01-31 | 2015-01-31 | buffer hold | 313616 | 23 | True | 57.888 | large / large | 0.0 → 0.05 |
| 12-month (S2a rules) | 2015-01-31 | 2015-01-31 | sector-cap skip | 827052 | 17 | True | 22.204 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2015-01-31 | 2015-01-31 | excluded: price under $1 | 12239 |  | False | 0.027 | None / below large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2015-01-31 | 2015-01-31 | excluded: below $10bn | 1750 |  | False | 1.14 | small / below large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2015-01-31 | 2015-01-31 | excluded: financial | 4962 |  | False | 83.488 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2015-01-31 | 2015-01-31 | excluded: stale TTM | 16875 |  | False | 30.646 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2015-04-30 | 2014-04-30 | rank 1 | 40704 | 1 | True | 32.988 | large / large | 0.04625 → 0.05 |
| 12-month (S2a rules) | 2015-04-30 | 2014-04-30 | rank 20 | 827052 | 20 | True | 19.855 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2015-04-30 | 2014-04-30 | rank 21 | 1059556 | 21 | True | 22.977 | large / large | 0.058816 → 0.05 |
| 12-month (S2a rules) | 2015-04-30 | 2014-04-30 | buffer hold | 1059556 | 21 | True | 22.977 | large / large | 0.058816 → 0.05 |
| 12-month (S2a rules) | 2015-04-30 | 2014-04-30 | excluded: quality flag | 720762 |  | False | 16.592 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2015-04-30 | 2014-04-30 | excluded: price under $1 | 12239 |  | False | 0.021 | None / below large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2015-04-30 | 2014-04-30 | excluded: below $10bn | 1750 |  | False | 1.204 | small / below large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2015-04-30 | 2014-04-30 | excluded: financial | 4962 |  | False | 78.673 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2015-04-30 | 2014-04-30 | excluded: stale TTM | 16875 |  | False | 31.659 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2019-07-31 | 2014-07-31 | rank 1 | 40704 | 1 | True | 31.97 | large / large | 0.057673 → 0.05 |
| 12-month (S2a rules) | 2019-07-31 | 2014-07-31 | rank 20 | 1467373 | 20 | True | 125.205 | large / large | 0.057108 → 0.05 |
| 12-month (S2a rules) | 2019-07-31 | 2014-07-31 | rank 21 | 1318220 | 21 | True | 23.92 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2019-07-31 | 2014-07-31 | buffer hold | 789019 | 22 | True | 1044.212 | large / large | 0.060946 → 0.05 |
| 12-month (S2a rules) | 2019-07-31 | 2014-07-31 | excluded: quality flag | 1084267 |  | False | 27.045 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2019-07-31 | 2014-07-31 | excluded: price under $1 | 8504 |  | False | 0.004 | None / below large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2019-07-31 | 2014-07-31 | excluded: below $10bn | 1750 |  | False | 1.458 | small / below large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2019-07-31 | 2014-07-31 | excluded: financial | 4962 |  | False | 103.187 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2019-07-31 | 2014-07-31 | excluded: stale TTM | 16875 |  | False | 33.063 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2020-03-31 | 2014-03-31 | rank 1 | 40704 | 1 | True | 31.986 | large / large | 0.05991 → 0.05 |
| 12-month (S2a rules) | 2020-03-31 | 2014-03-31 | rank 20 | 1659166 | 20 | True | 18.567 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2020-03-31 | 2014-03-31 | rank 21 | 27904 | 21 | True | 18.262 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2020-03-31 | 2014-03-31 | buffer hold | 313616 | 23 | True | 96.366 | large / large | 0.054368 → 0.05 |
| 12-month (S2a rules) | 2020-03-31 | 2014-03-31 | excluded: quality flag | 827052 |  | False | 19865214.741 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2020-03-31 | 2014-03-31 | excluded: price under $1 | 8504 |  | False | 0.006 | None / below large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2020-03-31 | 2014-03-31 | excluded: below $10bn | 1750 |  | False | 0.623 | small / below large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2020-03-31 | 2014-03-31 | excluded: financial | 4962 |  | False | 69.176 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2020-03-31 | 2014-03-31 | excluded: stale TTM | 16875 |  | False | 30.029 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2022-11-30 | 2014-11-30 | rank 1 | 42888 | 1 | True | 11.792 | large / large | 0.050913 → 0.05 |
| 12-month (S2a rules) | 2022-11-30 | 2014-11-30 | rank 20 | 100885 | 20 | True | 133.676 | large / large | 0.048807 → 0.05 |
| 12-month (S2a rules) | 2022-11-30 | 2014-11-30 | rank 21 | 779152 | 21 | True | 13.813 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2022-11-30 | 2014-11-30 | buffer hold | 21076 | 23 | True | 18.341 | large / large | 0.048127 → 0.05 |
| 12-month (S2a rules) | 2022-11-30 | 2014-11-30 | excluded: quality flag | 1005210 |  | False | 1044.976 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2022-11-30 | 2014-11-30 | excluded: price under $1 | 8504 |  | False | 0.038 | None / below large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2022-11-30 | 2014-11-30 | excluded: below $10bn | 1750 |  | False | 1.633 | small / below large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2022-11-30 | 2014-11-30 | excluded: financial | 4962 |  | False | 117.756 | large / large | 0.0 → 0.0 |
| 12-month (S2a rules) | 2022-11-30 | 2014-11-30 | excluded: stale TTM | 16868 |  | False | 90.152 | large / large | 0.0 → 0.0 |

### 4. Market-cap share counts re-read from SEC's live XBRL API (quarterly configuration, ranks 1 and 20)

This re-reads the filings' tagged values from SEC today, so it tests the download, panel and point-in-time steps. It is not an independent source: it reads the same XBRL filings.

| Date | Role | CIK | Field (concept) | Dataset shares | SEC shares | Period end | Filed | Form | Match |
|---|---|---:|---|---:|---:|---|---|---|---|
| 2015-01-31 | rank 1 | 40704 | shares_out (dei:EntityCommonStockSharesOutstanding) | 603,747,687 | 603,747,687 | 2014-12-05 | 2014-12-17 | 10-Q | True |
| 2015-01-31 | rank 20 | 47111 | shares_out (dei:EntityCommonStockSharesOutstanding) | 223,805,223 | 223,805,223 | 2014-02-07 | 2014-02-21 | 10-K | True |
| 2015-04-30 | rank 1 | 40704 | shares_out (dei:EntityCommonStockSharesOutstanding) | 596,089,958 | 596,089,958 | 2015-03-06 | 2015-03-18 | 10-Q | True |
| 2015-04-30 | rank 20 | 827052 | shares_out (dei:EntityCommonStockSharesOutstanding) | 325,811,206 | 325,811,206 | 2015-04-24 | 2015-04-28 | 10-Q | True |
| 2019-07-31 | rank 1 | 40704 | shares_out (dei:EntityCommonStockSharesOutstanding) | 601,959,611 | 601,959,611 | 2019-06-10 | 2019-06-28 | 10-K | True |
| 2019-07-31 | rank 20 | 1467373 | shares_diluted (us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding) | 650,144,931 | 650,144,931 | 2019-05-31 | 2019-06-27 | 10-Q | True |
| 2020-03-31 | rank 1 | 40704 | shares_out (dei:EntityCommonStockSharesOutstanding) | 606,138,918 | 606,138,918 | 2020-03-10 | 2020-03-18 | 10-Q | True |
| 2020-03-31 | rank 20 | 1659166 | shares_out (dei:EntityCommonStockSharesOutstanding) | 336,415,264 | 336,415,264 | 2020-02-21 | 2020-02-27 | 10-K | True |
| 2022-11-30 | rank 1 | 42888 | shares_out (dei:EntityCommonStockSharesOutstanding) | 168,529,015 | 168,529,015 | 2022-10-12 | 2022-10-26 | 10-Q | True |
| 2022-11-30 | rank 20 | 100885 | shares_out (dei:EntityCommonStockSharesOutstanding) | 614,800,800 | 614,800,800 | 2022-10-14 | 2022-10-20 | 10-Q | True |

### Data files (sha256)

- `monthly_metrics.csv.gz`: `ae5429b661bd060d040109138d35cb4ea22356d4a549056c8616c3a2a7e87561`
- `prices_monthly.csv.gz`: `505115711f7ef59c8df417671f8afecf77dd2240e13a2a3bdff453721b3d801a`
- `sec_companies.csv.gz`: `acf5e3f746c355aa2c0aa2b76c0c3f55413daf5e927524672537d0389d214a90`
- `exec_prices_to_2022.csv.gz`: `dd6608f62ae2676fd4fd5b3b256105d5f52eb720ba3a10a2965cf504e17d47dc`
- `gbpusd_daily_to_2022.csv.gz`: `fd9f8e7dc921465732460a507225778ea9d14437dfd5026f4b37f3dd54310d65`
- `benchmarks_daily_gbp_to_2022.csv.gz`: `0ec17f8631a17cc6f7cc3ca7e1f8054437371e2012739926d4ccfffa0b1f6fc6`

# B5 input audit: revenue fallback, common period ends, foreign forms

Run 2026-10-16. Large-band company-months 2015-01 to 2022-12 passing the Phase A quality rule: 43,511 rows (34,624 non-financial), 781 companies. SEC facts filed after 2022-12-31 are never read. **No price, return, score, ranking or NAV is computed.**

> **Survivorship (material, unbounded):** the universe needs a price, so companies that delisted before the 2026 price download are missing entirely. Nothing here bounds that bias.

## 1. H1: operating cash flow and capex period ends

- Both inputs present: 40,217 rows. Latest TTM period ends differ: **1,546** (3.8%; 593 non-financial).
- Registered rule (v2 §2.1, unchanged by ADDENDUM_1 §2): those rows have no FCF, so no H1 score. No alignment is attempted.
- Diagnostic only: aligning both inputs to the earlier common end would recover 132 rows that are also fresh (≤ 183 days). Not adopted.
- The earlier figure (650 of 39,273, v2 §1.1) was measured on the dataset's carried-forward values; this count recomputes each input as known at each month-end, which is what the trial will use.

## 2. S2a: which gross profit each non-financial row would use

| Path | Rows |
|---|---:|
| `GrossProfit` tag, own end ≤ 183 days | 14,687 |
| Fallback: revenue − cost of revenue, common end ≤ 183 days | 10,084 |
| Neither (no S2a score) | 9,853 |

- Stale `GrossProfit` (> 183 days) is never used: 2,587 rows; of these 1,855 fall back to a fresh revenue − cost of revenue and 732 have no score.

### Revenue-concept conflicts among fallback rows (ADDENDUM_1 §1)

Ratio = largest value any listed revenue concept reports for the same period ÷ the selected concept's value (worst period of the TTM). Above 1.10, or a selected value ≤ 0, is a conflict and the fallback is unavailable.

| Ratio | Fallback rows |
|---|---:|
| (0.0, 1.0] | 9,117 |
| (1.0, 1.05] | 404 |
| (1.05, 1.1] | 124 |
| (1.1, 1.25] | 171 |
| (1.25, 1.5] | 61 |
| (1.5, 2.0] | 50 |
| (2.0, inf] | 157 |

**439 fallback rows in 44 companies conflict** and become unavailable:

| CIK | Company | Rows | First | Last | Worst ratio |
|---|---|---:|---|---|---:|
| 1551182 | Eaton Corp plc | 37 | 2015-01-31 | 2018-01-31 | inf |
| 23217 | CONAGRA BRANDS INC. | 33 | 2015-01-31 | 2017-12-31 | 8.33 |
| 40545 | GENERAL ELECTRIC CO | 24 | 2015-07-31 | 2020-09-30 | 9.65 |
| 46080 | HASBRO, INC. | 20 | 2016-04-30 | 2018-01-31 | 2.33 |
| 40704 | GENERAL MILLS INC | 19 | 2021-06-30 | 2022-12-31 | 8.90 |
| 1666700 | DuPont de Nemours, Inc. | 16 | 2019-08-31 | 2022-12-31 | 3.99 |
| 40533 | GENERAL DYNAMICS CORP | 14 | 2017-07-31 | 2019-01-31 | 1.81 |
| 16732 | CAMPBELL'S Co | 12 | 2019-06-30 | 2020-08-31 | 1.24 |
| 1681459 | TechnipFMC plc | 11 | 2017-05-31 | 2018-03-31 | inf |
| 80424 | PROCTER & GAMBLE Co | 10 | 2015-01-31 | 2015-12-31 | 2.83 |
| 33213 | EQT Corp | 10 | 2022-03-31 | 2022-12-31 | inf |
| 1466258 | Trane Technologies plc | 10 | 2015-01-31 | 2021-01-31 | 1.28 |
| 1467858 | General Motors Co | 10 | 2017-07-31 | 2018-06-30 | 1.13 |
| 202058 | L3HARRIS TECHNOLOGIES, INC. /DE/ | 10 | 2017-05-31 | 2018-04-30 | 1.25 |
| 1645590 | Hewlett Packard Enterprise Co | 9 | 2017-06-30 | 2018-05-31 | 1.65 |
| 47217 | HP INC | 9 | 2016-03-31 | 2016-11-30 | 1.98 |
| 31462 | ECOLAB INC. | 9 | 2020-08-31 | 2021-07-31 | 1.19 |
| 1442145 | Verisk Analytics, Inc. | 9 | 2016-05-31 | 2017-01-31 | 1.20 |
| 1510295 | Marathon Petroleum Corp | 9 | 2020-11-30 | 2021-10-31 | 1.17 |
| 59478 | ELI LILLY & Co | 9 | 2019-05-31 | 2020-01-31 | 1.15 |
| 891103 | Match Group, Inc. | 9 | 2020-08-31 | 2021-07-31 | 2.38 |
| 1090872 | AGILENT TECHNOLOGIES, INC. | 9 | 2015-03-31 | 2015-11-30 | 1.72 |
| 103379 | V F CORP | 9 | 2019-10-31 | 2020-09-30 | 1.25 |
| 51434 | INTERNATIONAL PAPER CO /NEW/ | 9 | 2022-04-30 | 2022-12-31 | 1.17 |
| 78003 | PFIZER INC | 9 | 2021-05-31 | 2022-01-31 | 1.19 |
| 310158 | Merck & Co., Inc. | 9 | 2021-08-31 | 2022-07-31 | 1.17 |
| 1136869 | ZIMMER BIOMET HOLDINGS, INC. | 8 | 2022-05-31 | 2022-12-31 | 1.15 |
| 8670 | AUTOMATIC DATA PROCESSING INC | 7 | 2015-01-31 | 2015-07-31 | 1.20 |
| 32604 | EMERSON ELECTRIC CO | 7 | 2017-04-30 | 2017-10-31 | 1.41 |
| 1800 | ABBOTT LABORATORIES | 7 | 2015-01-31 | 2015-10-31 | 1.11 |
| 2969 | Air Products & Chemicals, Inc. | 7 | 2017-04-30 | 2017-10-31 | 1.27 |
| 1521332 | Aptiv PLC | 7 | 2018-07-31 | 2019-01-31 | 1.37 |
| 813762 | ICAHN ENTERPRISES L.P. | 7 | 2018-08-31 | 2019-02-28 | 1.63 |
| 101829 | RTX Corp | 7 | 2015-10-31 | 2016-09-30 | 1.12 |
| 93556 | STANLEY BLACK & DECKER, INC. | 6 | 2022-07-31 | 2022-12-31 | 1.13 |
| 1013871 | NRG ENERGY, INC. | 6 | 2018-05-31 | 2019-10-31 | 1.18 |
| 1163165 | CONOCOPHILLIPS | 6 | 2020-05-31 | 2021-07-31 | 1.28 |
| 1130310 | CENTERPOINT ENERGY INC | 6 | 2020-08-31 | 2021-01-31 | 1.64 |
| 788784 | PUBLIC SERVICE ENTERPRISE GROUP INC | 3 | 2019-07-31 | 2019-09-30 | 2.40 |
| 1090012 | DEVON ENERGY CORP/DE | 3 | 2019-05-31 | 2019-07-31 | 1.73 |
| 1570585 | Liberty Global Ltd. | 3 | 2019-05-31 | 2019-07-31 | 1.36 |
| 1755672 | Corteva, Inc. | 3 | 2020-05-31 | 2020-07-31 | 1.85 |
| 109177 | Spectrum Brands Holdings, Inc. | 1 | 2018-07-31 | 2018-07-31 | 1.77 |
| 47111 | HERSHEY CO | 1 | 2015-01-31 | 2015-01-31 | 3.97 |

## 3. Foreign annual forms (ADDENDUM_1 §3)

339 rows whose latest balance sheet came from a 20-F or 40-F become unavailable to both trials:

| CIK | Company | Rows | First | Last | Financial |
|---|---|---:|---|---|---|
| 818686 | TEVA PHARMACEUTICAL INDUSTRIES LTD | 37 | 2015-01-31 | 2018-01-31 | False |
| 849395 | CRH PUBLIC LTD CO | 22 | 2021-03-31 | 2022-12-31 | False |
| 1159152 | James Hardie Industries plc | 30 | 2015-01-31 | 2022-07-31 | False |
| 1413447 | NXP Semiconductors N.V. | 57 | 2015-01-31 | 2019-09-30 | False |
| 1527762 | Chaince Digital Holdings Inc. | 7 | 2021-02-28 | 2021-11-30 | True |
| 1541157 | Akari Therapeutics Plc | 2 | 2017-03-31 | 2017-04-30 | False |
| 1567094 | CNH Industrial N.V. | 68 | 2015-04-30 | 2022-10-31 | False |
| 1594805 | SHOPIFY INC. | 17 | 2021-02-28 | 2022-06-30 | False |
| 1611747 | Scinai Immunotherapeutics Ltd. | 4 | 2020-06-30 | 2020-09-30 | False |
| 1635327 | Flutter Entertainment plc | 39 | 2018-03-31 | 2021-05-31 | False |
| 1650372 | Atlassian Corp | 51 | 2018-08-31 | 2022-10-31 | False |
| 1704292 | Zai Lab Ltd | 2 | 2021-01-31 | 2021-02-28 | False |
| 1873875 | Incannex Healthcare Inc. | 3 | 2022-10-31 | 2022-12-31 | False |

## 4. The named cases

| Company | Eligible rows | S2a paths | Fallback conflicts | Foreign-form rows |
|---|---:|---|---|---:|
| General Mills | 96 (2015-01-31 to 2022-12-31) | fallback 96 | 19 (2021-06-30 to 2022-12-31) | 0 |
| Eaton | 96 (2015-01-31 to 2022-12-31) | fallback 96 | 37 (2015-01-31 to 2018-01-31) | 0 |
| Procter & Gamble | 96 (2015-01-31 to 2022-12-31) | fallback 96 | 10 (2015-01-31 to 2015-12-31) | 0 |
| Flutter (CIK of The Stars Group) | 39 (2018-03-31 to 2021-05-31) | none 30, gross_profit_tag 9 | 0 | 39 |

H1 does not use revenue, so the revenue defect cannot reach H1 scores.

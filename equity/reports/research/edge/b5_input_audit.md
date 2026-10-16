# B5 input audit: revenue tests, restated periods, common period ends, company identity

Run 2026-10-16. Large-band company-months 2015-01 to 2022-12 passing the Phase A quality rule: 43,511 rows (34,624 non-financial), 781 companies. SEC facts filed after 2022-12-31 are never read. **No return, score, ranking or NAV is computed.**

> **Survivorship (material, unbounded):** the universe needs a price, so companies that delisted before the 2026 price download are missing entirely. Nothing here bounds that bias.

## 1. H1: operating cash flow and capex

- Latest TTM ends differ in **1,546** of 40,217 rows (593 non-financial): no H1 score (owner decision, no alignment). An alignment step would have recovered 132 fresh rows; not adopted.
- Rows with a fresh common end: 38,375. Of these, **1,166** (956 non-financial, 182 companies) have an OCF or capex TTM that mixes bases (test T2). **Open decision: T2 is not applied to H1 yet.**

## 2. S2a: which gross profit each non-financial row would use

| Path | Rows |
|---|---:|
| `GrossProfit` tag, own end ≤ 183 days | 14,687 |
| Fallback: revenue − cost of revenue, common end ≤ 183 days | 10,084 |
| Neither (no S2a score) | 9,853 |

- A `GrossProfit` value older than 183 days is never used: 2,587 rows; 1,855 fall back to a fresh revenue − cost of revenue, 732 have no score.
- `GrossProfit`-tag rows whose TTM mixes bases (T2): 171 in 28 companies. **Open decision: T2 is not applied to the tag path yet.**

### Fallback rows blocked by the revenue tests (ADDENDUM_2 §1)

**587 of 10,084 fallback rows, 63 companies.** By test (T0 revenue ≤ 0; T1 same-filing concept conflict; T2 revenue TTM mixes bases; COR-T2 cost of revenue TTM mixes bases):

| Tests failed | Rows |
|---|---:|
| COR-T2 | 79 |
| T0 | 54 |
| T1 | 90 |
| T1+COR-T2 | 6 |
| T1+T2+COR-T2 | 7 |
| T2 | 175 |
| T2+COR-T2 | 176 |

| CIK | Company | Tests | Rows | First | Last |
|---|---|---|---:|---|---|
| 908937 | SIRIUS XM HOLDINGS INC. | COR-T2 | 12 | 2015-04-30 | 2018-06-30 |
| 8670 | AUTOMATIC DATA PROCESSING INC | COR-T2 | 7 | 2015-01-31 | 2015-07-31 |
| 896878 | INTUIT INC. | COR-T2 | 7 | 2015-01-31 | 2018-01-31 |
| 1521332 | Aptiv PLC | COR-T2 | 7 | 2015-07-31 | 2016-01-31 |
| 1800227 | People Inc | COR-T2 | 7 | 2021-08-31 | 2022-02-28 |
| 40545 | GENERAL ELECTRIC CO | COR-T2 | 6 | 2020-04-30 | 2020-09-30 |
| 773840 | HONEYWELL INTERNATIONAL INC | COR-T2 | 6 | 2018-07-31 | 2019-09-30 |
| 45012 | HALLIBURTON CO | COR-T2 | 4 | 2015-10-31 | 2016-01-31 |
| 797468 | OCCIDENTAL PETROLEUM CORP /DE/ | COR-T2 | 4 | 2020-05-31 | 2020-08-31 |
| 101829 | RTX Corp | COR-T2 | 3 | 2018-04-30 | 2018-06-30 |
| 790051 | CARLISLE COMPANIES INC | COR-T2 | 3 | 2022-04-30 | 2022-06-30 |
| 874499 | GULFPORT ENERGY CORP | COR-T2 | 3 | 2021-05-31 | 2021-07-31 |
| 1000697 | WATERS CORP /DE/ | COR-T2 | 3 | 2018-05-31 | 2018-07-31 |
| 1501585 | HUNTINGTON INGALLS INDUSTRIES, INC. | COR-T2 | 3 | 2018-07-31 | 2018-09-30 |
| 732712 | VERIZON COMMUNICATIONS INC | COR-T2 | 2 | 2018-05-31 | 2018-06-30 |
| 109177 | Spectrum Brands Holdings, Inc. | COR-T2 | 1 | 2018-07-31 | 2018-07-31 |
| 1466258 | Trane Technologies plc | COR-T2 | 1 | 2015-01-31 | 2015-01-31 |
| 1551182 | Eaton Corp plc | T0 | 37 | 2015-01-31 | 2018-01-31 |
| 1681459 | TechnipFMC plc | T0 | 11 | 2017-05-31 | 2018-03-31 |
| 33213 | EQT Corp | T0 | 6 | 2022-04-30 | 2022-12-31 |
| 23217 | CONAGRA BRANDS INC. | T1 | 24 | 2015-07-31 | 2017-06-30 |
| 46080 | HASBRO, INC. | T1 | 20 | 2016-04-30 | 2018-01-31 |
| 40704 | GENERAL MILLS INC | T1 | 19 | 2021-06-30 | 2022-12-31 |
| 40533 | GENERAL DYNAMICS CORP | T1 | 7 | 2018-07-31 | 2019-01-31 |
| 80424 | PROCTER & GAMBLE Co | T1 | 7 | 2015-01-31 | 2015-07-31 |
| 1163165 | CONOCOPHILLIPS | T1 | 6 | 2020-05-31 | 2021-07-31 |
| 33213 | EQT Corp | T1 | 4 | 2022-03-31 | 2022-09-30 |
| 40545 | GENERAL ELECTRIC CO | T1 | 2 | 2017-05-31 | 2017-06-30 |
| 47111 | HERSHEY CO | T1 | 1 | 2015-01-31 | 2015-01-31 |
| 23217 | CONAGRA BRANDS INC. | T1+COR-T2 | 6 | 2015-01-31 | 2015-06-30 |
| 40533 | GENERAL DYNAMICS CORP | T1+T2+COR-T2 | 7 | 2017-07-31 | 2018-01-31 |
| 1060391 | REPUBLIC SERVICES, INC. | T2 | 36 | 2015-04-30 | 2022-09-30 |
| 8670 | AUTOMATIC DATA PROCESSING INC | T2 | 18 | 2018-11-30 | 2020-07-31 |
| 319201 | KLA CORP | T2 | 10 | 2018-10-31 | 2019-07-31 |
| 1018724 | AMAZON COM INC | T2 | 10 | 2018-10-31 | 2019-09-30 |
| 1283699 | T-Mobile US, Inc. | T2 | 10 | 2017-04-30 | 2018-01-31 |
| 40545 | GENERAL ELECTRIC CO | T2 | 9 | 2015-05-31 | 2016-01-31 |
| 45012 | HALLIBURTON CO | T2 | 9 | 2016-05-31 | 2017-01-31 |
| 103379 | V F CORP | T2 | 9 | 2019-08-31 | 2020-04-30 |
| 1090872 | AGILENT TECHNOLOGIES, INC. | T2 | 9 | 2018-08-31 | 2019-07-31 |
| 1601046 | Keysight Technologies, Inc. | T2 | 9 | 2019-03-31 | 2019-11-30 |
| 315189 | DEERE & CO | T2 | 8 | 2015-02-28 | 2018-04-30 |
| 1618756 | Restaurant Brands International Inc. | T2 | 8 | 2016-04-30 | 2019-07-31 |
| 14272 | BRISTOL MYERS SQUIBB CO | T2 | 7 | 2019-07-31 | 2020-01-31 |
| 3570 | Cheniere Energy, Inc. | T2 | 6 | 2017-08-31 | 2018-01-31 |
| 202058 | L3HARRIS TECHNOLOGIES, INC. /DE/ | T2 | 3 | 2017-05-31 | 2017-07-31 |
| 788784 | PUBLIC SERVICE ENTERPRISE GROUP INC | T2 | 3 | 2019-07-31 | 2019-09-30 |
| 797468 | OCCIDENTAL PETROLEUM CORP /DE/ | T2 | 3 | 2021-05-31 | 2021-07-31 |
| 1506307 | KINDER MORGAN, INC. | T2 | 3 | 2015-07-31 | 2015-09-30 |
| 779152 | JACK HENRY & ASSOCIATES INC | T2 | 2 | 2018-06-30 | 2018-07-31 |
| 1423902 | Western Midstream Partners, LP | T2 | 2 | 2019-05-31 | 2019-06-30 |
| 813762 | ICAHN ENTERPRISES L.P. | T2 | 1 | 2015-01-31 | 2015-01-31 |
| 1666700 | DuPont de Nemours, Inc. | T2+COR-T2 | 15 | 2019-08-31 | 2022-01-31 |
| 1090872 | AGILENT TECHNOLOGIES, INC. | T2+COR-T2 | 14 | 2015-03-31 | 2018-07-31 |
| 47217 | HP INC | T2+COR-T2 | 9 | 2016-03-31 | 2016-11-30 |
| 59478 | ELI LILLY & Co | T2+COR-T2 | 9 | 2019-05-31 | 2020-01-31 |
| 1442145 | Verisk Analytics, Inc. | T2+COR-T2 | 9 | 2016-05-31 | 2017-01-31 |
| 1466258 | Trane Technologies plc | T2+COR-T2 | 9 | 2020-05-31 | 2021-01-31 |
| 1136869 | ZIMMER BIOMET HOLDINGS, INC. | T2+COR-T2 | 8 | 2022-05-31 | 2022-12-31 |
| 2969 | Air Products & Chemicals, Inc. | T2+COR-T2 | 7 | 2017-04-30 | 2017-10-31 |
| 732712 | VERIZON COMMUNICATIONS INC | T2+COR-T2 | 7 | 2015-07-31 | 2016-01-31 |
| 813762 | ICAHN ENTERPRISES L.P. | T2+COR-T2 | 7 | 2018-08-31 | 2019-02-28 |
| 1467858 | General Motors Co | T2+COR-T2 | 7 | 2017-07-31 | 2018-01-31 |
| 31462 | ECOLAB INC. | T2+COR-T2 | 6 | 2020-08-31 | 2021-01-31 |
| 87347 | SLB LIMITED/NV | T2+COR-T2 | 6 | 2016-07-31 | 2016-12-31 |
| 310158 | Merck & Co., Inc. | T2+COR-T2 | 6 | 2021-08-31 | 2022-01-31 |
| 891103 | Match Group, Inc. | T2+COR-T2 | 6 | 2020-08-31 | 2021-01-31 |
| 1130310 | CENTERPOINT ENERGY INC | T2+COR-T2 | 6 | 2020-08-31 | 2021-01-31 |
| 1133421 | NORTHROP GRUMMAN CORP /DE/ | T2+COR-T2 | 6 | 2018-04-30 | 2018-09-30 |
| 1645590 | Hewlett Packard Enterprise Co | T2+COR-T2 | 6 | 2017-06-30 | 2017-11-30 |
| 30554 | EIDP, Inc. | T2+COR-T2 | 4 | 2015-10-31 | 2016-01-31 |
| 40533 | GENERAL DYNAMICS CORP | T2+COR-T2 | 4 | 2015-01-31 | 2017-06-30 |
| 101829 | RTX Corp | T2+COR-T2 | 4 | 2015-10-31 | 2016-01-31 |
| 773840 | HONEYWELL INTERNATIONAL INC | T2+COR-T2 | 4 | 2018-10-31 | 2019-01-31 |
| 16732 | CAMPBELL'S Co | T2+COR-T2 | 3 | 2019-06-30 | 2019-08-31 |
| 31791 | REVVITY, INC. | T2+COR-T2 | 3 | 2018-08-31 | 2019-01-31 |
| 1423902 | Western Midstream Partners, LP | T2+COR-T2 | 3 | 2019-07-31 | 2019-09-30 |
| 1510295 | Marathon Petroleum Corp | T2+COR-T2 | 3 | 2020-11-30 | 2021-01-31 |
| 1755672 | Corteva, Inc. | T2+COR-T2 | 3 | 2020-05-31 | 2020-07-31 |
| 40545 | GENERAL ELECTRIC CO | T2+COR-T2 | 2 | 2018-05-31 | 2018-06-30 |

## 3. Company identity and price units

### 3.1 The 13 companies with a 20-F/40-F balance sheet (339 rows)

| CIK | Company | Ticker | Rows | First | Last | Median market cap $bn | Median assets $bn | Cap ÷ assets | Review |
|---|---|---|---:|---|---|---:|---:|---:|---|
| 818686 | TEVA PHARMACEUTICAL INDUSTRIES LTD | TEVA | 37 | 2015-01-31 | 2018-01-31 | 51.2 | 54.26 | 0.9 | plausible: NYSE ADS 1:1, market cap 0.9x assets |
| 849395 | CRH PUBLIC LTD CO | CRH | 22 | 2021-03-31 | 2022-12-31 | 36.4 | 44.94 | 0.8 | plausible: NYSE listing, market cap 0.8x assets |
| 1159152 | James Hardie Industries plc | JHX | 30 | 2015-01-31 | 2022-07-31 | 14.9 | 4.03 | 3.7 | plausible: market cap 3.7x assets (ADS ratio changed over time; not verified) |
| 1413447 | NXP Semiconductors N.V. | NXPI | 57 | 2015-01-31 | 2019-09-30 | 32.2 | 24.05 | 1.5 | plausible: Nasdaq common shares, market cap 1.5x assets |
| 1527762 | Chaince Digital Holdings Inc. | CD | 7 | 2021-02-28 | 2021-11-30 | 15.3 | 0.01 | 1,579.0 | INVALID units: market cap 1,579x assets, ADS price times ordinary shares (financial, never scored) |
| 1541157 | Akari Therapeutics Plc | AKTX | 2 | 2017-03-31 | 2017-04-30 | 15.3 | 0.05 | 334.5 | INVALID units: market cap 334x assets, ADS price times ordinary shares |
| 1567094 | CNH Industrial N.V. | CNH | 68 | 2015-04-30 | 2022-10-31 | 13.9 | 48.28 | 0.3 | plausible: NYSE common shares, market cap 0.3x assets |
| 1594805 | SHOPIFY INC. | SHOP | 17 | 2021-02-28 | 2022-06-30 | 153.4 | 7.76 | 19.8 | plausible: NYSE class A shares (diluted count), market cap 20x assets |
| 1611747 | Scinai Immunotherapeutics Ltd. | SCNI | 4 | 2020-06-30 | 2020-09-30 | 16.3 | nan | n/a | INVALID units: $16bn market cap for a small biotech with no total assets in the data |
| 1635327 | Flutter Entertainment plc | FLUT | 39 | 2018-03-31 | 2021-05-31 | 16.3 | 11.27 | 2.2 | INVALID identity: CIK filed as The Stars Group (40-F) in 2018-20, priced with Flutter's FLUT |
| 1650372 | Atlassian Corp | TEAM | 51 | 2018-08-31 | 2022-10-31 | 44.5 | 2.98 | 14.2 | plausible: Nasdaq class A shares (diluted count), market cap 14x assets |
| 1704292 | Zai Lab Ltd | ZLAB | 2 | 2021-01-31 | 2021-02-28 | 10.5 | 0.36 | 29.6 | plausible: Nasdaq ADS, market cap 30x assets (ADS ratio not verified) |
| 1873875 | Incannex Healthcare Inc. | IXHL | 3 | 2022-10-31 | 2022-12-31 | 20.5 | 0.04 | 540.4 | INVALID units: market cap 540x assets, ADS price times ordinary shares |

### 3.2 Market cap above 100 × total assets (all companies; highest genuine case seen 54×, Zoom in late 2020)

| CIK | Company | Rows | First | Last | Financial | Lowest ratio |
|---|---|---:|---|---|---|---:|
| 1084267 | Mobiquity Technologies, Inc. | 8 | 2018-08-31 | 2019-03-31 | False | 1,371 |
| 1108205 | CURIS INC | 4 | 2021-01-31 | 2021-05-31 | False | 101 |
| 1157075 | PharmaCyte Biotech, Inc. | 1 | 2021-07-31 | 2021-07-31 | False | 3,467 |
| 1374690 | Larimar Therapeutics, Inc. | 1 | 2015-03-31 | 2015-03-31 | False | 109 |
| 1517681 | Propanc Biopharma, Inc. | 22 | 2015-05-31 | 2021-01-31 | False | 6,672 |
| 1527762 | Chaince Digital Holdings Inc. | 7 | 2021-02-28 | 2021-11-30 | True | 973 |
| 1540684 | Atlas Lithium Corp | 41 | 2015-01-31 | 2022-10-31 | False | 8,149 |
| 1541157 | Akari Therapeutics Plc | 14 | 2015-11-30 | 2017-04-30 | False | 144 |
| 1613103 | Medtronic plc | 4 | 2015-02-28 | 2015-05-31 | False | 2,306,440 |
| 1650101 | ADDENTAX GROUP CORP. | 1 | 2022-08-31 | 2022-08-31 | False | 13,156 |
| 1651308 | BeOne Medicines Ltd. | 4 | 2017-09-30 | 2018-04-30 | False | 101 |
| 1688126 | Crypto Co | 1 | 2017-12-31 | 2017-12-31 | False | 3,023 |
| 1707925 | LINDE PLC | 4 | 2018-11-30 | 2019-02-28 | False | 9,629 |
| 1784970 | Next Technology Holding Inc. | 6 | 2022-07-31 | 2022-12-31 | False | 266 |
| 1873875 | Incannex Healthcare Inc. | 3 | 2022-10-31 | 2022-12-31 | False | 382 |

### 3.3 Between 25× and 100× (kept by every option; errors and genuine cases overlap here)

| CIK | Company | Rows | Highest ratio |
|---|---|---:|---:|
| 1261333 | DOCUSIGN, INC. | 2 | 25 |
| 1713683 | Zscaler, Inc. | 1 | 25 |
| 1511737 | Ubiquiti Inc. | 2 | 26 |
| 1831097 | agilon health, inc. | 2 | 28 |
| 1647639 | Upstart Holdings, Inc. | 2 | 28 |
| 1561550 | Datadog, Inc. | 4 | 29 |
| 1811210 | Lucid Group, Inc. | 1 | 29 |
| 1655210 | BEYOND MEAT, INC. | 2 | 30 |
| 1477720 | Asana, Inc. | 1 | 31 |
| 1704292 | Zai Lab Ltd | 2 | 31 |
| 906709 | NEKTAR THERAPEUTICS | 3 | 34 |
| 1650372 | Atlassian Corp | 7 | 39 |
| 1645113 | NovoCure Ltd | 4 | 41 |
| 1477333 | Cloudflare, Inc. | 3 | 41 |
| 1585521 | Zoom Communications, Inc. | 12 | 54 |
| 1374690 | Larimar Therapeutics, Inc. | 8 | 85 |
| 1108205 | CURIS INC | 6 | 97 |
| 1651308 | BeOne Medicines Ltd. | 73 | 97 |

### 3.4 Options compared (input evidence only)

| Option | Rows removed | Companies | Invalid companies removed | Plausible foreign filers removed | Other companies removed |
|---|---:|---:|---|---|---|
| A_broad_foreign_form | 339 | 13 | [1527762, 1541157, 1611747, 1635327, 1873875] | [818686, 849395, 1159152, 1413447, 1567094, 1594805, 1650372, 1704292] | 0 |
| B_cik_1635327_only | 39 | 1 | [1635327] | [] | 0 |
| C_cik_1635327_plus_mcap_over_100x_assets | 160 | 16 | [1527762, 1541157, 1635327, 1873875] | [] | 12 |

## 4. The named cases

| Company | Eligible rows | S2a paths | Fallback rows blocked | Foreign-form rows |
|---|---:|---|---|---:|
| General Mills | 96 (2015-01-31 to 2022-12-31) | fallback 96 | {'T1': 19} | 0 |
| Eaton | 96 (2015-01-31 to 2022-12-31) | fallback 96 | {'T0': 37} | 0 |
| Procter & Gamble | 96 (2015-01-31 to 2022-12-31) | fallback 96 | {'T1': 7} | 0 |
| Flutter (CIK of The Stars Group) | 39 (2018-03-31 to 2021-05-31) | none 30, gross_profit_tag 9 | 0 | 39 |

H1 does not use revenue, so the revenue tests cannot change H1 scores.

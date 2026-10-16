# TTM accounting checks 1-3 (PHASE_A_AUDIT.md §10.4)

Run 2026-10-16. Large-band company-months 2015-01 to 2022-12 passing the quality rule: 43,511 rows, 781 companies. SEC facts filed after 2022-12-31 are never read. No return, score or ranking is computed.

> **Survivorship (material, unbounded):** the universe needs a price, so companies that delisted before the 2026 price download are missing entirely. The -30% and -100% missing-price rules do not address them and are not evidence that survivorship bias is bounded.

## Reproduction (precondition)

Recomputing every TTM with `equity.panel.ttm` from the facts reproduces the dataset exactly where both exist:

| Metric | Both present | Equal | Dataset only | Recomputed only |
|---|---:|---:|---:|---:|
| revenue | 40,806 | 40,806 | 12 | 0 |
| ocf | 42,576 | 42,576 | 5 | 0 |
| capex | 39,282 | 39,282 | 30 | 0 |
| gross_profit | 16,358 | 16,358 | 24 | 0 |
| cost_of_revenue | 27,138 | 27,138 | 28 | 0 |

"Dataset only" rows are values the builder carried forward from an earlier filing after their period became more than 18 months old (it re-evaluates freshness only when the company files). See the stale-input finding below.

## Check 1: basis

Pass rule: the fiscal-year-only share is below 10% for large caps. A fiscal-year basis is correct for the months between a 10-K and the next 10-Q (about a quarter of all months), so the rule is applied to **stale fallbacks**: a later year-to-date period was already filed but the prior-year comparative was missing.

| Metric | All `fy` rows | Stale fallbacks (all years) | Worst single year |
|---|---:|---:|---:|
| capex | 23.0% | 0.048% | 0.23% |
| cost_of_revenue | 23.0% | 0.022% | 0.18% |
| gross_profit | 29.0% | 0.000% | 0.00% |
| ocf | 22.0% | 0.023% | 0.21% |
| revenue | 22.7% | 0.015% | 0.13% |

**Result: PASS** on stale fallbacks (all below 0.25% in every year). Read literally (every `fy` row), the share is 22-29% and the rule would fail, but those rows are correct.

## Check 2: fiscal-year identity

Every 10-K filed 2015-2022: at the first month-end after filing, the dataset's TTM equals the 10-K's annual value of the best-ranked concept.

| Metric | 10-Ks | Equal | Share |
|---|---:|---:|---:|
| revenue | 3,338 | 3,338 | 100.00% |
| ocf | 3,495 | 3,494 | 99.97% |
| capex | 3,213 | 3,213 | 100.00% |
| gross_profit | 1,295 | 1,295 | 100.00% |
| cost_of_revenue | 2,169 | 2,169 | 100.00% |

Exceptions (each explained by rule):

- ocf, CIK 1540684, 2022-03-31: TTM uses a later filing of the same year (0001493152-22-008045, 2022-03-29): a restatement or amendment

**Result: PASS** (100% apart from the listed exception). This tests the TTM arithmetic against the same filings; it does not test the filings or the concept choice (see check 3 and check 4).

## Check 3: jump review

TTM revenue moving more than 50% against 3 months earlier: 113 events at 53 companies. 30 sampled with a fixed seed and classified:

| CIK | Company | Month | TTM before → now ($m) | Change | Classification |
|---:|---|---|---|---:|---|
| 3570 | Cheniere Energy, Inc. | 2017-04-30 | 780 → 1,283 | +65% | real: LNG exports began 2016 (Sabine Pass) |
| 33213 | EQT Corp | 2022-10-31 | 4,323 → 7,858 | +82% | real: reported revenue includes derivative gains and losses (2021 hedging losses, 2022 reversal) |
| 40704 | GENERAL MILLS INC | 2021-06-30 | 18,626 → 2,189 | -88% | ERROR: annual 'Revenues' tag is about $2bn against roughly $18bn of sales; a partial line item ranks first |
| 80424 | PROCTER & GAMBLE Co | 2015-10-31 | 26,975 → 74,035 | +174% | ERROR (before the jump): the earlier 'Revenues' values (about $29bn) are a partial line; SalesRevenueNet is right |
| 100517 | United Airlines Holdings, Inc. | 2021-04-30 | 22,831 → 10,597 | -54% | real: COVID collapse in air travel |
| 813762 | ICAHN ENTERPRISES L.P. | 2021-05-31 | 6,123 → 9,567 | +56% | real: revenue includes investment gains and losses |
| 815097 | Carnival Corp Ltd. | 2021-07-31 | 832 → 141 | -83% | real: COVID shutdown of cruises, then reopening |
| 815097 | Carnival Corp Ltd. | 2022-03-31 | 655 → 3,505 | +435% | real: COVID shutdown of cruises, then reopening |
| 884887 | ROYAL CARIBBEAN CRUISES LTD | 2021-04-30 | 4,692 → 218 | -95% | real: COVID shutdown of cruises, then reopening |
| 884887 | ROYAL CARIBBEAN CRUISES LTD | 2021-10-31 | 218 → 584 | +168% | real: COVID shutdown of cruises, then reopening |
| 884887 | ROYAL CARIBBEAN CRUISES LTD | 2021-11-30 | 93 → 584 | +525% | real: COVID shutdown of cruises, then reopening |
| 906709 | NEKTAR THERAPEUTICS | 2018-08-31 | 321 → 1,374 | +328% | real: about $1bn upfront collaboration payment recognised in 2018 |
| 1065088 | EBAY INC | 2016-04-30 | 17,705 → 8,668 | -51% | real: PayPal spin-off in July 2015 (continuing operations restated) |
| 1090012 | DEVON ENERGY CORP/DE | 2021-08-31 | 4,503 → 6,814 | +51% | real: merger with WPX Energy (January 2021, all-stock) |
| 1335258 | Live Nation Entertainment, Inc. | 2021-03-31 | 4,513 → 1,861 | -59% | real: COVID cancellation of live events, then recovery |
| 1335258 | Live Nation Entertainment, Inc. | 2021-06-30 | 1,861 → 786 | -58% | real: COVID cancellation of live events, then recovery |
| 1335258 | Live Nation Entertainment, Inc. | 2021-08-31 | 786 → 1,288 | +64% | real: COVID cancellation of live events, then recovery |
| 1370637 | ETSY INC | 2020-10-31 | 877 → 1,378 | +57% | real: pandemic demand |
| 1404912 | KKR & Co. Inc. | 2020-05-31 | 4,221 → 2,032 | -52% | real: revenue includes investment income (Q1 2020 carried-interest reversal) |
| 1411579 | AMC ENTERTAINMENT HOLDINGS, INC. | 2021-08-31 | 449 → 875 | +95% | real: COVID cinema closures, then reopening |
| 1477449 | Teladoc Health, Inc. | 2021-05-31 | 867 → 1,367 | +58% | real: Livongo acquisition (October 2020) |
| 1527166 | Carlyle Group Inc. | 2021-02-28 | 1,880 → 2,935 | +56% | real: revenue includes performance allocations |
| 1527166 | Carlyle Group Inc. | 2021-05-31 | 2,935 → 6,118 | +108% | real: revenue includes performance allocations |
| 1551182 | Eaton Corp plc | 2017-11-30 | 87 → 311 | +257% | ERROR: annual 'Revenues' values are zero or tiny for a company with about $20bn of sales |
| 1585521 | Zoom Communications, Inc. | 2020-09-30 | 829 → 1,347 | +62% | real: pandemic demand |
| 1590895 | Caesars Entertainment, Inc. | 2021-08-31 | 4,700 → 7,168 | +53% | real: Eldorado-Caesars merger (July 2020) |
| 1635327 | Flutter Entertainment plc | 2019-03-31 | 1,312 → 2,029 | +55% | UNRESOLVED: annual-only data (fy to fy, 15-month gap) for a non-US filer; possible currency or comparative issue |
| 1682852 | Moderna, Inc. | 2020-11-30 | 106 → 247 | +133% | real: grants and vaccine-related revenue |
| 1811210 | Lucid Group, Inc. | 2022-08-31 | 84 → 182 | +115% | real: production ramp from a near-zero base |
| 1874178 | Rivian Automotive, Inc. / DE | 2022-11-30 | 514 → 1,049 | +104% | real: production ramp from a near-zero base |

**Result:** 26 real, 3 errors, 1 unresolved. Every case is classified, which is the check's pass rule. The errors share one cause: the concept ranked first for revenue (`Revenues`) holds a partial line item for some companies (General Mills, Eaton; P&G before 2015). That error is silent while it persists and shows as a jump only when the tag changes, so the jump review cannot measure how widespread it is. It affects revenue and therefore S2a's fallback (revenue - cost of revenue); H1 uses operating cash flow and capex, which have narrower concept lists, but the same kind of error cannot be ruled out without check 4.

# B5 pre-registration, addendum 2

Written 2026-10-16, after the owner's reviews at 13:34Z and 14:17Z and **before any H1 or S2a score, ranking,
return, NAV, Sharpe ratio or verdict has been computed**. It amends `B5_PREREGISTRATION.md` version 2 (sha256
`51acdd22…0d18`) and addendum 1 (`B5-V2-ADDENDUM-1`, sha256 `0ac28262…7595`); both stay unchanged and hash-frozen.
This file is registered by its sha256 as `B5-V2-ADDENDUM-2` (not counted; N stays 100). Any later edit fails
`research/tests/test_edge_rules.py`.

Every rule was set on input evidence only: SEC fact rows, and market cap and total assets as levels
(`research/edge_b5_input_audit.py`, report `equity/reports/research/edge/b5_input_audit.md`). No trial output was
computed or looked at. Registering this addendum does **not** authorise the trial run.

What does not change: the trial ids, N = 100, the DSR definition (addendum 1 §4), the gates P1-P11 and their
thresholds, the portfolio rules, the tranches, the benchmark and the costs. TTM check 4 stays open, so no result
can carry the E2 label (addendum 1 §6).

## 1. S2a revenue tests (replaces addendum 1 §1)

S2a uses the `GrossProfit` tag when its TTM end is at most 183 days old and it passes §2. Otherwise it may fall back
to revenue minus cost of revenue sharing one end at most 183 days old. The fallback is **unavailable** when any test
below fails. **No test ever substitutes a value**: the TTM revenue is always the one `equity.panel.ttm` selects
(best-ranked concept, latest filing per period); a failure only removes the row. A missing test result counts as a
failure.

**What is compared.**

- Concepts (us-gaap): `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet`,
  `SalesRevenueGoodsNet`, `SalesRevenueServicesNet`; (ifrs-full) `Revenue`, `RevenueFromContractsWithCustomers`.
  `RevenueFromContractWithCustomerIncludingAssessedTax` remains selectable but is **never a comparison**: it
  includes excise and similar taxes by definition.
- Period: identical start and end dates only. Different lengths are never compared.
- Currency: USD only (fact unit `USD`); other units are never loaded.
- Timing: only facts filed on or before the decision month-end.

**Tests.**

- **T0.** A revenue value used for any combined period is zero or negative.
- **T1.** In the **same filing** (accession number) that supplied a value used, another compared concept reports the
  identical period more than **1.10 times** higher (strictly greater).
- **T2.** As defined in §2, applied to revenue and, separately, to cost of revenue.
- 1.10 was set on the input distribution only: genuine same-basis gaps sit below 10% (taxes, rounding); the
  defects sit far above (General Mills 8.3×, P&G 2.8×, Eaton zero).

**Input-level examples.**

| Case | Test | Inputs | Verdict |
|---|---|---|---|
| General Mills 2021-06 to 2022-12 | T1 | Same 10-K: `Revenues` $2.19bn, contract revenue $18.1bn | True positive (partial line) |
| Conagra, Hasbro, Hershey, P&G | T1 | Same filing: $2.2bn v $17.7bn; $1.97bn v $4.45bn; $1.8bn v $7.1bn; $29.4bn v $83.1bn | True positives |
| Eaton 2015-01 to 2018-01 | T0 | `Revenues` reported as 0 | True positive |
| HP Inc 2016-03 | T2 | TTM $101.7bn mixes pre- and post-split bases; about $48bn on one basis | True positive |
| DuPont 2019-08 | T2 | TTM $85.4bn mixes pre- and post-separation bases | True positive |
| **General Dynamics 2017-18** | T1, T2 | An alternate concept tagged $27.4bn for a half-year (a mis-tag of the full year) | **Known false positive**: 18 rows lost |
| EQT, ConocoPhillips 2020-22 | T1 | `Revenues` includes derivative results; contract revenue does not | Basis difference, flagged (conservative) |
| **Abbott 2015-01** | none | About 10.6% basis mixing; its annual filing had restated for an unrelated reason, so §2 condition (b) passed it | **Known missed case** |

**Effect** (non-financial fallback rows, with §2 applied to the `GrossProfit` tag): 710 of 10,253 unavailable,
85 companies (T2 alone 185, T2 and cost-of-revenue T2 289, cost-of-revenue T2 alone 79, T1 90, T0 54, combinations
13). Every company is listed in the audit.

**Disclosure.** Every B5 trial report states these known limitations (General Dynamics false positive, Abbott
missed case, derivative-basis flags, the identity residuals in §3) in a fixed block written by the run script
(`edge_b5_run.KNOWN_INPUT_LIMITATIONS`); the block cannot be omitted.

## 2. T2: a TTM that mixes accounting bases, known at the decision date

A TTM built as annual + year-to-date − prior year-to-date mixes bases when the prior year-to-date value comes from
a later filing that recast it (spin-off, disposal, new standard) while the annual value is still on the old basis.

**Rule (point in time).** At decision month-end t, using only filings with `filed` ≤ t:

- (a) the prior-year year-to-date value used differs by more than 10% (either way) from another filing's value for
  exactly that period, under any compared concept of the metric; and
- (b) the annual filing that supplied the fiscal year did **not** itself recast its own prior year by more than 10%
  against that year's earliest value.

Both true: the TTM is flagged. A TTM that is a single fiscal year is never flagged.

**2.1 Timing.** Every value in (a) and (b) was filed on or before t, so the flag is known at the decision date and
later filings cannot change it. Evidence: a truncation check recomputed every flag for 6,249 rows (all 3,249 flagged
by any test plus 3,000 random others) from facts filed on or before each row's own month-end only: **0 differences**.
A synthetic test (`test_t2_is_point_in_time_later_filings_cannot_change_it`) shows that a restatement filed after t
does not flag month t.

**2.2 Where it applies (owner principle, 14:17Z).** Because it is contemporaneous, T2 filters the primary trials for
all four inputs: revenue and cost of revenue (S2a fallback), the `GrossProfit` tag (S2a), and operating cash flow and
capex (H1: either flagged means no FCF, so no G and no H1 for that month, nor for a score that needs it 12 months
later).

| Input | Rows in scope | Flagged at t (used) | Companies | Flagged only with later filings (diagnostic, **not used**) |
|---|---:|---:|---:|---:|
| Revenue (fallback rows) | 10,253 | 481 | 67 | 33 |
| Cost of revenue (fallback rows) | 10,253 | 381 | 62 | 10 |
| `GrossProfit` tag (fresh) | 14,687 | 171 | 28 | 53 |
| Operating cash flow (H1) | 38,375 | 824 | 144 | 14 |
| Capex (H1) | 38,375 | 503 | 78 | 2 |

Of the 171 `GrossProfit` rows, 169 fall back to revenue minus cost of revenue, and 123 of those fail §1, so 125 have
no S2a score. H1: 1,166 rows (956 non-financial, 182 companies) lose FCF; 37,209 remain.

**2.3 Retrospective diagnostic.** The same test using filings up to 2022-12-31 is reported (last column above) and
never filters a trial. Every point-in-time flag is also a retrospective flag (0 exceptions).

**2.4 Nature of the flags.** Most recast ratios sit between 1.10 and 2 (spin-offs and disposals: GE, Trane, FMC, Keurig
Dr Pepper, DuPont). Ratios of infinity (Entergy, EQT and Universal Health Services capex) mean one of the two filings
reported zero for the period. Both are treated the same: the TTM as assembled at t is internally inconsistent.

## 3. Company identity: rule C (replaces addendum 1 §3; owner preferred C, 14:17Z)

A deterministic company-identity rule is not reliable on free data: a rebrand and a successor issuer look the same,
and there are no listing dates.

**Rule C.** A company-month is unavailable to both trials when either holds:

1. its CIK is **1635327** (The Stars Group's 40-F accounts priced with Flutter's ticker FLUT); or
2. **mcap > 100 × total_assets**, strictly greater, both as of the row's own month-end:
   - `mcap` = (`shares_out` if > 0, else `shares_diluted`) × `close_raw` (`xsection.load`): the latest share count
     filed by the month-end, times the unadjusted month-end close;
   - `total_assets` = the monthly dataset's latest balance-sheet value filed by the month-end.

Missing or non-positive `total_assets`, or missing `mcap`: the ratio is undefined and rule C does not exclude the
row. Such a row still has no H1 or S2a score, because both require `total_assets` > 0 and the universe requires a
market cap. Code: `edge_b5.identity_ok` (`IDENTITY_RULE = "C"`). Regression tests: the strict threshold (100× kept,
100.0001× removed), missing, zero and negative assets, missing mcap, the audit's real cases (Medtronic, Atlas
Lithium and CIK 1635327 removed; Zoom 54×, Atlassian 39×, Curis 97×, BeOne 97× kept).

**Effect.** 160 rows, 16 companies: CIK 1635327 (39 rows) and 121 rows above 100× (15 companies, including the
domestic total-asset scale errors at Medtronic 2015 and Linde 2018-19). The highest genuine ratio seen is 54×
(Zoom, late 2020). The 20-F/40-F filers whose inputs look valid (Teva, CRH, James Hardie, NXP, CNH, Shopify,
Atlassian, Zai Lab) stay in.

**Residual risk (disclosed in every report).** Rows between 25× and 100× where errors and genuine values overlap stay
in: Curis (97×, price defect), BeOne (97×, ADS units) and Larimar (85×, CIK reused after Zafgen). Scinai (no total
assets) is unscorable under any rule.

## 4. Run definitions (made exact before the script exists)

- **Score panel.** Every company-month from 2012-01 of any company that is ever in the large band, so that H1's
  t-12 and t-24 inputs exist; scores use only values known at each month-end.
- **S2a rank.** Percentile rank of gross profitability within SIC group among that month's eligible names: large
  band, quality flag, close ≥ $1, a profitability value, not financial. P9 re-ranks with the point-in-time quality
  flag.
- **Non-overlapping t (P1, S2a).** The monthly excess series in date order, observations 1, 13, 25, …; mean ÷ (sample
  standard deviation, ddof 1, ÷ √n). Fewer than 3 observations: not available (P1 fails).
- **FF5 + momentum alpha (P3).** Each period's combined USD return is labelled with the calendar month of its start
  (execution) date and matched to that month's factors. Factor files are frozen copies cut at 2022-12
  (`research/edge/factors/`).
- **Run controls (§5 of the owner's review, 14:17Z).** `research/edge_b5_run.py`: registered ids only; the v2 and
  addendum hashes and an input-and-code manifest (`docs/edge/B5_RUN_MANIFEST.json`) checked before any data is read;
  owner authorisation recorded in `research/edge/status.json`; both trials in one invocation, each once; refusal if
  any result exists or the one-run lock exists; one fixed gate list; both primary results recorded before the shared
  DSR.

## 5. Survivorship

The universe needs a price, so companies that delisted before the 2026 price download are missing. Nothing here
bounds that bias; the −100% stress does not address companies missing from the universe. A passing exploratory
result is not proof of a deployable edge.

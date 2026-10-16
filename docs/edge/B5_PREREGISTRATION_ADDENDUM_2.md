# B5 pre-registration, addendum 2 (DRAFT, not yet registered)

Written 2026-10-16, after the owner's review at 13:34Z and **before any H1 or S2a score, ranking, return, NAV,
Sharpe ratio or verdict has been computed**. It amends `B5_PREREGISTRATION.md` version 2 (sha256 `51acdd22…0d18`)
and addendum 1 (`B5-V2-ADDENDUM-1`, sha256 `0ac28262…7595`); both stay unchanged and hash-frozen.

**Status: draft.** It is registered by hash, as `B5-V2-ADDENDUM-2` (not counted, N stays 100), only after the owner
has chosen the open points in §3 and §4. After registration any edit fails `research/tests/test_edge_rules.py`.

Every rule below was set on SEC fact rows, prices as a level (market cap) and total assets only, through
`research/edge_b5_input_audit.py` (report `equity/reports/research/edge/b5_input_audit.md`). No trial output was
computed or looked at.

What does **not** change: the trial ids, N = 100, the DSR definition (addendum 1 §4), the gates P1-P11, the
portfolio rules, the tranches, the benchmark and the costs. Check 4 stays open (addendum 1 §6).

## 1. S2a revenue tests (replaces addendum 1 §1; owner item 3)

S2a uses the `GrossProfit` tag when its own TTM end is at most 183 days old. Otherwise it may fall back to revenue
minus cost of revenue, sharing one end at most 183 days old. The fallback is **unavailable** when any test below
fails. No test ever picks a different value; a failure only removes the row. A missing test result counts as a
failure.

**What is compared.**

- Concepts (us-gaap): `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet`,
  `SalesRevenueGoodsNet`, `SalesRevenueServicesNet`; (ifrs-full) `Revenue`, `RevenueFromContractsWithCustomers`.
  `RevenueFromContractWithCustomerIncludingAssessedTax` is still a selectable revenue concept but is **never used as
  a comparison**: it includes excise and similar taxes by definition, so a gap against it is a basis difference,
  not a defect (it flagged Public Service Enterprise Group falsely).
- Period: the identical period, same start date and same end date. Different lengths are never compared.
- Currency: USD only. A value in another unit is not loaded (v2: non-USD reporters have no money values).
- Timing: only facts filed on or before the month-end.
- Basis: see the false positives below. A known basis difference that remains: for some energy producers
  `Revenues` includes derivative gains and losses while the contract-revenue concept does not. Those rows are
  flagged; this is accepted as conservative.

**Tests.**

- **T0.** A revenue value used for any combined period is zero or negative.
- **T1.** In the **same filing** (accession number) that supplied a value used, another listed concept reports the
  identical period more than 1.10 times higher. Same filing means same company, same document, same period and same
  basis of preparation, so a gap above 10% is two different line items, one of them partial.
- **T2 (mixed bases).** Applies when the TTM is built as annual + year-to-date − prior year-to-date. Fails when
  both hold: (a) the prior year-to-date value used differs by more than 10%, either way, from another filing's value
  for exactly that period under any compared concept (so the company later restated it, typically for a spin-off,
  a disposal or a new accounting standard); and (b) the annual filing used did **not** itself restate its own prior
  year by more than 10%. When (b) is false, the annual figure is already on the new basis and the TTM is consistent.
- **Cost of revenue.** T2 is applied to cost of revenue in the same way (`cor_restated`).
- 1.10 was chosen on the input distribution only: genuine same-basis differences sit below 10% (excise taxes,
  rounding), defects sit far above (General Mills 8.3×, P&G 2.8×, Eaton zero).

**Input-level examples (values read from the SEC fact rows in this audit).**

| Case | Test | Inputs | Verdict |
|---|---|---|---|
| General Mills 2021-06 to 2022-12 | T1 | Same 10-K: `Revenues` $2.19bn, `RevenueFromContract…Excluding…` $18.1bn | True positive: `Revenues` is a partial line |
| Conagra 2015-2017 | T1 | Same filing: $2.2bn against $17.7bn | True positive |
| Hasbro 2016-2018 | T1 | Same filing: $1.97bn against $4.45bn | True positive |
| Hershey 2015-01 | T1 | Same filing: $1.8bn against $7.1bn | True positive |
| Procter & Gamble 2015 | T1 | Same filing: $29.4bn against $83.1bn | True positive |
| Eaton 2015-01 to 2018-01 | T0 | `Revenues` reported as 0 | True positive |
| HP Inc 2016-03 | T2 | TTM $101.7bn: FY2015 before the HPE split plus restated year-to-date; consistent basis gives about $48bn | True positive |
| DuPont 2019-08 | T2 | TTM $85.4bn mixes pre- and post-Dow/Corteva separation; $20.7bn on one basis a year later | True positive |
| General Electric 2015-07 | T2 | TTM $147bn mixes the GE Capital exit bases | True positive |
| General Dynamics 2017-18 | T1, T2 | Alternate concept tagged $27.4bn for half-year 2017, a mis-tag of the full year | **False positive**: GD's own revenue was right; 18 rows lost |
| EQT, ConocoPhillips 2020-22 | T1 | `Revenues` includes derivative results; contract revenue does not | Basis difference, flagged (conservative) |
| Public Service Enterprise Group | was T1 | Gap only against the tax-inclusive concept | Fixed by excluding that concept from comparison |
| Pfizer 2021-05 | was T2 | FY2020 annual already on the post-Upjohn basis | Fixed by condition (b) |
| Abbott 2015-01 | none | About 10.6% mixing missed: its annual filing had restated for an unrelated reason, so (b) passed it | **Known false negative** |

**Effect** (non-financial fallback rows): 587 of 10,084 unavailable, 63 companies; T2 alone 175, T2 with cost of
revenue 176, cost of revenue alone 79, T1 90, T0 54, combinations 13. Every company is listed in the audit.

**Open decision (owner).** T2 is computed but **not yet applied** to (i) the `GrossProfit` tag path of S2a
(171 rows, 28 companies) and (ii) operating cash flow and capex in H1 (1,166 rows with a fresh common end, 956
non-financial, 182 companies). Applying it would treat these the same way as the fallback. Recommendation: apply
it to both, for consistency; the counts above are the cost.

## 2. Common period ends and staleness (owner items 1 and 2, approved in principle)

- H1: operating cash flow and capex must have the **same** TTM period end, at most 183 days old; otherwise H1 is
  unavailable for that row. No alignment is attempted (`edge_b5_inputs.fcf_inputs`, `align=False`). 1,546 of 40,217
  rows lose H1 this way.
- S2a: a `GrossProfit` value older than 183 days is never used. The revenue fallback is used only when its inputs
  pass §1. 2,587 stale rows: 1,855 fall back, 732 have no score.

## 3. Company identity (replaces addendum 1 §3 once chosen; owner item 4)

**Deterministic identity rule: not reliable on free data.** Tried: name changes, former names in the SEC company
file, filing gaps and ticker reassignments. A rebrand (Facebook to Meta) and a successor issuer (The Stars Group to
Flutter) look the same in this data, and the free data has no listing dates, so neither can be told apart by rule.

**Price-to-accounts plausibility.** Market cap above 100 times total assets: every such row in 2015-2022 is an
error (15 companies, 121 rows), including two domestic data errors that are otherwise scored
(Medtronic 2015 and Linde 2018-19, total assets loaded at the wrong scale). The highest genuine ratio seen is 54×
(Zoom, late 2020). Below 100× errors and genuine cases overlap (Curis 97×, BeOne 97×, Larimar 85× against Zoom
54×, Atlassian 39×), so no lower threshold separates them.

**Options (input evidence only):**

| Option | Rows removed | Companies | Invalid removed | Plausible removed | Other errors removed |
|---|---:|---:|---|---|---:|
| A: any 20-F/40-F balance sheet (addendum 1) | 339 | 13 | 5 of 5 | 8 (Teva, CRH, James Hardie, NXP, CNH, Shopify, Atlassian, Zai Lab) | 0 |
| B: CIK 1635327 only | 39 | 1 | 1 of 5 | 0 | 0 |
| C: CIK 1635327 + market cap > 100 × total assets | 160 | 16 | 4 of 5 (Scinai has no total assets, so no score under any option) | 0 | 12 companies |

Recommendation: **C**. It removes the one identity mismatch and every gross price-unit error, including the
domestic ones A and B leave in, while keeping the eight foreign filers whose inputs look valid. Residual risk under
every option: Curis, BeOne and Larimar (CIK reused after Zafgen) rows between 25× and 100× stay in.

Code: `edge_b5.identity_ok`, `IDENTITY_RULE` (now "A", addendum 1, until the owner chooses).

## 4. Run script (owner item 5; not written)

Written only after this addendum is registered. It will: take the two registered trial ids and nothing else; check
the v2, addendum 1 and addendum 2 hashes and the input-file hashes before reading data; run both trials in one
invocation, each exactly once, refusing if a result for either id already exists in the registry; apply every gate
from one list with no skip flag; write both results before the shared DSR; and keep check 4's E2 block. Its tests,
exact command and hashes come with it for approval before it is executed.

## 5. Survivorship

The universe needs a price, so companies that delisted before the 2026 price download are missing. Nothing in this
addendum bounds that bias; the −100% stress does not address companies missing from the universe.

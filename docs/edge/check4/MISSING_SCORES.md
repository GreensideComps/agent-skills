# Check 4 sampling frame: why eligible company-months have no score

Owner request 20 Oct 2026 (item 3). Analysis only: no Check 4 sample was drawn, no source value extracted, no score
filled or imputed, and no frozen Run 2 rule changed.

**Command:** `python3 research/check4/missing_scores.py --frozen <a4a07d7 checkout> --out docs/edge/check4`
(about 2.5 minutes; run twice, output byte-identical, sha256 `7152289a16bf58e90ba97ee1bdd4662eeb551b91bbdc924901cf3b61c18ec4af`).
It verifies the frozen checkout and the 26 manifest files first, rebuilds the panel with the same frozen functions as
`reconstruct_holdings.py`, recomputes the frozen intermediates (`edge_b5.h1_velocity`, `s2a_profitability`,
`identity_ok`) and gives each unscored row the **first** step of the frozen formula that fails, in the formula's own
order. Full counts, per year, per SIC group and the eight companies with most rows per reason are in
`missing_scores_summary.json`.

**Population:** decision months 2015-01 to 2022-11; large band; point-in-time quality rule passed; close >= $1;
non-financial. These are the rows the engine would rank if they had a score.

| | H1 | S2a |
|---|---|---|
| Scored (in the frame) | 25,176 | 23,678 |
| Unscored (outside the frame) | **8,924** (26.2%) | **10,422** (30.6%) |
| Per decision month, mean | 93.9 | 109.7 |
| Companies unscored at least once | 540 | 321 |
| Companies never scored in the window | 101 | 144 |
| Rows no classifier step explains | **0** | **0** |

Tests: `test_missing_scores.py` (14) checks on random synthetic panels that every row the frozen score leaves NaN
gets a named reason and no scored row gets one, for both trials.

## H1 (free-cash-flow acceleration): 8,924 rows

| Reason (first failing step) | Rows | Companies | Kind |
|---|---|---|---|
| OCF or capex not found in the SEC facts | 1,761 | 98 | input absent |
| TTM FCF period ended > 183 days before | 257 | 25 | rule |
| Identity rule C | 59 | 9 | rule |
| OCF or capex restated flag (T2, fail closed) | 940 | 148 | rule |
| No row 12 months earlier | 239 | 49 | rule (history) |
| FCF 12 months earlier unavailable | 1,498 | 235 | inherits: restated 981, input absent 397, stale 96, identity 24 |
| Shares or split factor undefined at t-12 | 210 | 27 | input absent |
| Share count changed > 3x (share guard) | 46 | 16 | rule |
| TTM periods at t and t-12 not 350-380 days apart | 1,317 | 341 | rule |
| G 12 months earlier unavailable (needs 24 months) | 2,597 | 419 | inherits: mostly the t-12 row's own FCF or period gaps |

By kind: rule 2,858; input absent 1,971; inherited 4,095. H1 needs three aligned annual FCF periods (t, t-12, t-24),
so one gap removes up to two later years of scores: that multiplier is why inherited rows are the largest group.

## S2a (gross profitability): 10,422 rows

| Reason | Rows | Companies | Kind |
|---|---|---|---|
| Identity rule C | 128 | 16 | rule |
| Total assets missing or not positive | 365 | 10 | input absent |
| No gross profit and no revenue + cost of revenue | 6,303 | 160 | input absent |
| Every gross-profit route stale (> 183 days) | 485 | 29 | rule |
| GrossProfit restated (T2) and no fallback | 125 | 23 | rule |
| No fresh GP; revenue and cost periods end differently | 2,435 | 79 | rule |
| No fresh GP; revenue fails T0-T2 or cost restated | 581 | 63 | rule |

By kind: rule 3,754; input absent 6,668. S2a is a point-in-time single-period score, so nothing is inherited.

## Expected behaviour versus possible input-data problems

**Expected (the frozen rules working as registered):** stale periods, mismatched period ends, restated and
revenue-conflict flags (fail closed by ADDENDUM_2), the identity rule, the share guard, and short history. These
6,612 rows (H1 2,858, S2a 3,754) plus most inherited H1 rows are by design.

**Input absent: cannot be classified without a source check.** "Not found in the SEC facts as captured" covers two
different things that the data alone cannot separate:
- *The company does not report the line.* Expected for some business models: utilities, airlines, restaurants and
  many service companies present no cost-of-revenue or gross-profit line. S2a's 6,303 rows are concentrated there
  (transport/utilities/telecom 3,187; services 1,287), e.g. American Electric Power, Entergy, Eversource, Delta,
  McDonald's, all with 95 of 95 months unscored.
- *The company reports it but the capture missed it* (tag not mapped, foreign-form filer, or a parsing gap). This
  is a possible data problem. The strongest signs:
  - H1 "OCF or capex not found" includes Eli Lilly, Automatic Data Processing, NextEra Energy and DTE Energy for all
    95 months. Every one of these files cash-flow statements with operating cash flow and capital spending, so these
    are very likely capture gaps (probably capex reported under a tag outside the mapped set), not genuine absence
    [inference, not checked against filings].
  - Canadian Pacific Kansas City, Enbridge and Imperial Oil (Canadian filers) lack total assets or cash-flow items
    for most of the window: probably foreign-form coverage, not a business-model absence [inference].
  - Some "rule" rows are persistent enough to look like a capture issue rather than a timing difference: AT&T,
    Workday, Corpay and Williams have revenue and cost-of-revenue period ends that differ in 85-95 months.

## What this means for the sampling frame

1. The frame is the set the engine ranked. Check 4, as written in PR #21, tests whether the source values behind
   **scored** rows are right. It cannot see a company the capture dropped, because that company has no rank,
   decile or holding status to stratify on.
2. The unscored set is large (26-31% of eligible rows) and **not random**: it is concentrated in utilities,
   transport, telecom and services, and includes some of the largest US companies. If the "input absent" rows are
   mostly capture gaps, the B5 universe was narrower and differently composed than the registered universe rule
   intended. That would be a coverage limitation of Run 2 itself, separate from value accuracy.
3. It does not make the reconstruction wrong: the reconstruction reproduces what the frozen engine did, gaps
   included. It also cannot change the recorded verdicts, which already failed.

## What can and cannot be assessed for unscored rows

| Question | Assessable? |
|---|---|
| Which frozen step removed the row | Yes, for every row (this analysis) |
| Whether the input truly is absent from the filing | Only with an independent source check of a sample of "input absent" rows; not done (it is extraction) |
| Whether the row would have been held | No. It would need a score computed from source values, i.e. a counterfactual re-scoring. That is new analysis on the exploration data, not part of Check 4, and needs separate approval |
| Effect on Run 2's results | No, for the same reason; and the verdicts already failed |

## Options for the owner (nothing done)

- **A (recommended):** keep the Check 4 frame as scored rows only, as PR #21 states, and add a separate, small,
  descriptive coverage stratum: e.g. 1 company-month per year from the "input absent" rows, checked only for
  "is the input present in the filing: yes or no". It estimates the capture-gap rate without scoring anything.
- **B:** record the coverage gap as a Run 2 limitation only, with no sampling of unscored rows.
- **C:** treat it as a data fix for future work (map the missing tags) under a separate proposal; it would not
  touch Run 2.

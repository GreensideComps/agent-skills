# TTM check 4: independent-source verification procedure (proposal)

Status: **PROPOSAL, not adopted.** This file only proposes the procedure. It runs nothing, and it does not change
`research/edge/status.json` (`ttm_check4_independent_source.complete` stays `false`), any gate, the registry or
any B5 file. Owner decision O6 (owner message `cmsg_01U4KMvkBYNknqm4HRVie8uv5WhbXFRm6KFGKqgHWHri4W`, 2026-10-19
14:36Z) asked for a Check 4 procedure that names who or what source performs it. Under O6, Check 4 is never marked
complete just because tests pass.

Background: Checks 1-3 test the TTM arithmetic and data handling against the same SEC data the pipeline reads.
They cannot catch a wrong concept choice or a value the aggregation got wrong (B5 pre-registration §8, Addendum 1 §6,
on PR #19's branch). While Check 4 is open, no result carries the E2 label and no confirmation pre-registration can
be registered. Neither B5 trial passed its gates in run 2 (D31/D32), so Check 4 blocks nothing today. It will matter
for any later trial built on the same inputs.

## 1. What is verified

| Trial input | Concepts compared |
|---|---|
| H1 (FCF per share acceleration) | operating cash flow, capital expenditure, total assets |
| S2a (gross profitability) | gross profit, revenue, cost of revenue, total assets |

Each compared value is the one the pipeline used **as of the decision date** (point in time). It is compared with
the value in the filing the pipeline attributes it to (the `accn` accession number), and the TTM sums are rebuilt
from those filings.

## 2. Independent source and its limits

- **Source:** the original filed 10-K / 10-Q documents on SEC EDGAR, meaning the primary statement pages read from
  the filing index for that accession number. This is not the `companyfacts` JSON aggregation the pipeline uses.
- **What it catches:** wrong concept mapping (for example a "Revenues" tag picked over the face-statement total),
  sign and scale errors, wrong period attribution, the wrong filing used at the decision date, and aggregation or
  TTM-assembly errors.
- **What it cannot catch:** an error the company itself filed (the statement page and the XBRL come from the same
  filer), or survivorship bias. A truly separate vendor would need paid data, which O7 rules out; this limitation is
  stated in any Check 4 result.

## 3. Sample (fixed before looking)

- **Seed:** `20261019`, published here, before any value is drawn.
- **Per trial: 40 company-quarters**, five per decision year 2015-2022. In each year:
  - 3 drawn from names the trial actually held (top-20 portfolio) at a decision date that year;
  - 2 drawn from the eligible, unheld universe, one from each extreme decile of the trial's score.
- **Sampling within strata:** sorted by (ticker, decision date), then drawn with `random.Random(20261019 + k)`,
  where k is the trial index (0 = H1, 1 = S2a). A drawn company-quarter with no matching filing on EDGAR is replaced
  by the next draw, and each replacement is logged.
- **Out of scope:** no decision after 2022-11 (the exploration window). The 2023-26 holdout is not touched.
- Total: 80 company-quarters, about 230 compared values (3 or 4 concepts per draw, plus the rebuilt TTM figures).

## 4. Who performs it

1. **Extraction, agent A:** reads each filing and records the value, page, line label, period and units. Agent A
   **does not see** the pipeline's value.
2. **Second extraction, agent B:** a separate session does the same blind extraction for every value. Any A/B
   disagreement is resolved from the filing, and the resolution is recorded with the page reference.
3. **Comparison:** a script compares the extracted values with the pipeline's values. For each mismatch it re-scores
   that decision date with the filed value and reports whether the top-20 holdings would change.
4. **Owner review:** the owner reviews the evidence pack, which lists every draw, both extractions, every mismatch
   and its holding effect. Only the owner records Check 4 complete, as a separate reviewed change to
   `status.json` that names the owner message.

## 5. Acceptance (stated in advance)

Check 4 passes for a trial's inputs only if **all** of these hold:

- fewer than **2%** of compared values differ from the filing by more than **1%** (relative);
- **no** mismatch changes a top-20 holding at any sampled decision date;
- no systematic pattern in the mismatches: the same concept or sector wrong in 3 or more draws counts as a
  systematic error, whatever the overall rate.

If it fails, Check 4 stays open. The report names the failing concept or filings and proposes a pipeline fix, which
needs its own review, and the affected results keep their current labels.

## 6. Permission

Running this procedure is data-quality work (O5's non-experimental category). It runs no performance experiment,
changes no gate and reads no holdout data. It still starts only after the owner approves this procedure, because the
outcome feeds a gate (the E2 label). It reads B5 inputs that live on PR #19's branch. Per O3, B5 stays read-only,
so the procedure writes its evidence pack under `docs/edge/check4/` on its own branch.

## 7. Open points for the owner

- Accept the five-per-year stratification, or ask for a larger sample (for example 60 per trial).
- Accept "same filer, different artefact" as the independent source, given O7 (no paid data).
- Confirm the tolerance (2% of values off by more than 1%, zero holding changes).

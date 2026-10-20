# TTM check 4: independent-source verification procedure (proposal, revision 2)

Status: **PROPOSAL, not adopted, not performed.** This file runs nothing and changes no research status, gate,
registry or B5 file. `research/edge/status.json` keeps `ttm_check4_independent_source.complete = false`. No
independent verification has taken place. Only the owner can adopt this procedure, and only the owner can record
Check 4 complete, after the procedure has been performed and its evidence reviewed. Under O6 (owner message
`cmsg_01U4KMvkBYNknqm4HRVie8uv5WhbXFRm6KFGKqgHWHri4W`, 2026-10-19 14:36Z), Check 4 is never marked complete because
tests pass.

Revision 2 (owner review request, 2026-10-19 15:24Z) defines the sampling unit, the error denominator, the seeded
selection, the handling rules, adjudication, classification, failure handling and limits. Section 11 lists the
points that need an owner decision.

## 1. Why the check exists

Checks 1-3 test the TTM arithmetic and data handling against the same SEC `companyfacts` data the pipeline reads.
They cannot catch:
- a wrong concept choice;
- a value the aggregation recorded wrongly;
- a filing used before it was public.

See B5 pre-registration §8 and Addendum 1 §6 on PR #19's branch. While Check 4 is open, no result carries the E2
label, and `edge_registry.append` refuses a confirmation batch. Neither B5 trial passed its gates in run 2
(D31/D32), so Check 4 changes no current verdict. It matters for any later trial that uses the same inputs.

## 2. Definitions: sampling unit and denominator

- **Sampling unit: a company-decision.** One trial, one company (SEC CIK), and one monthly decision date between
  2015-01 and 2022-11. It stands for the point-in-time inputs that trial used for that company on that date.
  (Revision 1 called this a "company-quarter". A decision uses the latest TTM known at the month-end, so the
  decision date is the honest unit.)
- **Compared value:** one filed fact the pipeline used. For each input, `edge_b5_inputs.ttm_input` names the fact
  rows it combined:
  - the FY value alone (basis `fy`); or
  - FY + current YTD − prior-year YTD (three rows);
  - total assets is a single balance-sheet (instant) fact.

  Each fact row has a concept, a period, a value and an accession number (`accn`), and each row is one compared
  value.
  - H1 uses operating cash flow, capex and total assets: 3 to 7 facts per company-decision.
  - S2a uses gross profit, revenue, cost of revenue and total assets: 4 to 10 facts per company-decision.
- **Denominator for the 2% threshold:** the number of compared filed facts for that trial, counted after
  adjudication and excluding facts marked unresolvable (§5.5). Unresolvable facts are counted and reported
  separately.
- **Value error:** the pipeline's fact differs from the filed figure by more than **1% of the filed figure**, after
  both are put in the same units (§5.2). If the filed figure is zero, any non-zero difference counts.
- **Derived checks, reported but outside the 2% denominator:**
  - each rebuilt TTM figure (from the filed facts, using the pipeline's own arithmetic);
  - each trial input (FCF per share for H1, GP over total assets for S2a).

  A derived figure that is wrong when every fact is correct is an arithmetic defect. It fails Check 4 outright
  (§8).

## 3. Sample size and the strength of the evidence

There are 40 company-decisions per trial (80 in total), which gives about 150 to 300 compared facts per trial.

The pass rule uses the observed rate (under 2%), but a pass is weak evidence.

**The interval is descriptive, not a confidence statement about the population** (owner, 2026-10-20). The facts are
not independent draws: the 3 to 10 facts of one company-decision share a filing, a filer's tagging habits and often
the same concept mapping, so an error in one tends to come with errors in the others. The Clopper-Pearson bound
treats every fact as an independent trial, so it understates the uncertainty. With 40 company-decisions per trial,
the effective sample size is nearer 40 than 250. For illustration only, on the independence assumption:
- with 250 facts and 0 errors, the one-sided 95% Clopper-Pearson upper bound is about 1.2%;
- with 4 errors (1.6%), it is about 3.6%.

The report therefore:
- states the observed fact-level rate and, next to it, the exact one-sided Clopper-Pearson 95% upper bound,
  labelled "descriptive: assumes independent facts, which they are not";
- states the company-decision-level count as well (company-decisions with at least one value error, out of 40),
  with its own Clopper-Pearson bound; with 0 of 40 that bound is about 7.2%, which shows how little 40 units can rule
  out;
- never calls either bound a confidence level for the population error rate, and never claims that the population
  error rate is below 2%.

None of this changes the sample, the strata or the decision rules in §4 and §8, which stay as fixed in advance.

## 4. Selection and stratification (reproducible from seed `20261019`)

1. **Frame.**
   - For each trial and each decision date, the frame is every company that was eligible under the trial's rules
     (at least $10bn, price at least $1, financials excluded, input available).
   - Each frame row carries:
     - the trial's score decile at that date;
     - whether the company was held in the trial's top-20 portfolio after the buffer and sector-cap rules.
   - Run 2 did not record holdings, so they must be **reconstructed**. Section 11, item 1, covers how.
   - The frame is written to `docs/edge/check4/frame_<trial>.csv` and its sha256 is recorded before any draw.
2. **Strata.** For each trial, decision year (2015-2022) and stratum:
   - `held`: 3 per year, drawn from held company-decisions;
   - `top`: 1 per year, drawn from eligible, unheld company-decisions in the top score decile;
   - `bottom`: 1 per year, drawn from the bottom score decile.

   That gives 8 years × 5 = 40 per trial.
3. **Draw.**
   - Sort each stratum's rows by (CIK, decision date).
   - Shuffle a copy with `random.Random(f"20261019:{trial_id}:{year}:{stratum}").shuffle(rows)`. This uses Python's
     version 2 string seeding, which is deterministic across runs and platforms.
   - Take rows in that order. One company appears at most once per trial per year.
   - If a draw's filing cannot be retrieved from EDGAR, it is skipped, logged with its reason, and the next row in
     the order is taken. The final draws and every skip are written to `docs/edge/check4/draws_<trial>.csv`, with
     the frame hash.
4. **Reproducibility test.** Before extraction, the draw script runs twice and must produce byte-identical draw
   files. The owner receives both hashes.

## 5. Handling rules (written before extraction, applied the same way by both extractors)

1. **Source document.** The filing with the pipeline's accession number, read from its EDGAR filing index. The
   source is the primary statement (income statement, cash flow statement or balance sheet) in the main document,
   not the XBRL. Exhibits and press releases are not used.
2. **Units and scale.**
   - The extractor records the figure as printed, plus the statement's scale ("in thousands", "in millions") and
     currency.
   - The comparison converts both sides to units of one in the reporting currency.
   - A wrong scale or currency is a units error, whatever its size.
3. **Restatements.**
   - The check is point in time. The reference is the figure as first filed in that accession, which is what an
     investor could have known at the decision date.
   - If a later filing restated the figure, that is recorded as `restated_later`. It is not a pipeline error.
   - If the pipeline used a figure from a filing dated after the decision date, that is a point-in-time error (a
     look-ahead), whatever the value.
4. **Missing data.**
   - The pipeline has a fact but the filing has no matching line: concept-mapping error.
   - The pipeline marked an input unavailable but the filing shows it clearly: coverage miss. Coverage misses are
     counted in a separate rate, because they change eligibility rather than a value.
5. **Ambiguous disclosures.** These are cases with no single face-statement line for the concept. Examples:
   - no gross-profit line;
   - capex split across several lines;
   - revenue shown net of excise duties in one place and gross in another.

   The extractor marks the value `ambiguous`, cites every candidate line and does not choose. The adjudicator
   decides using the rulebook below. Anything still undecided goes to the owner, and if the owner leaves it
   undecided it is recorded `unresolvable`. If more than 10% of a trial's facts end up unresolvable, the check for
   that trial is **inconclusive**, which is not a pass.

   **Rulebook (fixed before extraction):**
   - **Capex:** the "purchases of property, plant and equipment" line or lines in investing cash flow; capitalised
     software only if the filer reports it within that line.
   - **Revenue:** the face-statement total revenue line.
   - **Gross profit:** printed gross profit if shown; otherwise revenue minus cost of revenue, recorded as a
     derived value, and only when both lines are printed.
   - **Total assets:** the balance-sheet total.
6. **Signs.** Capex and costs are compared as absolute values. An inverted sign in a derived figure is a sign
   error.

## 6. Blind double extraction and adjudication

1. Two separate agent sessions, A and B, each receive only the draw list (CIK, form, accession, period, concept
   names). Neither sees the pipeline's values or the other's output.
2. Each records:
   - the value as printed;
   - scale, currency and period;
   - page or section, and the line label;
   - a `confidence` flag.
3. **A versus B.** They agree if the values match exactly at the printed precision, with the same period and the
   same unit. Any disagreement goes to adjudicator C (a third session). C sees both extractions and the filing,
   but still not the pipeline value, and records a decision with its citation.
   - The A/B agreement rate is reported.
   - If A and B disagree on more than 10% of facts, the extraction itself is unreliable. The check stops, and the
     rulebook is revised and the extraction repeated **before** any comparison with the pipeline.
4. **Only after adjudication** are the agreed values compared with the pipeline.
5. The owner reviews every adjudication and every error. The owner's review is mandatory and cannot be delegated
   to an agent.

## 7. Classification of every error

Each error record carries:
- trial;
- concept (field);
- CIK and ticker;
- fiscal period and decision year;
- form and accession;
- the filed and pipeline values;
- relative and absolute difference;
- an error class, one of:
  - concept mapping;
  - units or scale;
  - sign;
  - period attribution;
  - point-in-time (look-ahead);
  - TTM arithmetic;
  - coverage miss;
- the **holding effect**: the trial's score is recomputed for that decision date with the corrected input, and the
  record says whether the company's top-20 membership changes after the buffer and sector-cap rules (yes, no, or
  not computable).

The report tabulates errors by field, company, year and class.

## 8. Decision rules (all stated in advance)

For each trial's inputs, Check 4 **passes** only if every condition holds:

1. Value errors are under 2% of the denominator in §2. The report also gives the descriptive bounds in §3.
2. No error changes a top-20 holding.
3. There are no point-in-time errors and no TTM arithmetic defects. Either one fails the check outright, at any rate.
4. There is no systematic pattern. A pattern is any of these:
   - the same class and concept in 3 or more draws;
   - 2 or more errors in one company across different years;
   - more than half of all errors in one decision year or one sector.
5. Coverage misses are under 5% of company-decisions.
6. The result is not inconclusive under §5.5 or §6.3.

**If it fails:**
- Check 4 stays open.
- The report names the failing class, concept and filings.
- It proposes a pipeline fix, and that fix needs its own review and its own tests.
- No existing result is relabelled and no result is rescored by this procedure.
- The failure stays on record.

## 9. No expansion after a failure

The sample is **not** expanded after a failure. Adding draws until the rate falls under 2% would be optional
stopping. After a failure, the only route to completing Check 4 is:
1. a reviewed pipeline fix;
2. then a new run of this procedure with a **new** seed and a sample size set in advance (larger if the owner wants
   it).

Every earlier run is reported alongside the new one. Extra draws to understand a systematic error already found
may be taken, but they are diagnostic only and never count toward a pass.

## 10. Limits (stated in any Check 4 result)

- **Same filer.** The statement page and the XBRL both come from the company. An error in the filing itself, or a
  later restatement, is not caught as an error here; restatements are only recorded (§5.3).
- **Survivorship bias is untouched.** The frame contains only companies in the free Yahoo/SEC universe, and
  delisted firms are missing. Check 4 says nothing about that bias, which stays material and unbounded.
- **Agent extraction is not a human audit.** Blind double extraction and owner review reduce extraction error but
  do not remove it.
- **Sample size.** 40 company-decisions per trial gives weak bounds (§3). A pass is "no evidence of a material
  input error at this sample size", not proof of accuracy.
- **Holdings are reconstructed** (§4.1), so the holding-effect test depends on that reconstruction being faithful
  to run 2. Run 2 did not record holdings, so the reconstruction cannot be checked against them directly.

## 11. Decisions needed from the owner before this can run

1. **Holdings reconstruction.** The `held` stratum and the holding-effect test need each trial's top-20 holdings
   per decision date, and run 2 did not record them. Proposal:
   - run only the selection step of the frozen run-2 code (eligibility, ranking, buffer, sector cap) at commit
     `a4a07d7`, writing holdings per date;
   - **no returns, NAV, Sharpe or gate statistic is computed or read**.

   This re-executes part of a registered trial's code on scoring inputs, so it needs explicit approval. If it is
   not approved, the fallback is to stratify by score decile only and report the holding effect as the change in
   rank, a weaker test.

   **Approved by the owner on 2026-10-20** (message `cmsg_01U4KMvkBYNknqm4HRVie8uvWBGcbQVLRwVrW8HKHTK5JK`), solely to
   build the frame and test the holding effect, with the frozen run-2 code, inputs and configuration; no returns or
   statistics; no change to any run-2 report, registry entry, verdict, authorisation history, lock archive, gate or
   B5 status; every holding labelled reconstructed; missing inputs and uncertainty reported; stop if the selection
   cannot be reproduced reliably. Source extraction does not start until the owner has reviewed the
   reconstruction.
2. **Accept** the stratification (3 held, 1 top, 1 bottom per year) and the size of 40 per trial, or set a larger
   size.
3. **Accept** "same filer, different artefact" as the independent source, given O7 (no paid data).
4. **Confirm** the tolerances: under 2% of facts off by more than 1%; zero holding changes; zero look-ahead or
   arithmetic defects; coverage misses under 5%; unresolvable facts at most 10%; A/B disagreement at most 10%.
5. **Confirm** that performing the procedure counts as O5 non-experimental data-quality work, so that it needs this
   approval and nothing more. It runs no performance experiment, changes no gate and reads no holdout data
   (decisions after 2022-11 are out of scope).

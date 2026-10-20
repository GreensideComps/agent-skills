# Portfolio manager pm-1.0: specification (fixed before implementation, owner decision D-T16)

Scope:
- A proposal-only component, `office/office/pm.py`. It cannot submit orders or alter holdings: it imports no broker
  code and returns a record.
- Proposals are recorded in the office log as `pm_proposal` task outputs.
- Changing any rule below makes a new version (pm-1.1, ...). Old proposals keep the version they were made under.

## 1. Eligibility: what may hold weight outside VWRP

- A strategy is eligible only if **both** of these hold:
  1. it is listed in `office/config/pm_eligible.json` with the owner's decision id;
  2. every trial id it cites has a passing gate verdict in `research/edge/trials.jsonl`.
- The file ships empty. Stage 2 and B5 both failed, so today **every proposal is 100% VWRP**, the documented no-trade
  outcome.
- An ineligible or unverifiable strategy gets weight 0, and the proposal records why.

## 2. Constraints, checked in code on every proposal

| Constraint | Definition | Limit |
|---|---|---|
| Outside VWRP | sum of satellite weights | ≤ 20% of the book |
| Per company (direct) | weight of one satellite holding | ≤ 5% |
| Per company (look-through, reported) | direct weight + core weight × the company's VWRP weight | reported; flagged if > 5% |
| Sector (look-through) | portfolio sector weight minus VWRP sector weight, where portfolio sector weight = core × VWRP sector weight + satellite weights in that sector | active over- or under-weight ≤ 10 percentage points |

**Why the sector limit is active, not absolute.** VWRP itself holds roughly 25% in technology [A]. An absolute 10% cap
would reject the 100% VWRP default. pm-1.0 therefore applies the 10% limit to exposure **relative to VWRP**,
measured with look-through. This interpretation is recorded for the owner to confirm or change.

A proposal that breaks any limit is not scaled down automatically. It is rejected, with the breach shown, and the
100% VWRP default stands.

## 3. Sector classification

- **Satellite holdings:** the SEC SIC code mapped to 11 top-level sectors, using the table in
  `office/office/sectors.py`. The table is an approximation of ICB/GICS industries; there is no free GICS source.
- **VWRP look-through:** sector weights and top holdings from a dated input file,
  `office/config/vwrp_lookthrough.json`, copied from Vanguard's published fund data with its source and as-of date.
- **Flags:**
  - **unverifiable:** the file is missing, older than 95 days, or entered without a source;
  - **classification mismatch:** VWRP's provider sectors (FTSE/ICB) and the SIC mapping are different systems, and
    the sector names are matched by a fixed table;
  - **unknown sector:** the company has no SIC code (it is not an SEC filer).
- With satellites, a sector check that cannot be computed (no look-through data, or a holding with an unknown
  sector) counts as failed, so the proposal is rejected and the 100% VWRP default stands. Stale or unsourced data
  is shown as unverifiable beside the numbers.
- With no satellites, no sector check can fail, so the default proposal needs no look-through data. The flag still
  shows when that data is missing.

## 4. Relative-performance review threshold (−15%)

This is not a trading trigger and not a protection. It only opens a review.

- **Measured:** at each month-end close (UTC date of the last close), from the satellite sleeve's inception.
- **Returns:** the satellite sleeve's return R_s and VWRP's total return R_v over the same dates, in GBP.
  VWRP is accumulating; the sleeve's prices are price-only unless dividends are recorded, and this is flagged.
- **Calculation:** relative = (1 + R_s) / (1 + R_v) − 1, computed on two windows:
  - the trailing 12 months, or since inception if shorter;
  - since inception.
- **Threshold:** relative ≤ −15% on either window.
- **Escalation:**
  1. The proposal records a `review_threshold` breach with both numbers and their inputs.
  2. A critical alert appears in the digest.
  3. An owner-review item is recorded.
  4. The proposal itself is unchanged. No weight moves until the owner decides.
- With no satellite sleeve, the check reports "not applicable".

## 5. What every proposal record shows

- the version, the time, and the evidence it used (trial ids, gate verdicts, file hashes);
- target weights, each with its reason;
- every constraint: its inputs, the arithmetic, the limit and pass/fail;
- flags for anything unverifiable;
- "no trade" when the target equals the current core.

# Portfolio manager pm-1.0: specification (fixed before implementation, owner decision D-T16)

Scope:
- A proposal-only component, `office/office/pm.py`. It cannot submit orders or alter holdings: it imports no broker
  code and returns a record.
- **Not yet wired:** recording proposals in the office log as `pm_proposal` task outputs, and the digest alert of
  §4. Adding a task type during the 14-day gate would change the system under test, so this waits for the gate or
  the owner. Until then a proposal is printed by `python3 -m office pm-propose`.
- Changing any rule below makes a new version (pm-1.1, ...). Old proposals keep the version they were made under.

## 1. Eligibility: what may hold weight outside VWRP

- A strategy is eligible only if **both** of these hold:
  1. it is listed in `office/config/pm_eligible.json` with the owner's decision id;
  2. every trial id it cites is registered as a trial with exactly one result in `research/edge/trials.jsonl`,
     and that result is a pass (a trial re-run after a failure is refused).
- The file ships empty. Stage 2 and B5 both failed, so today **every proposal is 100% VWRP**, the documented no-trade
  outcome.
- An ineligible strategy gets weight 0, and the proposal records why.

## 2. Constraints, checked in code on every proposal

| Constraint | Definition | Limit |
|---|---|---|
| Outside VWRP | sum of satellite weights | ≤ 20% of the book |
| Per company (direct) | weight of one satellite holding | ≤ 5% |
| Per company (look-through, reported) | direct weight + core weight × the company's VWRP weight | reported; flagged if > 5% |
| Sector (look-through) | portfolio sector weight minus VWRP sector weight, where portfolio sector weight = core × VWRP sector weight + satellite weights in that sector | active over- or under-weight ≤ 10 percentage points |

**Why the sector limit is active, not absolute.** VWRP itself holds 34.1% in technology (Vanguard, 31 Aug 2026) [V]. An absolute 10% cap
would reject the 100% VWRP default. pm-1.0 therefore applies the 10% limit to exposure **relative to VWRP**,
measured with look-through. **Confirmed by the owner, 20 Oct 2026 12:19Z (cmsg_01U4KMvkBYNknqm4HRVie8uvFVThkjb4nfMtWxVvYtRTrB):**
"±10 percentage points relative to VWRP, measured using look-through sector exposure. The 100% VWRP default should
pass its active-sector checks. If holdings data is missing or stale, mark the check as unverified rather than
passing it."

**Check results.** Every check has one of three statuses, and every record shows its calculation and evidence (the
look-through source, as-of date, age and weight sum):
- **pass:** within the limit, on verified data;
- **fail:** outside the limit (on any data);
- **unverified:** within the limit only on missing, stale, unsourced or unmapped data, or a holding has no sector.
  An unverified check never counts as a pass.

There is one row per sector (all 11), so the 100% VWRP default shows each active weight as exactly 0.

**Weights:** every satellite weight must be a finite number in (0, 1]; there are no shorts. Holdings are added up per
company (normalised ticker) across strategies before the per-company limit is checked.

A proposal that breaks any limit is not scaled down automatically. It is rejected, with the breach shown, and the
100% VWRP default stands.

## 3. Sector classification

- **Satellite holdings:** the SEC SIC code mapped to 11 top-level sectors, using the table in
  `office/office/sectors.py`. The table is an approximation of ICB/GICS industries; there is no free GICS source.
- **VWRP look-through:** sector weights and top holdings from a dated input file,
  `office/config/vwrp_lookthrough.json`, copied from Vanguard's published fund data with its source and as-of date.
- **Flags:**
  - **unverified:** the file is missing, older than 95 days, entered without a source, has a provider sector with
    no mapping holding more than 0.5% of the fund (the provider's own "Other" bucket below that is reported), a weight
    outside 0..1, or weights that do not sum to 100% ± 2 points;
  - **classification mismatch:** VWRP's provider sectors (FTSE/ICB) and the SIC mapping are different systems, and
    the sector names are matched by a fixed table;
  - **unknown sector:** the company has no SIC code (it is not an SEC filer).
- With satellites, any failed **or unverified** enforced check rejects the candidate, and the 100% VWRP default
  stands.
- With no satellites, the default stands whatever the data (it is the fallback). Its sector checks pass only on
  verified look-through data; otherwise they are recorded as unverified, never as passed.

## 4. Relative-performance review threshold (−15%)

This is not a trading trigger and not a protection. It only opens a review.

- **Measured:** at each month-end close (UTC date of the last close), from the satellite sleeve's inception.
- **Returns:** the satellite sleeve's return R_s and VWRP's total return R_v over the same dates, in GBP.
  VWRP is accumulating; the sleeve's prices are price-only unless dividends are recorded, and this is flagged.
- **Calculation:** relative = (1 + R_s) / (1 + R_v) − 1, computed on two windows:
  - the trailing 12 months, from the month-end mark 12 calendar months before the last one (chosen by date), or
    since inception if the sleeve is younger; a missing start mark or a non-positive value makes the check
    unverified;
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
- flags for anything unverified;
- "no trade" when the target equals the current core.

# B5 pre-registration, addendum 3: version 3 with point-in-time quality eligibility

Drafted 2026-10-19 after the owner's decisions D20 (07:33Z) and D21 (07:44Z), **before any H1 or S2a score,
ranking, return, NAV, Sharpe ratio or verdict has been computed**.

It amends `B5_PREREGISTRATION.md` version 2 (sha256 `51acdd22…0d18`), addendum 1 (`0ac28262…7595`) and addendum 2
(`50a5a18f…f80e`). All three files stay unchanged and hash-frozen, and no registry entry is edited. Version 2 as
amended by addenda 1, 2 and 3 is **version 3**, registered under **new trial ids** that count in N.

**Status: draft for the owner's review, not registered.**

Every statement here rests on input-level evidence only: share counts, prices and flags
(`docs/edge/B5_QUALITY_FLAG_REVIEW.md`, `research/edge_b5_quality_flag_audit.py`).

## 1. The change

| | Version 2 (as registered) | Version 3 |
|---|---|---|
| Trial ids | `B5-H1-FCFPS-ACCEL-V2`, `B5-S2A-GP-12M-V2` | **`B5-H1-FCFPS-ACCEL-V3`, `B5-S2A-GP-12M-V3`** |
| Primary quality rule | Phase A rule (D5): adjusted or raw close ≤ 0, or share count > 10× or < 1/10 of the company's **median over the exploration window** (`edge_split.share_outliers`) | The same price flag; share count > 10× or < 1/10 of the company's **expanding median** of rows dated on or before the month (`edge_split.share_outliers_pit`) |
| Full-window rule | Everywhere the quality rule applies | **Only** in the P9 robustness run, as a reverse veto |
| P9 | Net excess > 0 under the point-in-time rule (`ROB-PITQ`) | Net excess > 0 under the **full-window** rule (`ROB-WINQ`) |
| N | 100 | **102** |

Everything else in version 2 as amended by addenda 1 and 2 is carried into version 3 unchanged:

- scores, inputs and input rules;
- portfolio rules, tranches, costs and execution;
- benchmark, factors and statistics;
- the DSR formula, gates P1-P11 and their thresholds;
- labels and check 4.

**Why.** The full-window median lets a 2015 eligibility decision depend on share counts reported up to 2022. In the
B5 universe that excludes 20 company-months of 6 companies on later information only. P9 tested only the sign
under a point-in-time universe, so the strength gates (t, DSR, alpha) would have judged a portfolio nobody could
have built in real time.

## 2. Where the primary rule applies

The point-in-time rule (`edge_b5.PRIMARY_QUALITY` = `quality_ok_pit`) is applied consistently to:

1. **Portfolio eligibility** (`edge_backtest.eligible`): buying, and keeping a held name at a rebalance.
2. **The S2a rank population**: the percentile within the SIC group is taken among names passing this rule
   (`edge_b5_run.s2a_scores(df, quality)`; the rule is a required argument).
3. **The P5 equal-weighted universe**: built from the primary panel.
4. **P4, P6, P7, P8, P10, P11**: each is the primary with exactly one change.

`edge_b5_stats.with_quality_columns` produces both rules side by side as `quality_ok_pit` and `quality_ok_window`
and **no bare `quality_ok` column**. `edge_b5_run.score_panels` refuses a frame that has one, so no code path can
pick a rule implicitly.

## 3. Gates, robustness runs and ids

| Gate | Run | Version-3 id (`counts_for_dsr`) | Quality rule |
|---|---|---|---|
| P1, P2, P3, P10 | primary | `B5-H1-FCFPS-ACCEL-V3`, `B5-S2A-GP-12M-V3` (**yes**) | point in time |
| P4 | 2× costs | `B5-{H1,S2A}-V3-ROB-2XCOST` (no) | point in time |
| P5 | equal-weighted universe | none: computed under the primary's id, not recorded | point in time |
| P6 | missing price −100% | `B5-{H1,S2A}-V3-ROB-MISS100` (no) | point in time |
| P7 | next-month close | `B5-{H1,S2A}-V3-ROB-NEXTMONTH` (no) | point in time |
| P8 | data-error months barred | `B5-{H1,S2A}-V3-ROB-DATAERR` (no) | point in time |
| **P9** | **reverse veto** | **`B5-{H1,S2A}-V3-ROB-WINQ`** (no) | **full window**; S2a re-ranked in that population |
| P11 | without the largest contributor | none: computed under the primary's id, not recorded | point in time |

**Retired ids.** These stay registered exactly as written, and the version-1 and version-2 trial ids stay counted.
They can never be run or recorded (`edge_registry.B5_RETIRED_IDS`):

- `B5-H1-FCFPS-ACCEL-V2` and `B5-S2A-GP-12M-V2`, and all ten `B5-{H1,S2A}-V2-ROB-*`, including `ROB-PITQ`, whose
  rule is now the primary;
- version 1: `B5-H1-FCFPS-ACCEL`, `B5-S2A-GP-12M` and `B5-{H1,S2A}-ROB-*`.

**Reverse veto.** P9 passes only if net excess > 0 under the full-window rule. In `edge_b5.verdict` it is one more
condition:

- a failed P9 fails the trial;
- a passed P9 adds nothing;
- it is never used in place of any primary statistic.

A missing input fails closed.

**No old result can pass for a version-3 result.** Only version-3 ids can be run or recorded, and every version-3
result carries its own id. Version-1 and version-2 ids have no results and can never get one. `preflight` refuses to
start if any trial, robustness or retired id has a result.

## 4. How the controls interact (execution order)

1. **Registration, on the owner's separate approval** (`research/edge_b5_addendum3.register(owner_message)`). It
   appends `B5-V3-ADDENDUM-3`, the two version-3 trials (counted) and the ten version-3 robustness ids (uncounted),
   each carrying this file's sha256. Nothing existing is edited. It refuses without an owner message id, and refuses
   ids already registered.
2. **Manifest, on separate approval.** `B5-V3-RUN-MANIFEST` records the sha256 of `docs/edge/B5_RUN_MANIFEST.json`.
   That manifest hashes 10 input files and the 16 repository modules the run imports.
3. **Authorisation, on separate approval.** `research/edge/status.json` `b5_trial_run.authorised = true` with the
   owner's message id.
4. **`edge_b5_run.preflight`**, in order, before any data is read:
   - the authorisation;
   - the registry chain is valid;
   - **N = 102**;
   - the version-2 trial ids and addenda 1-2 match their files' hashes;
   - the version-3 trials and `B5-V3-ADDENDUM-3` match this file's hash;
   - the manifest is registered and every input and code file matches it;
   - both version-3 trials count, and all ten version-3 robustness ids are registered and uncounted;
   - **no result exists for any version-3, version-2 or version-1 id**;
   - the **one-run lock** is created exclusively. It is never removed and not git-ignored.
5. **The run gate.** `edge_registry.require` (called by every `bt.run_trial` and `bt.record`), `load_inputs`,
   `run_one` and `finish` all check `b5_run_open()`. That means the real `status.json` is authorised and the lock
   names the same message, so calling a function directly or running against copied files opens nothing.
   `require` refuses retired ids always.
6. **All or nothing.** `finish` checks every gate's run for both trials before the first append; a partial run
   records nothing. It then records both primary results and the ten robustness results. It confirms both primaries
   are in the registry, and only then computes each DSR. The DSR must see N = 102 and at least 2 comparable
   results.

## 5. Trial count: N = 102 (owner decision D21)

**Rationale.**

- Version 2 §7 control 4 allows only bug fixes before a run and forbids changing a definition.
- Addendum 3 changes primary portfolio eligibility, so it is a definition change, not a bug fix.
- Under the stricter route the owner chose, the amended specification is a new trial: new ids, counted. This is
  the same treatment version 1 received when version 2 replaced it.
- Version 2's ids stay registered and counted although they never run.

**Reconciliation under the existing rules:**

- `EVALUATION_SPEC.md` (N = every registered trial with `counts_for_dsr`) and version 2 §5 (every counted
  registration adds 1; robustness runs never count) are unchanged.
- The trial count is the number of counted registrations. Only the two version-3 trial registrations are counted.

| Registry ids | Kind | Counted |
|---|---|---:|
| `S2-S1a` … `S2-S9` (Stage 2) | inherited | 15 |
| `M8-T1`, `M8-AUDIT-*` | inherited | 6 |
| `DIAG-*` | diagnostic | 45 |
| `QX-*`, `QX-PIT-*` | diagnostic | 30 |
| `B5-H1-FCFPS-ACCEL`, `B5-S2A-GP-12M` (version 1, superseded, never run) | trial | 2 |
| `B5-H1-FCFPS-ACCEL-V2`, `B5-S2A-GP-12M-V2` (version 2, superseded, never run) | trial | 2 |
| **`B5-H1-FCFPS-ACCEL-V3`, `B5-S2A-GP-12M-V3`** | trial | **2** |
| **Total** | | **102** |

Not counted: `B5-V3-ADDENDUM-3`, the ten version-3 robustness ids, and everything listed as uncounted in version 2
§5.

**DSR configuration.** The formula (version 2 §5, addendum 1 §4) is unchanged. `edge_registry.deflated_sharpe` takes
N from the registry. `edge_b5_run.N_EXPECTED = 102`, and `preflight` and `finish` refuse any other N.

The 0.80 threshold, recomputed from the formula alone with N = 102, T = 94 and V = 1/94. No return series was used.
The same code reproduces version 2's N = 100 values to four decimals.

| Return shape | Monthly sr needed (N = 100 → 102) | Annualised | iid t-equivalent |
|---|---:|---:|---:|
| `SR0` | 0.2610 → **0.2617** | | |
| Normal (γ3 = 0, γ4 = 3) | 0.3509 → **0.3517** | 1.22 | 3.40 → 3.41 |
| Mild negative skew (−0.5, 4) | 0.3596 → **0.3604** | 1.25 | 3.49 → 3.49 |
| Strong negative skew, fat tails (−1, 6) | 0.3693 → **0.3701** | 1.28 | 3.58 → 3.59 |
| Two comparable results, V = 2/94 | 0.4609 → **0.4620** | 1.60 | 4.47 → 4.48 |

At t = 3.0 exactly (normal), DSR = 0.673 (was 0.676), which fails P2. The gate remains the DSR computed from the
trial's own statistics.

## 6. History preserved

- `B5_PREREGISTRATION.md` (version 2) and addenda 1 and 2 are unchanged, and their hashes are test-pinned.
- No registry line is added or edited until the owner approves. After registration, every earlier line is
  byte-identical (tested on a copy).
- D5 is not withdrawn: it governs Phase A and Stage 2, and `edge_split.share_outliers` is unchanged.
- D20 is not rewritten: its provisional N = 100 is superseded by D21, recorded as a new row in `DECISIONS.md`.

## 7. Effect on inputs (B5 universe: large band, close ≥ $1, non-financial, 2015-01 to 2022-11; 34,399 company-months)

| Set | Rows | Companies | Also removed by rule C |
|---|---:|---:|---:|
| Point-in-time rule (version 3 primary) | 295 | 49 | 168 |
| Full-window rule (P9 only) | 207 | 43 | 145 |
| Excluded only by the full-window rule (later information) | 20 | 6 | 9 |
| Excluded only by the point-in-time rule | 108 | 11 | 32 |

The two rules disagree on 128 rows (0.37%), at most 4 in any month.

## 8. Disclosures (fixed in every B5 report: `edge_b5_run.KNOWN_INPUT_LIMITATIONS`, `edge_rules.STANDING_LIMITATIONS`)

- **Point-in-time quality-rule errors.** It wrongly excludes about 108 company-months of genuine companies after
  mergers or spin-offs: MPLX, Fox, Linde, Viatris, Cheniere Energy Partners and others (76 rows, 9 companies after
  rule C). It also admits AVITA Medical's 9 inflated rows (2019-11 to 2020-07). Both rules wrongly exclude CoStar
  and The Trade Desk after their 2021 10-for-1 splits.
- **P8.** The 12 data-error company-months were chosen by auditing the whole 2015-2022 price path, which is later
  information. P8 is a veto only.
- **2026 SIC classifications.** The financial exclusion, S2a groups and sector cap use a 2026 snapshot of SIC codes,
  not point-in-time codes.
- **Input-validation false positives and misses.**
  - General Dynamics 2017-18 loses 18 fallback rows to a mis-tagged concept (false positive).
  - Abbott 2015-01, with about 10.6% basis mixing, is not caught (missed case).
  - EQT and ConocoPhillips are flagged for derivative-inclusive revenue.
- **Identity-rule residuals.** Rows between 25× and 100× market cap to assets stay in: Curis 97×, BeOne 97×, and
  Larimar 85× after a CIK reuse. Scinai cannot be scored.
- **Survivorship.** Companies that delisted before the 2026 price download are missing. This is material and
  unbounded, and the −100% stress does not address it.
- **Check 4 and evidence.** TTM check 4 is open, so no E2 label is possible. No exploratory result is proof of a
  deployable edge.

## 9. Registration steps (each on the owner's separate approval; none done)

1. Register version 3: `B5-V3-ADDENDUM-3`, the two version-3 trials and the ten version-3 robustness ids. N becomes
   102.
2. Register the run manifest as `B5-V3-RUN-MANIFEST`.
3. Authorise the run in `status.json`.

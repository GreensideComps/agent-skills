# B5 pre-registration, addendum 3: point-in-time quality eligibility

Drafted 2026-10-19 after the owner's decision D20 (07:33Z), **before any H1 or S2a score, ranking, return, NAV,
Sharpe ratio or verdict has been computed**. It amends `B5_PREREGISTRATION.md` version 2 (sha256 `51acdd22…0d18`),
addendum 1 (`0ac28262…7595`) and addendum 2 (`50a5a18f…f80e`). All three stay unchanged and hash-frozen, and their
registry entries are not edited. **Status: draft for the owner's review, not registered.** On approval it is
registered by its sha256 as `B5-V2-ADDENDUM-3` (not counted).

Every statement here rests on input-level evidence only: share counts, prices and flags
(`docs/edge/B5_QUALITY_FLAG_REVIEW.md`, `research/edge_b5_quality_flag_audit.py`).

## 1. The change

| | Version 2 (as registered) | This addendum |
|---|---|---|
| Primary quality rule | Phase A rule (D5): adjusted or raw close ≤ 0, or share count > 10× or < 1/10 of the company's **median over the exploration window** (`edge_split.share_outliers`) | The same price flag; share count > 10× or < 1/10 of the company's **expanding median** of rows dated on or before the month (`edge_split.share_outliers_pit`) |
| Where the full-window rule is used | Everywhere the quality rule applies | **Only** in the P9 robustness run, as a reverse veto |
| P9 | Net excess > 0 under the point-in-time rule (`ROB-PITQ`) | Net excess > 0 under the **full-window** rule (`ROB-WINQ`) |

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
4. **P4, P6, P7, P8, P10, P11**: each is the primary with exactly one change, so each uses this rule.

`edge_b5_stats.with_quality_columns` produces both rules side by side as `quality_ok_pit` and `quality_ok_window`
and **no bare `quality_ok` column**. `edge_b5_run.score_panels` refuses a frame that has one, so no code path can
pick a rule implicitly.

## 3. Gates and robustness runs, mapped

| Gate | Run | Id (`counts_for_dsr`) | Quality rule |
|---|---|---|---|
| P1, P2, P3, P10 | primary | `B5-H1-FCFPS-ACCEL-V2`, `B5-S2A-GP-12M-V2` (yes) | point in time |
| P4 | 2× costs | `B5-{H1,S2A}-V2-ROB-2XCOST` (no) | point in time |
| P5 | equal-weighted universe | none: computed under the primary's id, not recorded | point in time |
| P6 | missing price −100% | `B5-{H1,S2A}-V2-ROB-MISS100` (no) | point in time |
| P7 | next-month close | `B5-{H1,S2A}-V2-ROB-NEXTMONTH` (no) | point in time |
| P8 | data-error months barred | `B5-{H1,S2A}-V2-ROB-DATAERR` (no) | point in time |
| **P9** | **reverse veto** | **`B5-{H1,S2A}-V2-ROB-WINQ` (no), new** | **full window**; S2a re-ranked in that population |
| P11 | without the largest contributor | none: computed under the primary's id, not recorded | point in time |
| — | retired | `B5-{H1,S2A}-V2-ROB-PITQ` (no) | its rule is now the primary, so running it would duplicate the primary. **Never run** |
| — | retired | version 1: `B5-H1-FCFPS-ACCEL`, `B5-S2A-GP-12M` (yes, still counted) and `B5-{H1,S2A}-ROB-*` (no) | **never run** |

The registry entries of the ROB-2XCOST, MISS100, NEXTMONTH and DATAERR runs say "exactly as registered, except …".
This addendum amends the base they refer to, so they use the point-in-time rule. Their text is not edited.

**Reverse veto.** P9 passes only if net excess > 0 under the full-window rule. Like every robustness gate it is one
more condition in `edge_b5.verdict`:

- a failed P9 fails the trial;
- a passed P9 adds nothing;
- it is never used in place of any primary statistic.

A missing P9 input fails closed. The gate list P1-P11 and every threshold are unchanged.

## 4. Execution controls (no duplicate, partial or ambiguous run)

- `edge_registry.require` refuses every retired id (`B5_RETIRED_IDS`) always, whoever asks. It refuses the 2 trial
  ids and the 10 current robustness ids, including ROB-WINQ, unless the run is open: the owner's authorisation is
  in `status.json` and the one-run lock names the same message.
- `edge_b5_run.preflight` additionally requires, before any data is read:
  - Addendum 3 registered with its file's hash;
  - every robustness id registered and uncounted;
  - no result for any trial, robustness or retired id;
  - the one-run lock absent.
- `finish` refuses before its first append unless every gate's run is present.

## 5. Trial count: N stays 100. Justification, and what the policy does not cover

**What the registered policy says.**

- `EVALUATION_SPEC.md`: N is every registered trial with `counts_for_dsr`, reported or not, and a rerun of a trial
  that has a result is a new trial.
- Version 2 §5: every counted registration adds 1, and robustness runs never count.
- Version 2 §7, control 4: "No reruns or tuning. Before a run, only bug fixes may change code, and none may change a
  definition here."

**Why 100 is supported.**

1. **The counting rule.** N counts registrations. This addendum adds no counted registration: the trial ids are
   unchanged, and the new entries are an uncounted specification record and uncounted robustness runs, as
   version 2 §5 requires.
2. **No outcome has been looked at.** No B5 result exists for any id (the registry and `preflight` check this). The
   multiple-testing penalty protects against choosing among specifications after seeing outcomes. This change was
   prompted by an input-level timing defect found in review, before any outcome.
3. **It corrects timing; it does not add a hypothesis.**
   - The scores, the portfolio rules and the full-window rule's role as a filter of data errors are unchanged.
   - The rule is moved to information available at each decision date, the same principle the owner applied to T2
     (D19).
   - The point-in-time rule existed before this decision and was registered in version 2 as the P9 rule; it is not
     a new design.
4. **Prior looks with this rule are already counted.** Stage 2's `QX-PIT-*` diagnostics (15 counted, including
   `QX-PIT-S2a`) are in N.
5. **Precedent.** Addenda 1 and 2 changed version 2's input definitions before any result, with the owner's
   approval (D16-D19), and N stayed 100.

**Flagged, not assumed.**

- Control 4's text allows only bug fixes before a run and does not provide for amending a definition. Addenda 1-3
  rely on owner decisions (D16-D20), not on a clause of the registered policy. This change is closest to a timing
  defect fix, but it changes a definition, so its authority is D20.
- A stricter reading counts each specification ever registered as primary. That is how version 1 stayed counted,
  but version 1 had its own ids. Under that reading, re-registering the trials as V3 ids would make N = 102. The
  registered policy does not require that reading here, because it counts ids, not texts.

The owner kept N = 100 provisionally (D20).

## 6. History preserved

- `B5_PREREGISTRATION.md` (version 2) and addenda 1 and 2 are unchanged; their hashes are test-pinned.
- No registry line is edited. The trials' registered `universe` text ("Phase A quality rule") remains as the record
  of the version-2 definition; this addendum is the amendment.
- D5 is not withdrawn: it governs Phase A and Stage 2, and `edge_split.share_outliers` is unchanged. D20 records
  this change in `DECISIONS.md`.

## 7. Effect on inputs (B5 universe: large band, close ≥ $1, non-financial, 2015-01 to 2022-11; 34,399 company-months)

| Set | Rows | Companies | Also removed by rule C |
|---|---:|---:|---:|
| Point-in-time rule (now primary) | 295 | 49 | 168 |
| Full-window rule (now P9 only) | 207 | 43 | 145 |
| Excluded only by the full-window rule (later information) | 20 | 6 | 9 |
| Excluded only by the point-in-time rule | 108 | 11 | 32 |

The two rules disagree on 128 rows (0.37%), at most 4 in any month.

## 8. Disclosures (fixed in every B5 report: `edge_b5_run.KNOWN_INPUT_LIMITATIONS`, `edge_rules.STANDING_LIMITATIONS`)

- **Point-in-time rule errors.** It wrongly excludes about 108 company-months of genuine companies after mergers or
  spin-offs: MPLX, Fox, Linde, Viatris, Cheniere Energy Partners and others (76 rows, 9 companies after rule C).
  It also admits AVITA Medical's 9 inflated rows (2019-11 to 2020-07).
- **Errors under both rules.** Both wrongly exclude CoStar and The Trade Desk after their genuine 2021 10-for-1
  splits.
- **P8.** The 12 data-error company-months were chosen by auditing the whole 2015-2022 price path, which is later
  information. P8 is a veto only.
- **SIC codes.** The financial exclusion, S2a groups and sector cap use a 2026 snapshot of SIC codes, not
  point-in-time codes.
- **Addenda 1-2 cases.** The revenue tests' General Dynamics false positive and Abbott missed case, the
  derivative-basis flags, the rule C residuals from 25× to 100×, and Scinai.
- **Survivorship.** Companies that delisted before the 2026 price download are missing. This is material and
  unbounded, and the −100% stress does not address it.
- **Check 4 and evidence.** TTM check 4 is open, so no E2 label is possible. No exploratory result is proof of a
  deployable edge.

## 9. Registration, after the owner's separate approval (not done)

1. Register this addendum and the two ROB-WINQ ids (`research/edge_b5_addendum3.py`, `register(owner_message)`).
   N stays 100.
2. Register the run manifest (`B5-V2-RUN-MANIFEST`), on separate approval.
3. Authorise the run in `status.json`, on separate approval.

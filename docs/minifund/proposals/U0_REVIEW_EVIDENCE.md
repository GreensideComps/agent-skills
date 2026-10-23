# U0 review pack: D-A, D-B and D-C diffs, tests and before/after evidence (nothing applied)

Owner decision 2026-10-23 12:06Z (`cmsg_01U4KMvkBYNknqm4HRVie8uvGZrinrG9nzsK8dtuPiDUzc`): U0 is "provisionally
approved in principle … do not apply the proposed changes until you return the exact diff, tests and before/after
evidence for review. Historical results must remain unchanged."

**Nothing in this folder is applied** to master or to any PR branch.
- **Before** = master `b8cccb4` code. The PR #30 branch differs from it only under `docs/`.
- **After** = a scratch copy of master with all three patches applied, and the two D-A annotations appended with
  `edge_verdicts.append`.

All runs were offline inside a network namespace with no route out (`unshare -rn`), credentials unset, Python
3.13.16, pytest 9.1.1.

## 1. The exact diffs

| Patch | sha256 (16) | Files | Applies to |
|---|---|---|---|
| `DA_research_verdict_ledger.patch` | `287e7d6d55c646d9` | adds `research/edge_verdicts.py`, `research/tests/test_edge_verdict_annotation.py` (11 tests) | master (`git apply --check` passes) |
| `DA_pm_on_pr27.patch` | `c985a9e6b5c3debe` | `office/office/pm.py`, `office/tests/test_pm.py` (+2 tests) | PR #27 head `ba825f2` only |
| `DB_prior_etf_families.patch` (**new**) | `1bb600d1ab29240b` | adds `research/edge/prior_etf_families.json`, `research/edge_families.py`, `research/tests/test_edge_families.py` (9 tests) | master |
| `DC_evidence_labels.patch` | `ea61b8891b1a2603` | `equity/config/evidence.json`, `equity/equity/evidence.py`, `equity/tests/test_evidence.py` (+1 test) | master |

D-A also proposes two data lines. They are `DA_VERDICT_ANNOTATION_EVENTS.json`, and the resulting ledger is
`DA_verdict_annotations.expected.jsonl`. In the after copy, the appended ledger is byte-identical to the expected
file (`cmp` exit 0).

**About the D-B patch.**
- It turns the family table in `MULTIPLE_TESTING_PRIOR_ETF.md` §2 into a data file.
- It adds `extra_n(families)`, which counts each experiment once and refuses undeclared or unknown families.
- A check (`validate`) confirms that the configuration counts equal the `trials` fields in `research/experiments/`.
- It does not write to the registry and changes no N today. The extra count is meant to be passed to the deflated
  Sharpe at evaluation time (Stage 3).

## 2. Test commands and exit codes

| Run | Command (from the suite folder) | Result | Exit |
|---|---|---|---|
| Before: research | `env -u T212_KEY -u T212_SECRET -u T212_ENV -u RESEND_API_KEY unshare -rn python -m pytest -q -p no:cacheprovider` | 460 passed | 0 |
| Before: equity | same | 118 passed | 0 |
| After: research | same | **480 passed** (460 + 11 D-A + 9 D-B) | 0 |
| After: equity | same | **119 passed** (118 + 1 D-C) | 0 |
| After: office with `DA_pm_on_pr27.patch` (earlier run, 23 Oct) | `pytest tests` on PR #27 head | 66 passed | 0 |

## 3. Before and after (from `U0_BEFORE_AFTER_EVIDENCE.json`)

| Check | Before | After |
|---|---|---|
| `research/edge/trials.jsonl` sha256 | `de03d38b…17e6` | `de03d38b…17e6` (identical) |
| `research/edge_registry.py` sha256 | `129c0e2d…` | `129c0e2d…` (identical) |
| `n_trials` (deflated-Sharpe N) | 102 | 102 |
| `verdict` field on registry results for H1 and S2a V3 | none | none (the registry is not edited) |
| Verdict as read through the D-A ledger | no ledger | `fail`, `fail` |
| Allocation eligibility of H1 and S2a V3 | not eligible: no "pass" exists, with no recorded reason | not eligible, reason recorded: "verdict is fail, not pass" |
| D-B extra N for a momentum trial / an unrelated trial | no code | 74 / 0 |
| screen-1.0 and paper-1.0 banner | "**unvalidated: not a recommendation**" | "**unvalidated exploratory research: not investable evidence, not a recommendation**", plus the D-C allowed-use text |
| 19 historical reports in `equity/reports/screens`, `paper`, `portfolio` (sha256) | listed | identical |

**What D-A changes in practice.**
- The failed trials could not qualify before either, because pm-1.0 needs a recorded "pass".
- After D-A the fail is recorded explicitly, with its evidence hash and the owner decision, and eligibility gives
  a reason.
- A later code change that accepted, for example, "no verdict" can no longer let these two trials through
  unnoticed.

**What D-C changes in practice.** The wording in banners written after a merge. Historical reports keep their
current banners, which already say "unvalidated" (`SCREEN_1_0_LABEL.md`).

## 4. What applying would involve (for after review, not now)

1. Merge the three master patches as one draft PR or separately, as the owner prefers.
2. Run `edge_verdicts.append(<the two events>)` once and commit the ledger. Confirm with
   `python3 research/edge_verdicts.py`, which should print "valid".
3. Apply the D-C wording only together with the daily equity pipeline's next run, because it changes printed output.
4. Apply the pm patch only if PR #27 goes ahead.

No registry pin, scheduled task, G1/G2 file or office worker code is touched by any of these.

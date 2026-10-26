# Task ledger (append and update; never delete rows)

States: done · in review (a PR is open) · ready · blocked (with the reason) · later.
"Done" means the code is implemented and its tests pass. It is never a claim that the work operates in production,
unless the row says it was demonstrated.

| Id | Priority band | Task | State | Evidence or blocker |
|---|---|---|---|---|
| T01 | 1 Baseline | Verify the PR #19 merge, tests and research state | done | STATUS.md: 717 pass on `11512d4`, registry 102, authorised = false |
| T02 | 1 Baseline | Capability audit A–G | done | STATUS.md table |
| T03 | 2 Queue | Event log, git store, queue with leases (M1) | in review | M2 PR carries it; 27 tests; remote branch had been deleted, restored from the bundle `3802b79` |
| T04 | 3 Scheduling | Director, worker run, heartbeat events, pause and stop, budgets (M2) | in review | `office/office/{director,worker}.py`, test_m2.py |
| T05 | 3 Monitoring | Health report and alert rules from the log | in review | `health.py`; tests for silent worker, unfinished run, quarantine, pause |
| T06 | 6 Tests | Daily test-suite run on master with credentials stripped (CI substitute) | in review | `handlers.h_test_suites`; e2e run in this session (see PR) |
| T07 | 6 Alerts | Daily digest written from the log; email off by default | in review | `h_digest`, `render_digest` |
| T08 | 7 Portfolio | Read-only demo snapshot through `ReadOnlyClient` with the kill file set | in review | `h_demo_snapshot`; fake-run tests; one real read in the e2e run |
| T09 | 9 Gate | G1 criteria fixed before any run, and the gate evaluator | in review | `RELIABILITY_GATE.md`, `gate.py`, synthetic 15-day tests |
| T10 | 6 Alerts | Remove the deleted T212 routines from the equity schedule (false WARN) | in review | `equity/config/schedule.json`; equity 118 pass |
| T11 | 3 Deploy | Create `claude/office-state`, the heartbeat and digest tasks; start G1 | done (demonstrated) | PR #25 merged `b0e494b`; G1 started 2026-10-20 11:56Z. **G1 FAILED 21 Oct** (gap 6.02 h vs a 6.00 h limit; record in project files, unchanged). G2 criteria merged in PR #29; G2 not started |
| T12 | 6 Alerts | Test owner alert delivery by email | blocked | Owner approval (external send) |
| T13 | 3 Ops | Fix or explain the equity pipeline rc=1 on 19 Oct | in review | Cause: reliability still expected the deleted T212 routines; PR #26 |
| T14 | 7 Benchmark | Paper book: VWRP primary benchmark, SPY secondary (paper-1.1) | in review | D-T14 option A. `equity/equity/paper.py`, config `paper-1.1`; history kept as paper-1.0; 3 new tests (equity 121). Live Yahoo read 20 Oct: VWRP.L 142.40 GBP, GBPUSD 1.3345 |
| T15 | 4 Research | Research planner: one draft proposal per ISO week for owner approval (never registers or runs) | in review | D-T15. `office/office/planner.py`, `python3 -m office plan-draft`; 4 tests. Not scheduled yet: needs a candidate written by a session |
| T16 | 8 Paper | Office paper book with persisted intent, a simulated broker and reconciliation (uses `orders.py`) | later | After T14; needs its own gate |
| T17 | 5 Provenance | Record library versions with each research run | later | Gap found in Pack B |
| T18 | 10 Live | Live path | later | Separate explicit owner authorisation only; not started |
| T19 | — | Pack B: weekday brief recreate · decile rule · unscored option · M1 branch re-push | blocked | Owner decisions (EVIDENCE_PACK_2026-10-20_B.md) |
| T20 | 7 Portfolio | Proposal-only portfolio manager pm-1.0 (100% VWRP until gated evidence) | in review | D-T16. Spec `docs/office/PM_SPEC.md` fixed first; `office/office/{pm,sectors}.py`, `python3 -m office pm-propose`; 10 tests. Today's output: 100% VWRP, no trade |
| T21 | 6 Tests | Daily test task found no test runner in scheduled sessions (all suites exit 1, empty summary) | done (demonstrated) | Fixed on master by PR #28 (worker requirements plus a runner probe that sets `cause` on `tests_failing`). The 21 Oct 00:59Z run passed all 4 suites. PR #27's own handler change was dropped in favour of PR #28's |

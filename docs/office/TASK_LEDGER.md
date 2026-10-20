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
| T11 | 3 Deploy | Create `claude/office-state`, the heartbeat and digest tasks; start G1 | blocked | Owner approval (uses plan usage; scheduled tasks) and the M2 PR merged |
| T12 | 6 Alerts | Test owner alert delivery by email | blocked | Owner approval (external send) |
| T13 | 3 Ops | Fix or explain the equity pipeline rc=1 on 19 Oct | ready | Last run of trig_01PYai2PEsqMTtFSMDCD99BY |
| T14 | 7 Benchmark | Paper book benchmark VWRP, not SPY | ready | `equity/equity/paper.py`; changes a reported metric, so it needs a note to the owner before merge |
| T15 | 4 Research | Research director: proposes the next question as a draft manifest for owner approval (never runs it) | later | After G1 starts; must respect D-series governance |
| T16 | 8 Paper | Office paper book with persisted intent, a simulated broker and reconciliation (uses `orders.py`) | later | After T14; needs its own gate |
| T17 | 5 Provenance | Record library versions with each research run | later | Gap found in Pack B |
| T18 | 10 Live | Live path | later | Separate explicit owner authorisation only; not started |
| T19 | — | Pack B: weekday brief recreate · decile rule · unscored option · M1 branch re-push | blocked | Owner decisions (EVIDENCE_PACK_2026-10-20_B.md) |

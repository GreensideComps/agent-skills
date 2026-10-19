# M1 report: research office foundations (19 Oct 2026)

Scope: owner go-ahead at 14:43Z (`cmsg_01U4KMvkBYNknqm4HRVie8uvWwTNKF9omgYAaJPUXEVzyz`). Implementation and test
preparation on new branches, with **nothing deployed**. M1 stops here for owner review. The 14-day unattended test is a
separate gate and has not started.

## 1. What was built (branch `claude/research-office-plan-sseamv`)

| Part | File | What it does |
|---|---|---|
| Event log | `office/office/events.py` | append-only, hash-chained JSONL; validation finds edits, drops and reorders |
| Git store | `office/office/store.py` | non-force push as compare-and-swap; resolves an ambiguous push by looking at the remote; refuses a remote log that no longer extends what it saw; history audit |
| Task queue | `office/office/queue.py` | idempotent tasks, dependencies, growth limits, fenced leases with expiry, refusal of a stale result, retry backoff, quarantine |
| Order state machine | `office/office/orders.py` | records intent before submission; never resubmits an unknown outcome; adopts the one matching broker order or pauses; cancels working orders after a limit; reconciles positions; one-time decision keys; pause until an owner resume. **No broker adapter.** |
| GitHub test | `office/github_queue_test.py` | 7 scenarios against the real remote, on a throwaway branch |

## 2. Test results

**Unit tests:** `cd office && python3 -m pytest -q` gives **27 passed** (local bare-repo remote, fake broker).

**GitHub test** (branch `office-queue-test-20261019144950`, 6 worker processes; report at
`docs/office/evidence/github_queue_test_2026-10-19.json`):

| Scenario | Result | Evidence |
|---|---|---|
| S1 concurrent idempotent create | pass | 20 tasks from 6 writers each creating the same 20; 79 push rejections absorbed |
| S2 concurrent claim and drain | pass | 20 claims, **0 double claims**, 20 completed; 131 rejections |
| S3 worker crash and lease expiry | pass | victim killed with SIGKILL (exit -9); no claim while its lease was live; recovered as attempt 2 |
| S4 stale worker result | pass | the dead worker's late completion was refused; the rescuer's was accepted |
| S5 retries and quarantine | pass | attempts 1, 2, 3, then quarantined |
| S6 interrupted pushes | pass | 8 SIGKILLs at random moments; history audit clean |
| S7 remote unreachable | pass | raises `StoreUnavailable`; nothing recorded |
| Final audit | pass | 80 events, chain and history clean |
| **Cleanup of the throwaway branch** | **FAILED** | `git push --delete` was refused with HTTP 403 by this session's GitHub proxy (a policy denial, so it was not retried) |

**The owner needs to delete** `office-queue-test-20261019144950` at
https://github.com/GreensideComps/agent-skills/branches. It holds only the test's `events.jsonl`. The test's
`finally` block did run and verified the result with `ls-remote`, which is how the failure was detected and reported
rather than assumed. Cloud sessions here cannot delete branches, so later throwaway tests need the owner to clean up,
or a different mechanism.

**Other suites:**
- Trading suite on the retirement branch: 146 passed.
- Research suite on the D31 branch: see the D31 PR.

## 3. Separate reviewed PRs (none merged)

| PR | Content | Status |
|---|---|---|
| #20 retirement (O10) | strategy.json → `retired`, with no targets or signal; the bot halts before planning; the legacy loop is retired with `research/STOP`; old files archived unchanged; 7 new tests | draft, awaiting review |
| #21 Check 4 procedure (O6) | `docs/edge/CHECK4_PROCEDURE.md`: EDGAR filings as source, seeded sample, blind double extraction, owner review, tolerance stated in advance | draft, docs only |
| D31 fix (O4) | D31 added to `B5_SPENT_AUTHORISATIONS`; based on PR #19's branch | see the D31 PR; MANIFEST-3 now permanently fails its file check (disclosed and tested) |

## 4. Security and scope review

- **No trading path enabled.** `office/` imports only the standard library and itself (checked by grepping its
  imports). There is no HTTP client, no `trading/` import and no T212 reference. Its only external call is `git`, to
  its configured branch, without force.
- **No deployment.** No scheduled task was created or changed: the 19 Oct listing shows the newest task was created
  on 15 Oct, and the five disabled tasks are still disabled. No CI workflow was added, no service was started and
  no environment variable was changed.
- **The retirement only restricts trading.** A retired config cannot carry targets. A run with `--execute`, even with
  `--force`, halts before planning, and `decide` refuses.
- **The bot branch is unchanged.** `claude/trading212-agent-skills-r71zy3` still has the old 100% LQQ3 config, and the
  disabled hourly traders, trading ops and research loop point at it. They are harmless only while they stay disabled.
  Deleting them is your call.
- **No secrets** in office code or evidence (grep for key/secret/token/password).
- **Research controls are untouched.** No run, gate, holdout or registry change. The D31 PR adds a refusal and
  removes none.
- **Accounts:** no demo or live account was read or changed during M1 after the 14:40Z read-only check. No pie was
  touched.

## 5. Order safety (formalised)

States run intent → submitted → working → filled / cancelled / rejected → reconciled. An unknown outcome goes to
recover:
- exactly one matching broker order: adopt it;
- no match after a 120 s settle window, several matches, or a failed lookup: pause plus a critical alert.

An order is never resubmitted. A cancel with an unknown outcome pauses. A reconciliation mismatch pauses. While
paused, every new intent is refused, and only an owner message resumes. All 14 order tests pass against the fake
broker.

## 6. O8/O9: still blocked

`docs/office/DEMO_TEST_PROPOSAL.md` specifies five named tests with direction, size, caps, account verification,
cancel and recovery behaviour, and reconciliation criteria. It replaces the contradictory "6 orders, £10 each, £20
total": at most 5 submissions, at most £5 per buy, at most £15 gross buys, at most £10 net open exposure, and a final
net position of zero. The prerequisite is at least £20 of free demo cash, added without touching the pies.

## 7. Outstanding risks

1. **The throwaway branch is not deleted** (above). Session policy blocks branch deletion.
2. **Push contention grows with workers.** 6 workers on 20 tasks caused about 130 rejections and took 97 s. That is
   fine at office scale (tens of tasks a day), but not for high-frequency use.
3. **Git hosting is the single point of failure.** If GitHub is unavailable, the office stops safely
   (`StoreUnavailable`) but does not keep working.
4. **The order logic is proven only against a fake broker.** The real T212 behaviour (history lag, partial fills,
   fractional steps) is unverified until the M2 adapter and the L3 tests.
5. **The platform evidence is thin:** 6 of 6 fresh-session runs fired; a persistent session shared by 3 tasks lost
   3 of 6 runs. The 14-day test is still needed before any "always-on" claim.
6. **D31 fix side effect:** MANIFEST-3 can no longer pass its file check. This is intended, but any future B5 run
   needs a new manifest.
7. **PR #19 is still unmerged.** B5 stays read-only, and the D31 PR depends on it.

## 8. Proposed next actions (M2; each needs your go-ahead)

1. Review and merge PRs #20, #21 and the D31 PR (or ask for changes). Delete the throwaway branch.
2. **M2:** a supervisor and heartbeat on the queue, the daily digest and critical alerts (O12), and a T212 adapter for
   the order state machine, tested only against the fake broker and the demo read endpoints (L1/L2, no orders).
3. Then decide on starting the 14-day unattended test (the bar is in DECISION_REGISTER §3).
4. Separately, when you choose: the O8/O9 decision on the demo test proposal, and approval of the Check 4 procedure.

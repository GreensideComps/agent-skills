# Unattended-operation gate G1 (criteria fixed before any run)

Status: **defined, not started.** No `gate_started` event exists. Nothing may describe the office as operating
unattended, always-on or autonomous until a G1 run has passed.

These criteria were written and committed before the first run, and `office/office/gate.py` computes them
(`CRITERIA_VERSION = "G1"`). Changing any criterion means a new version (G2) and a fresh 14 days. A G1 run cannot be
re-scored under different rules.

## What G1 tests

G1 tests whether the office keeps operating with nobody prompting it. That covers the heartbeat, the queue, crash
recovery, daily checks and the digest. The office runs R0 work only: health, the test suites on master, a
read-only demo snapshot, and the digest.

G1 says nothing about research quality, investment edge, paper trading or execution:
- Paper trading needs its own gate once a paper book exists; see the task ledger.
- An edge claim needs the research gates.

## Starting a run

1. The owner approves the run in a message. The message id is recorded in `gate_started`, along with the heartbeat
   interval H and the criteria version.
2. `python3 -m office --heartbeat-h H gate-start --owner-message cmsg_...` appends the event.
3. The window runs from that event to the evaluation time. A pause during the window is allowed, but the gate cannot
   pass while the office is paused.

## Pass criteria (all must hold)

| # | Check | Pass when | Source |
|---|---|---|---|
| 1 | `elapsed` | at least 14 × 24 h between `gate_started` and evaluation | event timestamps |
| 2 | `history` | every commit on `claude/office-state` only appended to the log (`audit_history`) | git history |
| 3 | `heartbeat` | no gap longer than 2H between consecutive worker runs (gate start, every run start, evaluation time) | `worker_started` |
| 4 | `runs_finish` | at most 5% of closed runs recorded no `worker_finished` | worker events |
| 5 | `no_duplicates` | no task completed twice, and no result recorded under a superseded lease | task events |
| 6 | `no_orphans` | no expired lease left unrecovered for more than 2H | derived task state |
| 7 | `daily_outputs` | every full UTC day in the window has health and digest done | derived task state |
| 8 | `core_never_quarantined` | no health or digest task quarantined | derived task state |
| 9 | `r0_only` | only office event kinds and the four R0 task types appear | log |
| 10 | `crash_recovered` | at least one crash drill was recovered by a later run | `recovered_fence` on a claim |

A breach of checks 2–6 or 8–9 fails the run at once. The fix becomes a new commit, and a new `gate_started` begins
a fresh 14 days. Check 10 needs a deliberate drill: after day 2, one heartbeat runs
`python3 -m office worker --drill-crash`, which exits right after its first claim, and a later run must recover the
task.

A failing test suite on master, or a skipped or failed demo snapshot, does not fail G1. Each raises an alert and
appears in the digest. G1 tests the office, not the code it checks.

## Measured and reported, not pass/fail

The gate report includes each of these as measured. Where something was not measured, the report says so.

- **Scheduled versus completed runs.** Expected runs are the window divided by H; the count is of `worker_started`.
- **Missed, duplicate, stuck and recovered tasks.** Checks 3–6 and the health report.
- **Data and integration failures.** Failed and quarantined tasks, with their error text.
- **Resource use.** Run seconds from `worker_finished`, and the number of sessions. Plan usage is not visible to the
  office: the owner reads it in claude.ai usage settings. **No paid service is used.**
- **Alert delivery.**
  - Alerts reach the owner through the daily digest thread posted by the digest task.
  - Email delivery is **not part of G1 and not claimed**. It stays off unless the owner approves a separate test.
- **Permission enforcement.** Check 9, plus the handler tests: credentials are stripped from test runs, the demo read
  goes through `ReadOnlyClient` with the kill file set, and no order method is reachable.
- **Paper portfolio and reconciliation.** **Not measured: no paper book exists in the office yet.** This is stated in
  every gate report.

## Honesty rules

- Elapsed time comes only from timestamps the store writes from the real clock. Tests use a fake clock and never
  touch `claude/office-state`. A shortened run is never extrapolated.
- Event timestamps and commit dates are both written by the worker. Each `worker_started` therefore also records the
  cloud session id, and the session list (with server-side times) is a second, independent record for spot checks.
- The gate report is preserved in the log, and the final report is committed beside this file. A failed run stays
  recorded.

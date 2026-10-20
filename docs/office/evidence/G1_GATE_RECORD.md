# G1 14-day reliability gate: start record (verified 20 Oct 2026 13:10Z)

Every value below was read from its primary source in this session: the state branch, git, the scheduled-task
service and `python3 -m office gate-report`. Nothing here claims the gate has passed.

## Start

| Item | Value | Source |
|---|---|---|
| Gate start | `gate_started` 2026-10-20T11:56:57Z, criteria `G1`, heartbeat_s 10800 (3 h) | event log, `claude/office-state` |
| Owner authorisation | cmsg_01U4KMvkBYNknqm4HRVie8uv4jhm7TxpcEjQ5hAcQjmFxe (20 Oct 09:29Z) | same event |
| Earliest pass | 2026-11-03T11:56:57Z (14 × 24 h of event time; elapsed time is never fabricated) | `gate.py` DAYS = 14 |
| Deployed commit | master `b0e494b99c9f39de06de12001b1e44d35f76165e` (PR #25 merged after PR #26) | `git rev-parse origin/master`; `code` field of both `worker_started` events |
| State branch | root `8428e34ae414ee50f1ddaf95827c2d5c7f99720d` (pinned in `__main__.ROOTS`); head at record time `55059eb` | git |

## Criteria (fixed before the start; identified by hash at the deployed commit)

| File at `b0e494b` | sha256 |
|---|---|
| `docs/office/RELIABILITY_GATE.md` (the written criteria) | `f0c024331a3d9ace31333ec2f5d10d3655fc0d6f46d16a0cd295145ce4f8d347` |
| `office/office/gate.py` (the evaluator, `CRITERIA_VERSION = "G1"`) | `fe7f3dc4821fb8dd83b0895de657ad0252bd19c54ff9c55373554c9c9568680e` |
| `office/office/health.py` (run and alert rules it uses) | `d8a1b281698c8f0a71226dd1a71b379e249af44ffc37877256a9ed65428805b2` |
| `office/WORKER.md` (worker prompts) | `ba23f2c1cd128044c3836e1935bc2d3c751ad0a42ba93dae2a97c39c047ad30c` |

Checks: elapsed ≥ 14 days · history append-only · longest heartbeat gap ≤ 2 × 3 h · ≤ 5% of runs unfinished · no
task completed twice or from a stale lease · no expired lease left unrecovered for two heartbeats · health and digest
done every full day · health and digest never quarantined · R0 task types only · at least one crash recovered (drill).
PR #27 changes none of these files (`git diff --stat b0e494b HEAD` on them is empty).

## Schedule

| Scheduled task | Id | Schedule (UTC) | Notes |
|---|---|---|---|
| Edge office heartbeat (every 3 h) | trig_01UjCc8hupRgyh39BhJpxUBR | `57 */3 * * *`, fresh session each run | Created 12:02:49Z. Installs pytest if missing, unique run folder, reports alerts |
| Edge office heartbeat (old) | trig_01GX9V7x4sfQk7hPDFZK6vXs | same | Switched off 12:02:52Z, kept for its run record. Ran once (manual fire 11:57:20Z) |
| Edge office daily digest | trig_01LG9gbwm13WSoJtZ8yV2dXL | `52 6 * * *` | First run 21 Oct 06:52Z |

The heartbeat change came before the next scheduled slot (12:57Z), which ran: the longest gap so far is 1.00 h.

## Runs so far

| Run | Session | Result |
|---|---|---|
| 11:58:32Z | cse_01Td3TADVs8B6QNoJ6BBzxT6 (old task, manual fire) | 4 of 4 tasks done: health, test_suites, demo_snapshot (22 positions, 1,221.56, 0 pending), digest |
| 12:58:30Z | cse_01PLDDiTxRHUAJyRa7fRb3Ad (new task) | 0 tasks planned (today's were done), finished idle in 6.7 s |

## Gate report at 13:10Z

Verdict **running**. Passing: history, heartbeat, runs_finish, no_duplicates, no_orphans, core_never_quarantined,
r0_only. Not yet met (time-dependent): elapsed (0.05 of 14 days), daily_outputs (0 full days), crash_recovered (drill
due 23 Oct).

## Open alert: `tests_failing` (critical)

- It comes from the 11:58:53Z test_suites output on `b0e494b`: all four suites exited 1 with no pytest summary. Cause
  **inferred, not observed**: `b0e494b` does not record stderr. pytest is not in the base image: in this session's
  container it was installed by hand on 19 Oct 14:15Z. The 21 Oct run will confirm or refute this.
- The 12:58Z run did not re-run the tests (one test task per UTC day). It only re-reported the same output, which
  health carries for 36 hours, until about 21 Oct 23:59Z.
- The tests themselves pass on `b0e494b` in a session with pytest: trading 139, equity 118, research 460, office 43.
- The alert is not a G1 criterion. It is resolved only when the 21 Oct test task (first run 00:57Z) passes.
  Not yet proven.

## Changes during the gate

- 12:02Z: heartbeat task recreated with a new prompt; same schedule, same code (`b0e494b`). No criterion file changed;
  no restart required by G1 (the criteria measure the event log, not the task id).
- PR #27 is not merged. If it is merged during the gate, workers run new code for `test_suites` only (stderr capture
  and the `test_runner_missing` alert). No criterion file changes, and none of its other code is run by the worker.

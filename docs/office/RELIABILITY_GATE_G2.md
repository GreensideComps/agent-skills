# Unattended-operation gate G2 (criteria fixed before any run)

Status: **proposed, not authorised, not started.** No G2 `gate_started` event exists. Nothing may describe the office
as operating unattended, always-on or autonomous until a G2 run has passed.

G1 failed on 21 Oct 2026 (check 3 `heartbeat`, longest gap 6 h 01 min 07 s against 6 h 00 min). Its criteria
(`RELIABILITY_GATE.md`), event history and evidence stay exactly as they are. `gate.py` still scores a gate whose
`gate_started` names `criteria: "G1"` under the G1 rules, so the G1 verdict is reproducible from the log:
`python3 -m office --heartbeat-h 3 gate-report --gate-seq 0 --at 2026-10-21T10:01:00+00:00`.

G2 is a new run with new, pre-registered rules. It is not a re-scoring of G1.

## What changes from G1

| Kind | Change | Affects the verdict? |
|---|---|---|
| Criterion | Check 3 limit is 2H + 900 s (6 h 15 min at H = 3 h), not 2H | yes |
| Operational | Health warns `heartbeat_overdue` when no run has started for more than H + 900 s, and `heartbeat_missed` for a day after a gap longer than H + 900 s | no (alerts only) |
| Operational | The heartbeat prompt states plainly what the command does and stops, without retrying, if a step is refused (`office/WORKER_G2.md`) | no |
| Alert display | A task alert stops being live once a later completion of the same task type has no alert; the original event stays in the log and the report lists it under `cleared_alerts` | no |

Everything else is G1 unchanged: checks 1, 2 and 4-10, the 14 days, H = 3 h, R0 work only, the drill.

## Check 3 `heartbeat`, exactly

- **Timestamp used:** the `ts` field of each `worker_started` event. The store writes it from the worker session's real
  clock when the run records its heartbeat. Cron fire times and session creation times are not used.
- **Marks:** the `gate_started` ts, then the ts of every `worker_started` at or after it in time order, then the
  evaluation time.
- **Gaps:** the differences between consecutive marks, in seconds. The last gap (latest run to evaluation time) counts,
  so an open gap fails the gate as soon as it is too long.
- **Limit:** 2 × `heartbeat_s` + 900 s, with `heartbeat_s` read from `gate_started` (10 800 s), so 22 500 s.
- **Breach:** any gap strictly greater than 22 500 s. A gap of exactly 22 500 s passes.
- **Missed runs:** a scheduled run that never records `worker_started` (session refused, never started, or failed
  before the worker ran) leaves no event, so the gap simply spans it. One missed run between two on-time runs gives a
  gap of about 6 h plus the difference in start lag, which passes. Two missed runs in a row give about 9 h and fail.
  A late run (for example a session held by an account usage limit) shortens nothing: its gap is measured from its
  real start.
- **When it fails:** at once. The verdict becomes `fail` and stays `fail`; the 14 days cannot then pass.
- **Detail reported:** the run count, the longest gap in seconds with its start and end marks, and the limit.

The 900 s margin covers the session start lag measured on 20-21 Oct (93-189 s after the scheduled fire). It does not
cover a missed run followed by a usage-limit delay longer than about 12 minutes; that still fails G2.

## Pass criteria (all must hold)

| # | Check | Pass when | Source |
|---|---|---|---|
| 1 | `elapsed` | at least 14 × 24 h between `gate_started` and evaluation | event timestamps |
| 2 | `history` | every commit on `claude/office-state` only appended to the log (`audit_history`) | git history |
| 3 | `heartbeat` | no gap longer than 2H + 900 s, as defined above | `worker_started` |
| 4 | `runs_finish` | at most 5% of closed runs recorded no `worker_finished` | worker events |
| 5 | `no_duplicates` | no task completed twice, and no result recorded under a superseded lease | task events |
| 6 | `no_orphans` | no expired lease left unrecovered for more than 2H | derived task state |
| 7 | `daily_outputs` | every full UTC day in the window has health and digest done | derived task state |
| 8 | `core_never_quarantined` | no health or digest task quarantined | derived task state |
| 9 | `r0_only` | only office event kinds and the four R0 task types appear | log |
| 10 | `crash_recovered` | at least one crash drill was recovered by a later run | `recovered_fence` on a claim |

A breach of checks 2-6 or 8-9 fails the run at once. A pause during the window is allowed, but the gate cannot pass
while the office is paused. A failing test suite on master, or a failed demo snapshot, raises an alert and appears in
the digest but does not fail G2.

## Crash-recovery drill (part of G2)

Once, after day 2 and before day 5, a one-off session runs the heartbeat prompt with `worker --drill-crash` at a time
at least 60 minutes from any scheduled heartbeat. The worker records `worker_started`, claims one task, prints the
claim and exits with code 3 without running the task or recording `worker_finished`.

**Pass conditions (all):**
1. The drill run's `worker_started` and one `task_claimed` are in the log, and no `worker_finished` for that run.
2. A later regular run claims the same task with `recovered_fence` equal to the drill claim's seq, within 2H of the
   lease expiring (check 6), and completes it exactly once (check 5).
3. After that, check 10 `crash_recovered` passes and checks 4, 5 and 6 still pass.

**Fail conditions:** the task is completed twice, its lease is left unrecovered for more than 2H, or a result is
recorded under the drill's superseded lease. Each of these fails G2 at once. If the drill session itself is refused
or never starts, that is recorded as it happened; there is no workaround, and the owner decides whether to schedule
one more drill. Without a recovered drill, check 10 is unmet and G2 cannot pass.

**Safety limits:** the same prompt boundaries as every heartbeat. A fresh detached checkout of master, with
`trading/KILL` touched first. R0 task types only, so the claimed task is health, test_suites, demo_snapshot (read-only
demo client) or digest. The only process ended is the worker's own (`os._exit(3)`). The drill kills no other session,
deletes nothing, and changes no scheduled task, broker setting or permission. It writes only to `claude/office-state`.

## Measured and reported, not pass/fail

As in G1: scheduled versus completed runs, missed and late runs (now also as `heartbeat_missed` warnings), recovered
tasks, data failures, run seconds, alert delivery through the daily digest (email is not part of G2 and not claimed),
and permission enforcement. **Not measured: no paper book exists in the office yet.** Plan usage is not visible to the
office; the owner reads it in claude.ai usage settings. No paid service is used.

## Honesty rules

As in G1. Elapsed time comes only from timestamps the store writes from the real clock, and a shortened run is never
extrapolated. Each `worker_started` records its cloud session id, so the session list is an independent check. The
gate report is preserved in the log, and the final report is committed beside this file. A failed run stays recorded.

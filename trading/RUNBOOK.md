# Runbook: continuous operation

Two scheduled cloud routines keep the system running without prompts. Both fire into
one dedicated session, **`T212 demo: trading ops (scheduled, v2)`**. It was created with this repo as
its source **and** `claude/trading212-agent-skills-r71zy3` as its output branch, which gives it two things:
- it reads [`.claude/settings.json`](../.claude/settings.json), so the allow rule for `bash trading/ops_run.sh` applies;
- the git proxy lets it push.

| Routine | When | What it does |
|---|---|---|
| **T212 demo: trading ops** | Weekdays 08:20 London (moved from 10:07 on 2026-10-13) | `trading/ops_run.sh`: tests → `run --execute` (trades only if a rebalance is due) → report → commit journal |
| **T212 demo: research loop** | Daily 01:13 and 13:13 London | Follows [`../research/LOOP.md`](../research/LOOP.md): next agenda item → rigorous test → [promotion gate](../research/PROMOTION_GATE.md) → log → commit |

### Lessons from setup (2026-10-13)
- A fresh routine session with no repo attached: the classifier blocks `ops_run.sh`, and `git push` gets a 403 (the repo isn't an authorised source). The first research test run lost its P1/P2 results this way.
- A session needs **both** source and output branch set for unattended trading plus pushing.
- Manual "fire now" and creating extra sessions may be blocked by the permission classifier. The owner can use "Run now" in claude.ai → Routines instead.

Run by hand from any session that has the repo: `bash trading/ops_run.sh`.

## Stopping things

| You want to… | Do this |
|---|---|
| Stop everything | Tell Claude "stop". It deletes both routines. |
| Pause trading only | Add a file `trading/KILL` to the branch. Runs still snapshot but place nothing. |
| Pause research only | Add a file `research/STOP` to the branch. |
| Undo a strategy change | Revert the commit that changed `trading/config/strategy.json`. |

## Where to look

- `trading/PERFORMANCE.md`: account vs benchmarks, fill quality, the honest statistics
- `research/LOG.md`: every research run and its decision
- `research/AGENDA.md`: what's being researched next
- `trading/journal/events.jsonl`: every decision, order, rejection and fill (append-only)
- `trading/journal/snapshots.csv`: account value at every run

## Failure handling

| Symptom | Behaviour |
|---|---|
| Tests fail | No trading that day. The status is logged and you're notified. |
| Market closed or holiday | Run is deferred, with nothing placed |
| Pending orders exist | Run is skipped |
| Order timeout or 5xx | Bot reconciles, journals `order_ambiguous`, stops, never resends. The next run reconciles again. |
| Insufficient-funds rejection | Re-sized against fresh cash, at most 3 attempts. The cash-hold estimate is updated. |
| Stale or divergent quote | Run fails safely before any order (`run_failed` in the journal) |
| Git push conflict | Rebase and retry, up to 4 times |

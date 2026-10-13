# Runbook: continuous operation

Two scheduled cloud routines keep the system running without prompts. Each
firing starts a fresh session in this environment, works on branch
`claude/trading212-agent-skills-r71zy3`, and commits its results back.

| Routine | When | What it does |
|---|---|---|
| **T212 demo: trading ops** | Weekdays 10:07 London | `trading/ops_run.sh`: tests → `run --execute` (trades only if a rebalance is due) → report → commit journal. Sends a push notification on anything noteworthy. |
| **T212 demo: research loop** | Daily, 01:13 and 13:13 London | Follows [`../research/LOOP.md`](../research/LOOP.md): picks the next agenda item, researches it, applies the [promotion gate](../research/PROMOTION_GATE.md), logs results, commits. |

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

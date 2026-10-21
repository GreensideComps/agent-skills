# Office scheduled tasks for G2 (proposed prompts, not deployed)

Status: **proposed, not deployed.** The G1 heartbeat (`57 */3 * * *`) keeps running unchanged until the owner approves
G2. `WORKER.md` keeps the G1 text. When G2 is approved, the heartbeat below replaces the G1 heartbeat: a new
scheduled task is created with this exact prompt and the old one is disabled, not deleted, so its run history stays.
The daily digest task stays as it is; it already reports whichever gate is latest.

## What is different from the deployed G1 heartbeat, and why

The commands in steps 1-5 are byte-identical to the deployed G1 heartbeat prompt (20 Oct 13:48Z). Three things change:

1. **A plain statement of what the run is.** On 21 Oct 06:57Z the session's safety check refused the worker command
   as a real-world transaction. The prompt now says what the command does and what it cannot do, all of it true and
   checkable in `office/office/handlers.py`. Nothing in it asks for a check to be skipped or a permission widened.
2. **Stop on refusal.** If any step is refused, the session must not reword, split or retry the command, or ask for
   wider permission. It prints the refusal, posts one line in the project and stops. The run is then missed, as G1's
   06:57Z run was, and the gap rules in `docs/office/RELIABILITY_GATE_G2.md` decide the effect.
3. **Minute 12 instead of 57.** `12 */3 * * *` keeps the 3-hour heartbeat clear of the 06:45, 06:46 and 06:52 UTC
   routines and the 22:27 London research pipeline. No evidence shows that contention caused a G1 miss; this is a
   no-cost precaution.

The prompt has not been run yet. Whether the safety check accepts it can only be shown by running it, which is step 6
of the G2 start procedure and needs the owner's approval.

## Heartbeat worker (every 3 hours, a fresh session each run)

Cron `12 */3 * * *` UTC.

```
You are the Edge office heartbeat: a scheduled health check of this repository's own monitoring code. Do exactly this and nothing else.

What the command does: it runs four internal checks (log health, the repository's test suites, a read-only snapshot of a Trading 212 DEMO paper-money account, and a written digest) and records the results on the repository's own claude/office-state branch. It cannot place, change or cancel orders: no order code is reachable from it, the demo read goes through a read-only client, and step 2 sets the trading kill switch before anything runs. It never touches a real-money or ISA account.

1. From the repository checkout in your working directory, run:
   RUN=$(mktemp -d /tmp/office-run-XXXXXX) && git fetch -q origin master && git worktree add -q --detach "$RUN/repo" origin/master && echo "$RUN"
   (if the worktree command fails, instead: git clone -q --depth 1 --branch master "$(git remote get-url origin)" "$RUN/repo")
   Use that printed folder as RUN in the next steps. Never delete any folder.
2. Run: touch "$RUN/repo/trading/KILL"
3. The office's daily test task needs its declared test dependencies. Run:
   python3 -m pip install -q -r "$RUN/repo/office/requirements-worker.txt"; echo "pip exit $?"
   If the install fails, carry on; the test task will then report the failure.
4. Run: cd "$RUN/repo/office" && python3 -m office --heartbeat-h 3 worker --out-dir /mnt/project-files/research/office/digests
   (omit --out-dir if /mnt/project-files does not exist). Wait for it to finish, however long it takes.
5. Run: cd "$RUN/repo/office" && python3 -m office --heartbeat-h 3 status
6. Print the pip exit code, the worker's JSON output, then every alert from the status output (level, code, text), as your whole answer. If a command failed, print the last 30 lines of its error instead.

If any step is refused by a safety check or a permission prompt: do not reword, split or retry it, run it another way, or ask for wider permissions. Print "REFUSED at step N:" and the refusal text, post that one line in the project, and stop.

Never: place, modify or cancel an order; run anything under trading/ other than what the command runs; run research scripts; edit, commit or push any file yourself (the office writes only to its own claude/office-state branch); create, change or delete scheduled tasks; send email; read or change the live ISA. Do not post any message in the project unless a step was refused, a command failed or the status shows a critical alert.
```

## Crash drill (once, a one-off session after day 2 of G2)

The same prompt with one change: step 4 runs `worker --drill-crash` in place of `worker`, and step 6 also prints the
drill line (`{"drill": "exiting after claim", ...}`) and the exit code, which is 3 by design. Pass and fail conditions
and the safety limits are in `docs/office/RELIABILITY_GATE_G2.md`.

## Stopping it

- Emergency stop, durable: `python3 -m office pause --reason "..."`. Every later run records its heartbeat and does
  nothing else, and the gate cannot pass while paused. Only `resume --owner-message cmsg_...` lifts it.
- Stopping completely: disable the heartbeat and digest tasks. The log keeps everything that happened.

# O10: point the weekday brief at master (20 Oct 2026)

**Status: prepared and tested, NOT applied.** `update_trigger` refused the prompt change on 20 Oct (~08:15Z): this
task starts a new thread at each run, and such a task can only be changed by deleting and recreating it. The owner's
instruction rules out recreating scheduled tasks, so the task still holds the "before" prompt and the decision is
the owner's (recreate it with the new prompt, or leave it). `get_trigger` after the refusal shows it unchanged
(`updated_at` 2026-10-15T08:16:46Z).

Owner approval: message `cmsg_01U4KMvkBYNknqm4HRVie8uvU3uARM8qp1vWB8L62R9Sqa` (07:53Z), item 2. Only the prompt of
scheduled task `trig_012o3Bc5Ja2PiD7rvx2Fzrmd` ("Weekday portfolio brief") changes. Its schedule (`45 6 * * 1-5` UTC),
enabled state, fresh session per run, notifications and model are unchanged. No other scheduled task is touched.

Before and after prompts, with sha256, are in `WEEKDAY_BRIEF_CHANGE_RECORD.json`. The new prompt is
`WEEKDAY_BRIEF_PROMPT.txt` (the tests read it).

## What changes and why

| | Before | After |
|---|---|---|
| Branch | retired bot branch `claude/trading212-agent-skills-r71zy3` (its CLI now exits 5) | `master` |
| How it reads | "use its read-only client" (unspecified) | one fixed command: `ReadOnlyClient(T212Client(load_credentials()))`, reading summary, positions and pending orders |
| Bot CLI and scripts | not mentioned | forbidden by name |
| Kill switch | none | `touch trading/KILL` in the clone before anything else |
| strategy.json | flag a mismatch with its targets | do not act on it or compare with it (retired, O10) |
| Fallback | last journal snapshot | say it failed; no old figures (the repo journal's last snapshot is 14 Oct, before the pie copy) |
| Config, git, routines | "never change any routine or config" | never edit trading/config, never commit or push, never change any routine, setting or permission |

## Why it stays read-only

- The read command uses `ReadOnlyClient`, which only exposes eight GET methods. Order, cancel, `_request`, the
  wrapped client and attribute assignment raise `SafetyError` [tested].
- `load_credentials` refuses anything but `T212_ENV=demo`, and `T212Client` refuses any base URL but the demo host.
- Master is not guarded like the bot branch, and its strategy file is still the old 100% LQQ3 discretionary config
  until PR #20 merges. So the prompt adds a second, code-enforced stop: the kill file. `Bot.run` (which `decide`
  also calls) halts on it before any order [tested, with a control run that does order when the file is absent].
- The trading key in the environment could place demo orders through the full client. Only the prompt stops a
  session from writing its own code to do that; no code on master can. This was equally true before the change.

## Tests (`trading/tests/test_weekday_brief.py`, 8 tests)

All run offline: credentials stripped, every call answered by the in-memory fake broker or refused.
1. The prompt names master, not r71zy3, creates the kill file before the read, and carries every prohibition.
2. The exact read command from the prompt, run in a child process, prints the account and makes exactly three GETs.
3. It fails closed when `T212_ENV` is not `demo`, with no call.
4. `ReadOnlyClient` refuses order, cancel and internal access.
5. to 7. `run --execute --force`, `decide --set LQQ3l_EQ=1.0 --execute` and `decide --cash --execute`, run by mistake
   in a copied clone with the kill file, send no non-GET request and leave this checkout's config and journal
   unchanged.
8. Under master's committed strategy, the kill file halts `Bot.run` with no order; the same run without it orders.

Limit: the tests cover the commands the prompt names. A session that ignored the prompt could write its own code;
the kill file and the read-only client do not stop that. PR #20, once merged, adds the retired strategy and the
order-method refusals on master.

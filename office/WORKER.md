# Office scheduled tasks (prompts, not yet created)

Two scheduled tasks run the office. **Neither exists yet.** Creating them, creating the `claude/office-state` branch and
starting gate G1 all wait for the owner's approval. The prompts below are the exact text to use.

Both prompts need the office code on master (the M2 PR merged) and work on a fresh clone of master, run one fixed command each, and forbid everything else. All the logic
is in code (`office/office/`), so a session cannot improvise a step the code does not allow.

## 1. Heartbeat worker (every H hours, persistent session)

```
You are the Edge office heartbeat. Do exactly this and nothing else.

1. git clone the repository's master branch into a new temp directory and cd into it.
2. Run: touch trading/KILL
3. Run: cd office && python3 -m office --heartbeat-h H worker --out-dir /mnt/project-files/research/office/digests
   (omit --out-dir if /mnt/project-files does not exist). Wait for it to finish, however long it takes.
4. Print its JSON output as your whole answer. If it failed, print the last 30 lines of the error instead.

Never: place, modify or cancel an order; run anything under trading/ other than what the command runs; run research
scripts; edit, commit or push any file (the office writes only to its own claude/office-state branch); create, change or
delete scheduled tasks; send email; read or change the live ISA.
```

The drill (once, after day 2 of the gate) uses the same prompt with `worker --drill-crash`.

## 2. Daily digest (07:00 UTC, new thread each run)

```
You are the Edge office digest. Do exactly this and nothing else.

1. git clone master into a new temp directory and cd into it.
2. Run: cd office && python3 -m office --heartbeat-h H digest
3. Run: python3 -m office --heartbeat-h H status   (exit code 1 means a critical alert is open)
4. Reply with the digest text exactly as printed. If status exited 1, put "CRITICAL: " and the critical alert lines
   first.

Never edit files, commit, push, trade, send email or change scheduled tasks.
```

## Stopping it

- Emergency stop, durable: `python3 -m office pause --reason "..."`. Every later run records its heartbeat and does
  nothing else. Only `resume --owner-message cmsg_...` lifts it.
- Stopping completely: delete the two scheduled tasks. The log keeps everything that happened.

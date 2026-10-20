# PR #25 safety review (owner instruction M-25), 20 Oct 2026

Two passes:
- my own checks;
- an independent read-only review by a separate agent with no write access, which ran the offline office tests only.

## Critical checks (all pass)

| Check | Result |
|---|---|
| No broker write path | Pass. The only broker access is the demo read through `ReadOnlyClient` (summary, positions, pending orders). `T212Client` refuses any host but the demo one. `orders.py` is imported by nothing and has no broker adapter. |
| Live ISA unreachable | Pass. The demo read is skipped unless `T212_ENV=demo`; there are no live credentials in the environment. |
| Email off | Pass. `ctx.email` is never set by the CLI. |
| Research untouched | Pass. The diff against master changes no file under `research/`. No run, registration or holdout read is possible. |
| No secrets in the diff | Pass (pattern scan of the full diff). |
| Append-only log | Pass. Pushes are never forced. The history audit checks every commit, and now also the pinned root commit. |
| Bounded runs | Pass. Every subprocess and git call has a timeout; at most 8 tasks and 2400 s per run; transactions retry at most 30 times. |
| Tests on the merge candidate (offline, no credentials) | trading 139, equity 118, research 460, office 43: all pass |

## Findings from the independent review, all fixed in this PR

No finding was critical. Each fix below has a test.

1. **MAJOR: the GitHub queue script could delete a branch it did not create** (`--branch claude/office-state`).
   It now refuses any name not starting `office-queue-test-`, and deletes only a branch this run created.
2. **MAJOR: the demo read inherited the whole environment** (GitHub tokens and other variables). It now gets an
   allowlist: the demo key, the proxy and CA settings, `PATH`, `LANG`, `TZ` and a scratch `HOME`.
3. **MAJOR: a history rebuilt from scratch with a valid chain would pass the audit.** The root commit of
   `claude/office-state` (`8428e34`) is now pinned in code, and the audit fails if the root differs. The walk is
   `--first-parent`, which also closes minor finding 8.
4. **MAJOR: the test-suite lease could be shorter than the suites' worst case.** All suites now share a 2700 s budget,
   inside the 3600 s lease, and a suite that would run past it is recorded as a timeout.
5. **MINOR: error text went into the log verbatim.** URL credentials and the values of secret variables are now
   redacted before any failure text is recorded.
6. **MINOR: the test runs kept non-listed variables.** They now use an allowlisted environment with a scratch `HOME`,
   and `NO_PROXY` is emptied so every request goes to the dead proxy.

## Not changed

- **Finding 7:** digests are written under `/mnt/project-files/research/office/digests`. This is the office's
  existing shared folder; nothing in the research tree is read or changed.
- **A residual risk, inherent to the design:** the worker and the log are written by the same sessions, so the log
  can only prove what those sessions recorded. Session ids recorded in `worker_started` give a second, server-side
  record for spot checks.

# Edge status (durable; updated each working session)

Last updated: 2026-10-20 by the "Research office" thread. Labels: **[V]** verified directly in this session,
**[T]** a test asserts it, **[A]** inference or report not re-checked.

## Verified state

- **master:**
  - `11512d40369f009f023c40dcaa905dd533033c46`, tree `f12ba23c8d2c3229ab167366ad9e272d04da05f2`, parents `93b66f4`
    and `b2ea086` [V].
  - Offline tests on a clean master checkout: trading 139, equity 118, research 460 (717 in all), all pass [V].
- **Research state:**
  - Registry 102 trials; `b5_trial_run` authorised = false [V].
  - No lock file in `research/edge` [V].
  - No edge has been established: every Stage 2 signal and both B5 trials failed [V: reports on master].
- **CI:** none. There is no `.github/` directory, so nothing runs tests automatically on a push [V].
- **Live ISA:** not connected. Only demo credentials are in the environment (`T212_ENV=demo`) [V].

## Capability audit (A–G)

Categories: **IV** implemented and verified · **IU** implemented, not verified in operation · **P** partial ·
**M** missing · **B** blocked · **U** unsafe or unsuitable as is.

| Area | Capability | Cat. | Evidence |
|---|---|---|---|
| A | Durable job state outside a session | IU | Office event log on a git branch: a hash chain, compare-and-swap push and an ambiguous-push check (`office/office/store.py`, 27 M1 tests [T]). The real GitHub branch was exercised once on 19 Oct [V]; it is not deployed. |
| A | Atomic claims, leases, fencing, crash recovery | IU | `queue.py` [T]: two workers never hold one task, an expired lease is recovered, a late result is refused. |
| A | Scheduler and worker that run with nobody prompting | IU | M2 `worker.py`, run by a heartbeat scheduled task. The prompt is written (`office/WORKER.md`); the task is not created (owner decision). |
| A | Stalled-job and silent-worker detection, alerts | IU | `health.py` [T]: worker silent for more than 2 heartbeats, runs that never finished, quarantined or blocked tasks, task-raised alerts. |
| A | Existing scheduled tasks | P | 4 active (weekday brief, monthly signal log, equity daily pipeline, weekly discovery) [V: list_triggers]. Equity pipeline last run 19 Oct exited rc=1 [V]. Brief still clones the bot branch [V]. |
| B | Next research question chosen without prompting | M | No research director exists. Research runs only on an owner-approved manifest by design (D-series). |
| B | Hypothesis registered before testing | IV | `edge_registry` and manifest gate; run 2 executed only against registered MANIFEST-3 [V: registry, tests]. |
| B | Permissions and resource limits enforced in code | IV | `edge_b5_run.py` refuses without an unspent owner authorisation, matching lock and file hashes [T] (research 460). |
| B | Failures and inconclusive results recorded | IV | Run 1 failure recorded (D26), run 2 results with both fails [V]. |
| B | New evidence versus seen holdout | P | 2023–26 holdout recorded as PARTLY SEEN (DECISIONS.md); DSR counts prior trials. Untouched data does not exist for that window [V]. |
| C | Data sources connected | P | Yahoo prices (free, survivorship-biased) and SEC companyfacts [V]. Paid survivorship-free data not bought (owner). |
| C | Point-in-time and delisted coverage | U | Delisted firms over $1bn not priced; the bias is unbounded (B4, D13) [V]. Acceptable for exploration only. |
| C | Data-quality detection | P | Input audits, share-PIT audit, negative-price guard [V]. Check 4 coverage gap: 26–31% of eligible rows unscored (PR #23) [V]. |
| C | Costs, slippage, turnover | IV | 0.30% one-way, next-day close in the B5 engine, synthetic validation B2 [T]. |
| C | Multiple testing, holdout exposure | IV | DSR with N = 102, one confirmation batch rule [V]. |
| C | VWRP benchmark | P | B5 uses VWRL→VWRP [V]. The equity paper book benchmarks against **SPY**, not VWRP [V: `equity/equity/paper.py`]. |
| D | Portfolio manager that justifies positions | M | No component decides positions from evidence. The equity paper book follows the screen; the old bot strategy is retired. |
| D | Sizing, concentration, drawdown limits in code | P | Bot executor has position and order caps [A: not re-audited]. Nothing at portfolio level against VWRP. |
| D | Documented no-trade outcome | IV | Strategy V2 and Stage 2 decisions: no signal may drive sizes; VWRP fallback [V]. |
| D | Out-of-sample and paper evaluation | P | Equity paper book runs daily [A: pipeline rc=1 on 19 Oct]. No VWRP-relative paper gate. |
| E | Broker interfaces and permissions | IV | Demo key only; `ReadOnlyClient` blocks non-read methods [T]. Retired bot branch refuses its CLI [T, b61e8f7]. |
| E | ISA read-only | B | Not connected at all. Read-only is a property of the future key, the owner's decision. |
| E | Paper separate from live | IV | Bot code reaches the demo host only [V: earlier audit]; the office has no order path [T: `r0_only`]. |
| E | Intent, ambiguous outcome, reconciliation | P | Bot: ambiguous POST stops and reconciles [V: executor.py:124]. Office `orders.py` state machine has no broker adapter [T]. |
| E | Halt all trading | IV | Kill file and `T212BOT_KILL` [T]. Office: durable pause event and stop file [T]. |
| F | Durable decisions and authorisations | IV | DECISIONS.md, registry, status.json history [V]. Office: append-only log with history audit [T]. |
| F | Secrets | IV | Not in commits or logs [V: test fixtures strip them]. Office test runs strip every credential variable [T]. |
| F | Permissions in the execution layer | P | Research gate and read-only client in code [T]. Weekday brief and master still depend on prompts until PR #20 [V]. |
| F | Alert delivery | P | Email via Resend works (3 real sends, one an incident) [V]. Office alerts go to digest files and a thread; email is off. Thread delivery is not yet tested for the office. |
| F | Automated tests and CI | P | 717 tests on master plus 40 office tests [V]. No CI; the office `test_suites` task is the substitute once deployed. |
| F | Proof of completed work | IU | Every office result is a log event tied to a fenced claim. The gate recomputes from the log [T]. |
| G | Reusable components | — | Bot client and read-only facade, emailer, equity reliability checks, B5 engine. The office reuses them through a subprocess and does not rebuild them. |
| G | Dead or duplicate code | — | Retired bot branch (guarded). Old T212 entries in `equity/config/schedule.json` caused a false warning; removed on this branch. |

## What works end to end today

- Owner-gated exploratory research runs (B5) with registration, locking, recording and reports [V].
- Daily equity pipeline (screen, paper book, monitor) [A: last run failed].
- Weekday demo brief [V: 20 Oct run].

Nothing runs as a supervised, self-recovering system yet.

## Highest-priority blockers

1. **Owner approval to deploy the office:** create `claude/office-state`, the heartbeat and digest tasks, and start
   G1 (criteria in `RELIABILITY_GATE.md`). Uses plan usage only.
2. **Code must be on master** before the scheduled prompts can clone it: the M2 PR needs review and merge.
3. **Pack B decisions** (weekday brief, decile rule, unscored option, M1 branch) block only their own steps.

## Risks

- Cloud scheduled sessions failed 3 of 6 runs on 14 Oct in a shared persistent session [V: earlier audit]. G1
  measures this directly.
- A git push from a scheduled session to `claude/office-state` is assumed, not yet tested from a scheduled session [A].
- Plan usage limits are unknown here. The budgets in code (8 tasks and 40 minutes per run) cap use per run, not per
  month.

Next actions: see `TASK_LEDGER.md`.

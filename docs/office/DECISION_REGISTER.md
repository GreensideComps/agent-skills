# Investment manager: decision register and queue evidence

Written 2026-10-19 (~14:40-15:20 UTC) after the owner's decisions on O1-O13 (owner message
`cmsg_01U4KMvkBYNknqm4HRVie8uv5WhbXFRm6KFGKqgHWHri4W`, 14:36Z). Companion to `INVESTMENT_MANAGER_PLAN.md`.
Read-only inspection and planning only: nothing was built in the repository, no scheduled task was created or enabled, no
order was placed, no permission or account was changed. The queue tests in section 2 ran on a local throwaway git
repository in the session's scratch space, not on GitHub.

**Correction to the plan (section 1.7):** I wrote that the equity pipeline had "no fire and no commit for Fri 17 Oct".
That was wrong: 17 Oct 2026 was a Saturday, and the task only runs on weekdays. It fired and committed on every weekday
since it was created (14, 15 and 16 Oct). The plan file is corrected.

Status key: **Approved** = the owner approved it and it can be built when its dependencies are met. **Blocked** =
approved, but it cannot proceed until something else happens. **Awaiting** = needs an owner decision first.

## 1. Decision register

| # | Item | Status | Owner of next step | Depends on | Acceptance tests |
|---|---|---|---|---|---|
| O1 | Plan approved in principle | Approved | Claude | none | each phase reports changed files, tests, deployment needs, risks and evidence, then stops for review |
| O2 | Hosting: free git + cloud sessions, no recurring cost without a costed case | Approved, conditional on proof | Claude | M1, M2 | section 2 tests repeated against GitHub; the unattended-operation test in section 3; any paid option comes back as a costed proposal |
| O3 | Office built from master; B5 read-only until PR #19 is reviewed and merged | Approved | Claude | none; B5 integration blocked on the PR #19 merge (owner) | the office code imports nothing that can write `research/edge/*`; a test shows the B5 gate, registry and status are unchanged after office runs |
| O4 | D31 spent-authorisation fix as a separate reviewed PR | Approved to prepare; merge needs owner review | Claude prepares, owner reviews | PR #19's branch (the file lives there); coordination with the "Edge-discovery Phase A audit" thread, which owns that branch | registry bytes and `status.json` history unchanged; new test: every `spent: true` history entry is refused by `b5_authorisation`; all 442 research tests pass; the PR states that `edge_registry.py` no longer matches spent MANIFEST-3 |
| O5a | Standing research permission, class R0: maintenance, monitoring, data-quality investigation, documentation, research preparation | Approved; takes effect when the permission file and gate exist | Claude builds; owner signs the grant | M1, M3 | the gate refuses any experiment, gate change, permission change or order under R0; every refusal is recorded |
| O5b | Separate auditable standing authorisation for future experiments | Awaiting (proposal to be written) | Claude proposes, owner decides | O6, O7 remediation, PR #19 merge | proposal names class, protocol sha, trial budget counted into N before running, spent ledger, expiry |
| O6 | Check 4: independent verification procedure | Approved to propose; completion only by owner review | Claude proposes the procedure; owner (or a source the owner names) verifies | none | the procedure names the source and sample; evidence and limitations are recorded; nothing marks Check 4 complete automatically |
| O7 | No paid data; affected historical experiments stay blocked | Approved | owner (any future purchase) | survivorship and data-integrity remediation | the R1 gate refuses while the readiness statement says "not ready" |
| O8 | Tradeable demo environment | Awaiting (proposal in section 4) | owner chooses the option; owner acts in the app | none | after the change, read-only check shows tradeable quantity or cash as expected, and the ISA-mirror holdings are unchanged if they are meant to stay |
| O9 | Separate simulation, narrow demo tests and autonomous demo trading; no unrestricted demo trading | Approved in principle; the specific permission is awaiting (section 4) | owner grants the Demo Execution Test Permission | O8, M5 (trade gate built and tested on a fake broker) | only the listed test cases run; permission spent after use; no order outside its limits |
| O10 | Retire the 100% LQQ3 strategy and `research/LOOP.md` | Approved; to build | Claude | none (can run alongside M1) | audit trail kept (files archived, not deleted, with a DECISIONS entry); test: no code path or active scheduled task can write `trading/config/strategy.json`; the executor refuses to trade with the retired config; replacement behaviour (hold and report) tested |
| O11 | Pending Intel, Bloom Energy and Tempus AI sells | Separate decision, outside this work | owner | O8 (they are in pies) | not part of any office task |
| O12 | Critical alerts and daily digest | Approved | Claude | M1, M2 | each injected fault type (missed job, stalled queue, failed session, broker/API error, order failure, reconciliation mismatch, risk breach) produces an email within one heartbeat; digest delivered every day of the test |
| O13 | Live ISA out of scope | Approved (no action) | owner | an explicit readiness-review request and a defined mandate | the client stays hard-locked to the demo host |

## 2. Can git alone give a safe queue? Evidence

### 2.1 What was tested (local bare repository, 8 concurrent worker processes)

A scratch prototype (not in the repository) kept the queue as an append-only, hash-chained JSONL log on a git branch.
Every state change is one commit pushed without force. A rejected push means another worker changed state first, so the
worker refetches, rebuilds the state and decides again.

| Test | Result |
|---|---|
| T1 idempotent creation: 8 workers each tried to create the same 20 tasks at the same time | 20 create events, 20 unique keys, no duplicates |
| T2 atomic claiming: 8 workers drained 20 tasks at the same time | 20 claims and 20 completions, **0 tasks claimed twice**, chain valid, sequence contiguous, 6 seconds |
| T3 interrupted job: worker A claimed and was "killed" | B could not claim during A's lease; B reclaimed after the lease expired |
| T4 late result from a lost lease | A's late completion was refused (lease lost), so a stale worker cannot record over a newer attempt |
| T5 bounded retry and quarantine | after 3 attempts the task was quarantined, not retried |
| T6 crash between commit and push | nothing became visible to other workers (the change is all or nothing) |

### 2.2 What this shows and what it does not

- Git's non-fast-forward rejection works as an atomic compare-and-swap on the whole log, so claim, complete and
  create can each be one atomic transaction. GitHub applies the same rejection rule (standard git behaviour). That is
  inferred, **not yet tested against GitHub**; it is the first test in M1.
- Not provided by git, and handled in code instead:
  1. **External side effects (orders, emails) are not exactly-once.** Rule: write an `intent` event with the decision's
     idempotency key and push it before any order. On recovery, an intent without a `placed` event is resolved by
     looking up the broker's pending orders and history. An order is never retried automatically. This extends the
     executor's existing ambiguous-order handling.
  2. **Leases depend on clocks.** Leases will be minutes long, and each claim carries a fencing number (the claim's
     sequence). A completion must quote it, so a resumed stale worker is refused (T4).
  3. **Nothing pushes events to an idle worker.** A worker can only be started by the heartbeat scheduled task or by
     another session firing a scheduled task. My session has the tool to fire one. Whether sessions started by a
     scheduled task have it is **unverified** and is tested in M2.
  4. **Throughput.** About one second per push. That is ample for tens to hundreds of research tasks a day, and too
     slow for intraday trading loops, which this design does not need.
  5. **Log growth.** Periodic snapshots: a snapshot event with the state hash, and older lines kept in history.
- **Minimum extra infrastructure, only if the GitHub test fails** (contention, rate limits or push latency): a
  transactional queue in Cloudflare D1. The account exists and its free tier is likely enough, but the plan tier is
  unknown and must be checked. The git log stays the audit record. The fallback is a small VPS at about £4-6/month. Neither is
  proposed now.

### 2.3 Does the platform support reliable unattended execution? Evidence so far

| Scheduled task | Session type | Expected runs | Evidence of a run |
|---|---|---|---|
| Weekday portfolio brief (new, from 15 Oct 08:16) | fresh session per run | 16 Oct, 19 Oct | 2 of 2: one thread each day, fired 06:46-06:47 (1-2 min after schedule) |
| Equity daily pipeline | persistent session | 14, 15, 16 Oct | 3 of 3: one commit each night, about 10-12 min after firing |
| Weekly stock discovery | persistent session | 17 Oct | 1 of 1 |
| Monthly signal log | persistent session | none yet (first run 3 Nov) | none yet |
| Hourly trader + monitor (disabled) | one persistent session shared by 3 tasks | 6 on 14 Oct | 3 of 6 left no evidence (`docs/AUDIT_AND_PLAN.md` §4; likely cause: a busy shared session drops new runs) |

**Conclusion.** Scheduled runs fire on time when each run gets its own fresh session: 6 of 6 expected runs across three
tasks. A persistent session shared by several tasks lost half its runs. The sample is tiny (five days), so this is not
yet evidence of reliability. The design therefore uses only fresh-session workers and a missed-heartbeat detector.
It counts as reliable only after passing section 3. Unknowns to measure in M2: maximum session length, concurrent
session limits, the owner's plan usage limits, whether fresh sessions see `/mnt/project-files`, and whether they can
fire a scheduled task.

## 3. Proposed unattended-operation test (the "always-on" bar)

The system is called always-on only after passing all of these over **14 consecutive days**, in research-only mode:

1. A worker run every 60 minutes from the heartbeat. At least 95% of expected heartbeats produce a recorded run within
   15 minutes of schedule, and there is no gap longer than 2 heartbeats.
2. Event chaining: at least 80% of follow-on tasks start within 10 minutes of their parent completing, without waiting
   for the heartbeat (if fire-next works in fresh sessions; otherwise the plan is revised).
3. Zero duplicate completions, zero chain-validation failures and zero unrecorded tasks (the auditor reconciles the log).
4. Fault injection, at least once each: a killed worker mid-task, a duplicate worker, a push conflict, a poisoned task, a
   budget breach, a broker API error (read-only calls), and a stale-data gate failure. Each must be recovered or
   quarantined within 2 leases and alerted within 1 heartbeat.
5. A daily digest on 14 of 14 days. Every critical alert is delivered by email.
6. Measured usage within the budget set at the start (reported daily).

## 4. Demo execution: proposal for O8 and O9

Three separate levels. None implies the next one.

| Level | What | Real orders? | Permission |
|---|---|---|---|
| L1 Simulation | fake broker that replays real API shapes; every gate and failure case | no | none |
| L2 Demo dry run | real demo reads, full decision and gate path, orders built but not sent | no | none (read-only) |
| L3 Narrow demo execution tests | a fixed list of test orders on the demo account | yes, demo only | **Demo Execution Test Permission** (below) |
| L4 Autonomous demo portfolio trading | the system trades the demo under a mandate | yes | Demo Execution Mandate, later, after L3 and evidence |

**Tests that need real demo orders (L3):**
1. a small market buy accepted and filled, then reconciled;
2. the matching sell, filled and reconciled;
3. the duplicate-order guard against the real pending-order and history endpoints (a second identical decision must be
   refused);
4. a broker rejection handled correctly (an order below the instrument's minimum quantity);
5. order lookup after a deliberately discarded response (ambiguous outcome) resolves to the real order.

Everything else (stale prices, liquidity, concentration, cash, outages, loss limits, timeouts, market-closed refusal)
is tested in L1 and L2 without orders.

**Safest way to make the demo tradeable (owner action in the app, choose one):**
- **(a) Recommended:** add demo cash, if the app allows it, and leave the pies untouched. The ISA mirror stays intact
  and the tests use only the new cash.
- (b) Take one pie holding out of its pie. This changes the ISA mirror and is not recommended.
- (c) Reset the demo. This destroys the mirror, as the 13 Oct reset did.

**Minimum permission for L3:** demo host only; at most 6 orders; one named instrument (VWRP, liquid, GBP); at most £10
notional per order and £20 in total; only the 5 listed test cases; within one named date window and LSE market hours;
must not sell or alter any pie holding. It is spent automatically after the tests or at the window's end, and it does
not authorise anything else.

## 5. Check 4 procedure (proposal for O6)

- **What is verified:** the H1 inputs (operating cash flow, capex, total assets) and the S2a inputs (gross profit,
  revenue, cost of revenue, total assets) used by the B5 runs.
- **Independent source:** each sampled company's original filed financial statements on SEC EDGAR (the 10-K and 10-Q
  documents themselves, read from the filing index). The current pipeline uses the SEC's companyfacts aggregation, so
  the source is the same regulator but a different, primary artefact. A truly separate vendor would need paid data
  (O7), and that limitation is stated.
- **Sample:** a stratified random sample fixed by a published seed before looking: 40 company-quarters per trial,
  across years 2015-2022, size buckets and the decile extremes the strategies actually held.
- **Who:** an agent extracts the values and the comparison, and the owner reviews the evidence pack. Check 4 is
  recorded complete only by the owner, and only if the mismatch rate and its effect on scores are within a tolerance
  stated in advance (proposed: under 2% of values differ by more than 1%, and no mismatch changes a holding decision).

## 6. Next implementation milestone

**M1: the core queue and record store, in code, with tests, on a new branch from master. Nothing is deployed.**
- Files: `office/events.py` (hash chain, append, validate, snapshot), `office/store.py` (git backend behind a small
  interface), `office/queue.py` (create with idempotency key, claim with lease and fencing number, complete, fail with
  backoff, quarantine, growth and cycle limits, budgets), `office/tests/` (the six tests above plus fencing, cycles,
  growth limits and budget exhaustion).
- One concurrency run against GitHub on a throwaway branch (`office-queue-test`, deleted afterwards). This needs your
  approval because it pushes to the repository.
- Done when: all tests pass locally and against GitHub with 8 concurrent workers, and the report shows the numbers.

**Alongside M1** (each a separate PR for your review): the O10 retirement, the O4 D31 PR (coordinated with the
"Edge-discovery Phase A audit" thread), and the Check 4 procedure document.

**Then M2:** one heartbeat scheduled task, created only with your approval, running read-only maintenance tasks
(health, read-only demo reconciliation, alerts and digest), and the 14-day test in section 3.

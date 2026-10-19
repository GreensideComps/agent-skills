# Autonomous investment manager: architecture assessment and phased plan

Written 2026-10-19 (14:15-15:00 UTC) for the owner's review. This is the first deliverable of the owner's two requests of
2026-10-19 (14:12Z "Always-On Autonomous Investment Research Office" and 14:15Z "Always-On Autonomous AI Investment
Manager"), combined into one plan. The research office is one part of the investment manager.

**Nothing was built, run or changed.** No research run, no gate, registry or status change, no holdout access, no
trade, no account, portfolio, permission or investment-setting change, and no scheduled task created or enabled. The
only external calls were read-only: Trading 212 demo account summary, positions and pending orders (through the
repository's read-only client), the list of scheduled tasks and environments, the open PRs, and the Cloudflare
Workers list. Tests were run on a read-only checkout of PR #19's head.

Labels used: **Verified** = observed directly in this inspection (file, command output, API response). **Inferred**
= reasoned from verified facts, not observed. **Unknown** = not checked or not checkable from here.

---

## 0. Summary and the decisions only the owner can make

### 0.1 Summary

1. **What exists is a strong, careful research core and a demo-only trading bot, but no always-on system.** There is
   no persistent server, task queue, worker service, event bus or live dashboard anywhere in the repository or the
   connected infrastructure. Everything that runs today is a Claude scheduled task that starts a cloud session on a
   cron (four enabled). Progress between those runs depends on a person or a Claude thread.
2. **The research governance is good and should be reused, not rebuilt.** The hash-chained trial registry
   (`research/edge/trials.jsonl`, 252 lines, valid, N = 102), the one-run lock, manifest hashing, spent-authorisation
   checks, the exploration/holdout split and the deflated Sharpe all work (research tests: 442 passed). But they were
   built for one experiment (B5) with constants in code, and they live on PR #19, which is not merged.
3. **The D31 inconsistency is real but not currently exploitable.** D31 is recorded as spent in `status.json` and
   is missing from `edge_registry.B5_SPENT_AUTHORISATIONS`. A re-authorisation of D31 is still refused, because run 2's
   results exist and the lock is archived (test `test_re_authorising_spent_d31_cannot_start_a_second_run`). The
   protection rests on B5-specific facts, so a general standing-authorisation model must keep spent authorisations in
   an append-only ledger rather than a code constant (section 7.4).
4. **The brokerage integration can only reach the Trading 212 demo host, and today it could not execute any trade
   even if asked.** The demo account holds 22 positions, all inside pies, with **0 shares available for trading via the
   API, £0 cash and no pending orders** (verified 14:40Z: value £1,236.34, cost £1,298.05, unrealised −£61.71). The
   client does not implement pie endpoints. `strategy.json` is stale (`discretionary_intraday_v1`, target 100% LQQ3)
   and every trading scheduled task is disabled.
5. **No historical performance experiment should run until data readiness is demonstrated.** Survivorship bias is
   material and unbounded on free data, TTM Check 4 is open, and the E2 label is withheld. Both B5 V3 primary trials
   failed. No strategy in this repository has evidence above E1, so the honest default decision for the portfolio is
   VWRP or no change.
6. **Recommended build:** a storage-agnostic task queue and record store in Python with a git-backed append-only event
   log, drained by Claude cloud sessions that are started by events (a finished task fires the next worker run) with a
   scheduled heartbeat as fallback only. This needs no new paid service. It is "always on" in the sense that it runs
   without the owner's computer and without prompts, but each worker run is a short session, and its latency is
   bounded by the heartbeat. That must be proven in Phase G before anyone calls it always-on. A small paid server is
   the upgrade path if the free route proves unreliable (costs in section 2.6).
7. **Three permissions, kept separate and never inferred from each other:** a Research Standing Authorisation, a Demo
   Execution Mandate and a Live (ISA) Execution Mandate. The plan proposes the first two for later phases. It does not
   propose a live mandate; the ISA stays out of scope until the owner's readiness review.

### 0.2 Decisions only the owner can make

Each is needed before the phase named, not now. Recommended options are marked.

| # | Decision | Options | Needed before |
|---|---|---|---|
| O1 | Approve this plan, or change it | approve / amend | Phase B |
| O2 | Hosting | **(a) no new cost: git-backed queue + Claude cloud sessions (recommended to start)**; (b) Cloudflare Workers + D1 as queue/dashboard API (account exists, plan tier unknown, likely free tier); (c) small VPS ~£4-6/month plus Anthropic API usage | Phase C |
| O3 | Where office code lives while PR #19 is open | **(a) new branch from master, office reads the B5 registry read-only and B5 integration waits for PR #19 (recommended)**; (b) build on top of PR #19's branch | Phase C |
| O4 | D31 maintenance fix: add D31 to `B5_SPENT_AUTHORISATIONS` plus a consistency test, accepting that `edge_registry.py` will no longer match MANIFEST-3 (MANIFEST-3 is spent anyway) | **approve as a separate reviewed PR (recommended)** / leave as is | Phase B |
| O5 | Research Standing Authorisation: which classes of work may run unattended, budgets (tasks/day, compute, API calls), and whether any historical performance experiment class is ever permitted unattended | **non-experiment work only at first (recommended)**; experiments only after data readiness, per class, with a trial budget | Phase D |
| O6 | Check 4: who performs and records the independent-source verification, and from which source | owner review of an agent-prepared comparison / leave open | Phase B remediation |
| O7 | Paid survivorship-free data (Norgate ~$630/yr or EODHD ~$20/mo, prices recorded 2026-10-14, not re-checked) | **stay on free data and keep historical experiments blocked (recommended for now)** / buy | before any new historical experiment |
| O8 | Demo account structure for execution testing: holdings are all in pies with £0 cash, so the bot cannot trade | move holdings out of pies in the app / add demo cash / reset the demo / leave untradeable | Phase F (execution tests) |
| O9 | Demo Execution Mandate: universe, position and exposure limits, loss limits, order sizes, frequency | define later; **no mandate until Phase F tests pass** | Phase G |
| O10 | Retire `strategy.json` `discretionary_intraday_v1` and the legacy research loop (`research/LOOP.md`, which allows the research loop to edit `trading/config/strategy.json`) | **retire both (recommended)** | Phase D |
| O11 | The three pending demo sells (Intel, Bloom Energy, Tempus AI) from the 14 Oct validation | still awaiting the owner; cannot run via API while in pies | any time |
| O12 | Alerts: channel and thresholds (email via Resend is configured; push notifications unverified) | email for critical + daily digest (recommended) | Phase C |
| O13 | Live ISA connection | **out of scope until a readiness review the owner asks for** | not in this plan |

---

## 1. Phase A: repository and infrastructure assessment (verified)

### 1.1 Repository and branches

- Repo `GreensideComps/agent-skills`, default branch `master` at `90e9b3b` (equity daily pipeline commit, 16 Oct).
  No `.github/workflows` and no CI (verified: none in tree; `trading/deploy/daily-report.github-actions.yml.example` is
  an inactive example). Visibility: a GitHub repository search returned nothing, so it is probably private (inferred).
- PR #18 (Phase A governance) is merged into master (`9527e6e`).
- **PR #19** (`claude/edge-discovery-phase-a-j78pyp`, head `1eb0e96`, open, not merged) holds all Phase B and B5 work:
  87 files, +23,260 lines against master. Owned by the thread "Edge-discovery Phase A audit". Must not be merged
  without the owner's explicit authorisation.
- Branch `claude/trading212-agent-skills-r71zy3` (last commit 14 Oct, `5ba56fc`) is the trading bot's branch that the
  disabled trading tasks used; it differs from master's `trading/` only in journal files.
- Main code areas (verified):
  - `research/`: 46 Python modules. B5 and edge governance: `edge_registry.py`, `edge_b5_run.py`, `edge_b5.py`,
    `edge_b5_stats.py`, `edge_b5_inputs.py`, `edge_backtest.py`, `edge_rules.py`, `edge_split.py`,
    `edge_integrity.py`, `edge_exec_prices.py`, `edge_exec_audit.py`, `edge_ttm_checks.py`, input and quality audits.
    Stage 1/2: `xsection.py`, `stage2.py`, `stage2_diagnostics.py`, `signal_log.py`. Older ETF research:
    `run_regimes.py`, `run_factors.py`, `run_allocation.py`, `run_risk.py`, `h01`-`h09`.
  - `equity/equity/`: SEC ingest, universe, prices, screener, valuation, alerts, paper portfolio, reliability, job
    ledger (`jobs.py`), portfolio monitor. Daily pipeline `equity/daily_run.sh`.
  - `trading/t212bot/`: demo-only client, read-only facade, executor, planner, decide, monitor, shadow portfolios,
    reporting, Resend emailer, verify-report.
  - `docs/edge/`: pre-registrations, addenda, manifests, DECISIONS.md (D1-D32), incidents.
- Tests (verified on PR #19 head): research **442 passed** (241 s), equity **118 passed**, trading **139 passed**.

### 1.2 Research registry and B5 controls (verified in code)

- `edge_registry.append` hash-chains every event to the previous line and validates before replacing the file;
  `validate` checks the chain; kinds `trial`, `diagnostic`, `inherited`, `exposure`; `n_trials` counts only
  `counts_for_dsr` entries (N = 102). A confirmation `batch` event is refused while Check 4 is open, and D2 allows one
  confirmation batch ever (`MAX_BATCHES = 1`).
- `deflated_sharpe(..., stat=...)` pools only results of the same statistic.
- `edge_split` separates exploration (to Dec 2022) from the 2023-01..2026-09 holdout, which is recorded as **partly
  seen**.
- B5 run gate (`edge_registry.b5_authorisation`, `b5_manifest_ok`, `b5_run_open`; `edge_b5_run.preflight`): needs
  `status.json` `b5_trial_run.authorised = true` with an owner `cmsg_` id not in `B5_SPENT_AUTHORISATIONS`, naming the
  registered `B5_MANIFEST_ID` by id and sha256; every input and code file must match the manifest; no result may exist
  for any B5 V3 or retired id; then the one-run lock is created with `O_EXCL` and never removed by code. `load_inputs`,
  `run_one` and `finish` re-check `b5_run_open(verify_files=True)`; results are staged and recorded in one atomic
  rename.
- Current state (verified, `research/edge/status.json`): `b5_trial_run.authorised = false`; history holds run 1 (D26,
  spent, failed, lock archived `docs/edge/incidents/B5_RUN_1_LOCK.json`) and run 2 (D31, spent, completed, lock
  archived `B5_RUN_2_LOCK.json`, sha256 2041f109...). `research/edge/b5_run.lock` does not exist.
- Limitation for reuse: the controls are B5-specific constants (`B5_RUN_IDS`, `B5_MANIFEST_ID`,
  `B5_SPENT_AUTHORISATIONS`) and `edge_registry.py` itself is a manifest-listed file, so any change to it breaks
  MANIFEST-3's hash. A general system needs the same guarantees driven by data, not by editing code constants.

### 1.3 D32 Run 2 closeout review

- D32 (`docs/edge/DECISIONS.md` line 149, commit `1eb0e96`) matches the repository: 12 results on registry lines
  241-252, registry valid, N = 102, both primaries (B5-H1-FCFPS-ACCEL-V3, B5-S2A-GP-12M-V3) failed P1-P3, report
  `equity/reports/research/edge/b5_trials.md` with both "Verdict: fail" and the standing disclosures (checked by
  `test_run_2s_results_and_report_are_recorded_unchanged`).
- **D31 inconsistency (verified).** `B5_SPENT_AUTHORISATIONS = frozenset({D26 id})` only (`edge_registry.py:158`).
  What stops D31 being reused today:
  1. `authorised` is false, so `b5_authorisation` refuses;
  2. if someone wrote D31 back into status, `b5_authorisation` would **pass** (D31 is not in the spent set), but
     `preflight` refuses with "already run" because run 2's results exist, and takes no lock;
  3. `b5_run_open` refuses because no lock exists.
  So reuse is blocked by results-existence and the lock, not by the spent list. The gap matters for any future
  experiment with new trial ids under a new manifest: nothing in code would stop an old spent message id being
  reused there except the manifest id constant. Fix in section 7.4 (owner decision O4).

### 1.4 Standing limitations (unchanged, carried into every output)

- Survivorship bias is material and unbounded: free Yahoo prices omit delisted names; no delisted company over $1bn
  of assets is priced; 318 of 323 large companies that stopped filing in 2023-26 are unpriced
  (`docs/edge/SURVIVORSHIP_FEASIBILITY.md`). The limitation is accepted for exploration only (D13).
- TTM Check 4 (independent-source verification of H1 and S2a inputs) is open; it blocks any E2 label and any
  confirmation pre-registration.
- E2 label withheld. `backtester_validated` is true for exploratory research only (D12).
- Other recorded limitations: PIT quality-rule errors, the P8 ex-post data-error list, 2026 SIC codes, input
  validation false positives and misses, the identity rule, the P7 window disclosure (94/93 vs 95/94).

### 1.5 Brokerage integration: what it can reach and execute (verified in code and by read-only calls)

- `trading/t212bot/config.py`: `DEMO_BASE_URL = "https://demo.trading212.com"`; the live URL appears nowhere;
  `load_credentials` raises unless `T212_ENV == "demo"`.
- `client.py`: refuses any base URL other than demo and any path outside `/api/v0/` on demo. Implements account
  summary, positions, pending orders, history, instruments, exchanges and market-order placement and cancel; no pie
  endpoints.
- `readonly.py`: a read-only facade exposing only read methods; the Trading 212 public API has no withdrawal or
  transfer endpoint (as recorded in the module).
- `executor.py` safety path before any order: KILL file, demo lock, pending orders, market hours with open/close
  buffers, fresh Yahoo quotes cross-checked against T212 price (max 5% divergence), currency match, cash cap with
  learned reserve, max orders per run, ambiguous-order handling (looks the order up and stops), reconciliation.
  `decide.py` adds max decisions per day and a daily loss stop.
- Session environment (verified names only, values not read): `T212_ENV=demo`, `T212_API_KEY`, `T212_API_SECRET`,
  `RESEND_API_KEY`, `REPORT_EMAIL_FROM/TO/PROVIDER`, `GH_TOKEN`. The keys work against demo (calls succeeded).
- **What Claude can execute today:** nothing useful. All 22 demo positions are in pies with
  `quantityAvailableForTrading = 0`, cash available to trade is £0, so the executor has no shares to sell and no cash
  to buy with. The live ISA cannot be reached by this code at all; reaching it would need a code change, live keys and
  an owner decision.
- Not present: per-order idempotency keys (Trading 212's market-order API has no client order id in this client;
  duplicates are guarded by pending-order checks and post-hoc lookup), a mandate file separate from strategy config,
  pre-trade checks for concentration, liquidity (ADV), max exposure or stale account state as independent code.

### 1.6 Demo portfolio state (verified, 2026-10-19 ~14:40Z, read-only)

Value £1,236.34, cost £1,298.05, unrealised −£61.71, realised £0, cash £0 (available, reserved and in pies all 0),
22 positions, 0 pending orders. Largest by value: NVDA, GOOGL, AVGO, MSFT, AMZN, ASML, TSM, FB (META), SPCX, PLTR; also
AMD, VRT, BE, PANW, VST, INTC, CRWD, TEM, AAPL, TSLA, UBER, IBTA (LSE). This is a copy of the owner's real ISA pies
(project memory). `strategy.json` targets 100% LQQ3, so it never matches holdings; nothing acts on it.

### 1.7 Scheduled tasks and runtime (verified via the scheduled-task list)

| Task | State | Notes |
|---|---|---|
| Weekday portfolio brief `trig_012o3Bc5Ja2PiD7rvx2Fzrmd` | enabled, 06:45 UTC weekdays, fresh session | last run 19 Oct succeeded |
| Research: monthly signal log `trig_014YqFuWkepFLFUzGchCbRWk` | enabled, 3rd 06:46 London | keep unchanged; next 3 Nov |
| Equity: daily research pipeline `trig_01PYai2PEsqMTtFSMDCD99BY` | enabled, weekdays 22:27 London | last fired 16 Oct; **no fire and no commit recorded for Fri 17 Oct** (cause not checked); commits show rc=1 (warn) on 14-16 Oct |
| Weekly stock discovery `trig_015scjHUCMP5NZDTQVcPxJrT` | enabled, Sat 07:50 UTC | |
| Old brief, both hourly traders, trading ops, ETF research loop, an unrelated prospecting task | disabled | stay disabled |

- The signal log and the daily pipeline fire into the **same persistent session** (`session_018SQ...`), so a long run
  of one can delay the other (inferred risk).
- One cloud environment (`Greenside Competitions`, anthropic_cloud). Containers are ephemeral: 4 CPUs, 15 GB RAM in
  this session; nothing survives except git pushes and the project's shared folder.
- Whether fresh-session scheduled runs get `/mnt/project-files`: Unknown; must be tested in Phase C.

### 1.8 Persistent infrastructure that actually exists (verified)

- GitHub repository (durable, versioned; push rejection gives an optimistic compare-and-swap).
- Project shared folder `/mnt/project-files` (durable, network mount, last write wins, no locking).
- Claude scheduled tasks and cloud sessions; the tooling can fire a scheduled task on demand (event chaining).
- A Cloudflare account with one unrelated Worker (`greenside-entry-allocator-qa`); plan tier Unknown.
- Resend email configured (`trading/STATUS.md`: `email-check` OK; From `onboarding@resend.dev`).
- Artifacts with a shared database capability (can serve a live dashboard with no hosting).
- Not present: any always-running server, database service, message queue, or Anthropic API key for a self-hosted
  agent loop.

### 1.9 Dashboard, reporting and notifications

- Existing outputs are files: `equity/reports/*`, `research` reports, `trading/PERFORMANCE.md`, HTML daily report
  samples, the weekday brief thread. No live dashboard. Push notifications are unverified (`trading/STATUS.md`).

### 1.10 Gap summary

| Need | Exists | Gap |
|---|---|---|
| Persistent queue, leases, retries, DLQ | no (equity has a per-job ledger only) | build |
| Event triggers | cron only | build: completion events + fire-next |
| Shared versioned records | trial registry (B5-centred), DECISIONS.md, equity ledgers | generalise and extend |
| Research standing authorisation | B5 per-run authorisation only | build, with spent ledger |
| Relationship/regime analysis | older ETF scripts | build on edge_backtest |
| Portfolio construction under mandate | planner + paper portfolio | extend with risk/limits |
| Independent pre-trade gate | partial (executor checks) | build as separate module |
| Execution mandate separate from strategy | no | build |
| Reconciliation | executor.reconcile, verify-report | extend to every run |
| Attribution vs VWRP | shadow portfolios, PERFORMANCE.md | extend per decision |
| Live dashboard, alerts, digest | files, email | build |
| Tradeable demo account | no (pies, £0 cash) | owner decision O8 |

---

## 2. Target architecture

### 2.1 Principles

1. One durable source of truth: an append-only, hash-chained event log; current state is derived from it. Nothing is
   overwritten; corrections are new events.
2. Deterministic Python owns every gate, count, lock and limit. Model judgement proposes; code disposes. No agent can
   change a gate, threshold, mandate or registry rule; those change only by a reviewed PR plus an owner decision.
3. Research permissions and execution permissions are separate files, separate code paths and separate owner
   messages. Neither is read by the other's gate.
4. The research office has no write path into trading configuration. (The legacy `research/LOOP.md` does; it is
   retired in Phase D.)
5. Every output carries source, data version (file sha256), code version (commit), task id and experiment id.
6. Default decision is "hold VWRP / no change" unless evidence at the mandate's required tier says otherwise.

### 2.2 Components

```
                 events (task done, data update, failure, new evidence, heartbeat)
                                     |
  +-------------------------+    +---v-----------------+     +---------------------------+
  | Record store (git)      |<-->| Queue + Director    |---->| Worker run (cloud session)|
  | office/events.jsonl     |    | office/queue.py     |     | claims 1 task by lease,   |
  | (hash-chained, append)  |    | office/director.py  |     | runs the role's procedure,|
  | derived: state.sqlite   |    | priorities, deps,   |     | writes outputs + events,  |
  | research/edge/trials... |    | budgets, loop guard |     | fires next run if work    |
  +-----------+-------------+    +---------------------+     +-------------+-------------+
              |                                                            |
  +-----------v-------------+   +--------------------------+   +-----------v------------+
  | Dashboard (Artifact+db) |   | Governance auditor (code)|   | Gates (code only)      |
  | + alerts (Resend email) |   | validates every event    |   | research authorisation |
  | + daily digest          |   | chain, counts, mandates  |   | pre-trade gate (demo)  |
  +-------------------------+   +--------------------------+   +------------------------+
```

- **Record store.** `office/events.jsonl` on a dedicated branch `office-state` (keeps master history clean and avoids
  conflicts with the equity pipeline's pushes to master). Each event: `{seq, prev, ts, actor, task_id, kind, payload,
  code_commit, data_shas}`. A derived SQLite file is rebuilt from the log on each worker start (cheap; SQLite 3.45 is
  available) and is never the source of truth. The existing trial registry stays where it is and is referenced by
  id and line hash.
- **Transactions.** A state change is one commit appending events, pushed to `office-state`. A rejected push means
  another worker changed state first: refetch, rebuild, re-check the claim, retry (bounded). This gives
  compare-and-swap semantics without a database service.
- **Queue and Director** (`office/queue.py`, `office/director.py`): deterministic code. Task fields: id, type, role,
  inputs, `idempotency_key` (hash of type + normalised inputs), dependencies, priority, budget, deadline, attempt,
  status. The Director turns events into tasks by fixed rules and, when the queue is empty, asks for a judgement task
  ("choose the next useful permitted work") whose output is a list of proposed tasks that code then validates.
- **Workers.** A worker is one cloud session started by a scheduled task. It rebuilds state, claims the highest
  priority eligible task with a lease, runs the role's procedure, writes outputs and completion events, releases
  dependents, then either claims another task (within its run budget) or, if eligible work remains, fires the next
  worker run and ends. If no work is eligible it ends at once (efficient wait). The cron heartbeat only exists to
  recover from stalls and to run maintenance.
- **Gates** are plain Python called by every path that touches data or the broker; they read only real files at
  fixed paths (the pattern `b5_run_open` already uses).

### 2.3 The eleven research roles, mapped to existing code

These are logical roles run by the same worker, not separate always-running instances (cost). The Adversarial
Reviewer and Governance Auditor run in a different worker run from the work they review, and the reviewer's task has
no write access to the result it reviews.

| Role | Reuses | New |
|---|---|---|
| Research Director | AGENDA ideas, programme doc H1-H11 | `office/director.py` rules, priority scoring, dependency graph |
| Discovery | `equity` screener, weekly discovery task, SEC ingest | hypothesis records with dedupe (normalised signature + embedding-free text match) |
| Academic and Evidence | none | citation records (URL, retrieval date, claim, counterargument) |
| Data Integrity | `edge_integrity`, `edge_exec_audit`, `edge_b5_input_audit`, `edge_ttm_checks`, `equity/reliability.py` | data-readiness scorecard per dataset and per experiment class |
| Quant Research | `edge_b5*`, `edge_backtest`, `edge_rules`, `edge_split`, pre-registration docs | spec template generator; never runs an experiment without the gate |
| Relationship and Regime | `run_regimes.py`, `run_factors.py`, `edge_backtest` | section 6 |
| Portfolio Construction | `run_allocation.py`, `trading/t212bot/planner.py`, `equity/paper.py` | candidate-portfolio evaluator vs VWRP under mandate limits |
| Adversarial Reviewer | B5 review rounds as a template | objection records; blocking objections stop promotion |
| Memory and Meta-Analysis | `n_trials`, `deflated_sharpe`, `stage2_diagnostics` | effective-trial counting for overlapping experiments; priority recommendations |
| Governance Auditor | `edge_registry.validate`, B5 gate, DECISIONS.md | auditor over the office log, authorisations and mandates |
| Monitoring and Reporting | `t212bot/monitor.py`, `emailer.py`, `verify-report`, weekday brief | dashboard, alerts, digest |

### 2.4 Investment lifecycle (owner's 10 steps) and what is automated when

| Step | Today | First automated in | Permission needed |
|---|---|---|---|
| 1 Discover | weekly discovery, screener | C/D | Research authorisation (non-experiment class) |
| 2 Validate data / PIT | audits exist per B5 | D | same |
| 3 Evaluate returns, risks, costs | B5 harness | D (existing results only) | historical experiments need a class authorisation (O5) |
| 4 Relationships, regimes | none | E | same as 3 for any new backtest |
| 5 Construct candidate portfolios | paper portfolio | E | research only: candidates are proposals, never orders |
| 6 Independent review | manual | D | none |
| 7 Apply mandate and limits | executor checks | F | Demo Execution Mandate (O9) |
| 8 Execute | demo bot, disabled | G (demo only, after O8, O9) | Demo Execution Mandate |
| 9 Verify and reconcile | executor.reconcile, verify-report | C (read-only reconciliation daily) | read-only, no mandate |
| 10 Monitor, attribute, learn | shadow portfolios, PERFORMANCE.md | C/E | read-only |

A candidate portfolio becomes an order only if (a) a mandate permits that strategy's evidence tier, (b) the
pre-trade gate passes, and (c) the decision record names the evidence. With every strategy at E0/E1 today, the
correct output of steps 5-7 is "no change / VWRP" and the system must be allowed to say so.

### 2.5 Execution path (demo only)

`decision record -> pre-trade gate (office/trade_gate.py, independent of strategy code) -> t212bot executor
(existing checks) -> order outcome -> reconciliation -> attribution`. The gate checks, each blocking:
account identity (demo host, expected account currency and id fingerprint), mandate valid and unspent for this
decision class, available cash, order size and max notional, liquidity (share of 20-day ADV), stale price (quote age,
T212 vs Yahoo divergence), duplicate order (idempotency key per decision + pending-order check + recent-history
lookup), concentration (per name, per sector), max exposure, daily and drawdown loss limits, recent rejected orders,
last reconciliation clean, broker reachable and not degraded, KILL file absent. A failed check blocks that trade,
records the reason, preserves the last known state, opens an investigation task and alerts when severe.

### 2.6 Hosting options and costs

| Option | What runs where | Cost | Fit |
|---|---|---|---|
| (a) Git-backed log + Claude cloud sessions (recommended start) | state on `office-state` branch; workers are cloud sessions started by a heartbeat task and by fire-next | no new bill; uses the owner's Claude plan usage (plan limits Unknown here, so budgets are enforced in code) | uses only verified infrastructure; latency = heartbeat; reliability must be proven (one missed fire seen on 17 Oct) |
| (b) Cloudflare Workers + D1 | queue/state in D1 with real transactions, cron and HTTP event endpoints, dashboard API; heavy Python still in cloud sessions | Workers/D1 free tier is likely enough (plan tier Unknown; check before use) | better transactions and webhooks; needs a credential to start sessions or a GitHub token, which is an owner decision |
| (c) Small VPS (e.g. a ~£4-6/month instance) | systemd worker, SQLite, Python research, Anthropic API for agent roles | server ~£50-70/year plus API usage, which depends on volume (budget-capped; for scale, tens of judgement tasks a day is plausibly tens of pounds a month; not measured) | truly always-running; new paid services and a new secret store |

Recommendation: start with (a), write the queue against a small storage interface so (b) or (c) is a swap, and
decide on (c) only after Phase G shows whether (a) meets the latency and reliability targets.

---

## 3. Queue and worker design

- **Claim with lease:** `claim` appends `lease{task, worker_run, expires = now + task.deadline}` in one pushed commit.
  Expired leases return the task to `ready`, with the attempt counter kept.
- **Idempotency:** `idempotency_key` is unique among non-failed tasks; creating a duplicate returns the existing task.
  Outputs are written to content-addressed paths, so a re-run of an identical task cannot overwrite a different result.
- **Retries:** bounded (default 3) with exponential backoff (5 min, 20 min, 80 min); then `quarantined` with the error,
  visible on the dashboard, plus an investigation task for the Data Integrity or Governance role.
- **Loop and growth limits:** max tasks created per task (default 5), max queue depth per role, max total tasks per
  day, a dependency graph checked for cycles at insert, a generation counter (a task created by a chain longer than N
  needs the Director's approval task), and hypothesis dedupe before a Discovery task can spawn evaluation tasks.
- **Budgets:** per task (wall time, CPU minutes, external API calls), per worker run, per day; every task records its
  measured usage; exceeding a budget fails the task, never extends it.
- **Concurrency:** configurable (default 1 worker run at a time to start; the CAS commit makes 2+ safe).
- **Waiting:** a worker with nothing eligible ends immediately; the next start comes from an event or the heartbeat.
- **Recovery:** on start, a worker validates the chain, rebuilds state, expires stale leases and re-queues tasks
  whose outputs are missing. All research progress lives in git, so restarts and outages lose at most one task's
  in-flight work, which is re-run idempotently.
- **Health metrics** recorded as events: queue age per priority, throughput, failures, retries, worker-run duration,
  usage against budget, time since last successful worker run.

## 4. Shared records (all append-only, versioned, cross-referenced by id)

| Record | Key fields |
|---|---|
| Idea / source | id, text, source URL or dataset, retrieved_at, dedupe signature |
| Hypothesis / question | id, idea ids, economic rationale, predicted sign, evidence ids, status |
| Evidence / citation | id, citation, claim, counterarguments, reliability note |
| Data dependency / limitation | dataset id, sha256, coverage, PIT status, known limitations (incl. survivorship, Check 4) |
| Trial / variant | registry id (existing `trials.jsonl`), every attempted variant including combinations and conditions |
| Result / failed result | registry result line hash, report sha, gates passed and failed |
| Objection | reviewer task id, target, severity, resolution |
| Relationship | strategy pair or set, metric, window, value, experiment id |
| Decision / rejection | decision, reason, evidence ids, decided by (code, owner) |
| Task / handoff / failure / recovery | queue events |
| Authorisation / mandate / audit | owner message id, scope, budget, spent events, auditor findings |
| Portfolio decision / order / fill / reconciliation / attribution | decision id, gate results, order id, fills, costs, reconciliation diffs, contribution vs VWRP |

Traceability rule: a finding is invalid (and the auditor flags it) unless it names source, data shas, code commit,
task id and experiment id.

## 5. Permissions model

### 5.1 Research Standing Authorisation (RSA)

File `office/authorisations/research.json` (new; the existing `research/edge/status.json` keeps governing B5 and is
not changed). Each grant: owner message id, granted classes, budgets, expiry, and for experiment classes the exact
protocol document sha256, trial budget and data-readiness preconditions.

- **Class R0 (autonomous by default once O5 is granted):** discovery, source review, evidence collection, data-quality
  audits, synthetic tests, analysis of already-recorded results, relationship analysis on recorded results,
  preparing research specifications.
- **Class R1 (historical performance experiments):** only with an explicit grant naming the experiment class,
  protocol sha, trial budget (counted into N before running), and with every data and preflight gate passing. Each
  run spends budget by an append-only `spent` event; a grant whose budget is used is spent and cannot be reused.
- **Never:** holdout access without a separate explicit owner permission naming it; changing evaluation rules after a
  spec is registered; suppressing or omitting failed trials; any write to trading configuration or mandates.
- A blocked experiment records `blocked{reason}` and the Director picks permitted work (often fixing the blocker).

### 5.2 Demo Execution Mandate (DEM)

File `trading/config/mandate_demo.json` (new, separate from `strategy.json`). Owner message id, demo account
fingerprint, permitted strategies with minimum evidence tier, universe, per-name, sector and total exposure limits,
order size limits, max orders per day, loss limits, allowed hours, expiry. Read only by `office/trade_gate.py`. The
RSA cannot grant it and the trade gate never reads the RSA.

### 5.3 Live (ISA) Execution Mandate

Not proposed. The client is hard-locked to demo; lifting that is a code change requiring the owner's readiness review
(track record, missed runs, ISA constraints: no CFDs or shorting, the £20k subscription limit, ISA-eligible
instruments) and new credentials.

## 6. Relationship and Regime Agent, and combination accounting

- Analyses: monthly return and holdings correlations (Jaccard overlap of holdings), factor exposures (FF5 + momentum
  regressions; files already in `research/edge/factors`), sector, size, beta and concentration overlap,
  complementary/conflicting signals (rank correlation of scores), conditional interactions, regime behaviour using
  regime labels computed only from data available at each decision date (e.g. trailing 12-month market return sign,
  trailing volatility tercile, term-spread sign if a source is reachable; FRED was unreachable from the container),
  drawdown contribution, and incremental return over VWRP and the equal-weight universe.
- Accounting: every combination, weighting and condition explored is registered as a variant before its result is
  computed; variants on the same data count towards an effective N (Meta-Analysis role estimates effective N from
  the correlation of variant returns, and the larger of nominal and effective N is used conservatively in DSR).
  Results from analysis of recorded results are tagged exploratory; validation needs a separately registered, unseen
  period, and the 2023-26 holdout is partly seen and allows one confirmation batch ever (D2).
- A weak standalone strategy studied for diversification is labelled "diversification candidate, no standalone
  alpha evidence".
- First inputs (no new experiments): the 12 recorded B5 run 2 results and the Stage 2 results.

## 7. Data and governance remediation plan (before any new historical experiment)

1. **Universe completeness and survivorship:** quantify, per month 2015-2022, the large caps that later stopped
   filing and have no price; estimate their weight in the universe; produce a bias envelope under stated exit
   assumptions (acquisition premium, −30%, −100%). This bounds nothing proven but makes the size visible. Paid data
   is O7.
2. **Check 4:** prepare a comparison of H1 and S2a inputs against a second free source (for example, the filings'
   own XBRL instance documents vs the companyfacts aggregation, on a stratified sample) and hand it to the owner to
   review and record (O6). The agent never marks Check 4 complete.
3. **Filing timestamps, restatements, share counts, corporate actions, delisting returns:** extend `edge_ttm_checks`
   and `edge_b5_share_pit_audit` into a dataset readiness scorecard; restatement check compares first-reported vs
   latest values for the same period.
4. **D31 consistency (O4):** separate PR, maintenance only: add the D31 id to `B5_SPENT_AUTHORISATIONS`, add a test
   that every `status.json` history entry with `spent: true` is in the code set, and record in DECISIONS that
   `edge_registry.py` no longer matches MANIFEST-3 (spent, never to be used again). The general fix is the RSA's
   append-only spent ledger (5.1). No registry edit, no weakening.
5. **Readiness statement:** a table of which activity classes can proceed on current data (R0 yes; R1 no until 1-3
   are done and the owner decides).

## 8. Dashboard, alerts and digest

- Live dashboard as an Artifact page with a shared database, updated by each worker run: assignments and progress,
  queued/blocked/failed/quarantined/completed tasks, research pipeline and trial history (N, results, verdicts),
  relationships and candidate combinations, data readiness and governance status, worker health, usage and queue age,
  findings and rejected hypotheses with reasons, a searchable audit trail mirrored from `office/events.jsonl`.
- Alerts by email (Resend, configured): gate or chain validation failure, quarantined task, worker silent longer than
  2 heartbeats, budget breach, reconciliation difference, any order event. A concise daily digest is secondary.

---

## 9. Phases B to G

Each phase ends with a report to the owner (changed files, tests, deployment requirements, risks, evidence of
success) and stops for review before the next phase.

### Phase B: specification, permissions model, remediation plan (docs + one maintenance PR)

- Files: `docs/office/ARCHITECTURE.md`, `docs/office/PERMISSIONS.md`, `docs/office/RECORDS.md`,
  `docs/office/REMEDIATION.md`; separate PR for O4 touching `research/edge_registry.py` and one test.
- Tests: the O4 PR's consistency test plus the existing 442.
- Deployment: none. Risks: the O4 PR touches a manifest-listed file (stated). Evidence: owner approves specs.

### Phase C: queue, worker lifecycle, recovery, observability, records

- Files: `office/events.py` (chain, append, validate), `office/store.py` (storage interface, git backend, SQLite
  rebuild), `office/queue.py`, `office/director.py` (rules only), `office/worker.py`, `office/budget.py`,
  `office/health.py`, `office/tests/*`; heartbeat scheduled task prompt in `office/WORKER.md`.
- Tests: chain tampering, lease expiry, duplicate claim under concurrent CAS, idempotency, retries and quarantine,
  cycle rejection, growth limits, budget exhaustion, rebuild after crash.
- Deployment: `office-state` branch; one heartbeat scheduled task (created only on the owner's approval), first only
  running read-only maintenance tasks (daily read-only demo reconciliation, health). Verify whether fresh sessions see
  `/mnt/project-files`.
- Risks: scheduled-task reliability, git push contention with other threads, plan usage limits.
- Evidence: a week of heartbeat runs with no lost or duplicated task and correct recovery from a killed run.

### Phase D: agent responsibilities and B5 integration

- Files: `office/roles/*.md` procedures, `office/authorisations/research.json` (empty grants until O5),
  `office/research_gate.py` (RSA), read-only adapters to `edge_registry`; retire `research/LOOP.md` and
  `strategy.json` discretionary mode (O10).
- B5 integration is read-only (registry, results, status) until PR #19 is merged (O3); the office never calls
  `edge_b5_run`.
- Tests: R1 refused without grant, spent grant refused, holdout path refused, failed preflight recorded as blocked
  and Director picks other work, reviewer cannot write the reviewed result.
- Evidence: unattended R0 work (discovery, evidence, audits, remediation items 1-3) progressing with records.

### Phase E: Relationship and Regime, Meta-Analysis

- Files: `office/relationships.py`, `office/regimes.py`, `office/meta.py`, tests on synthetic strategies with known
  correlation and regime structure.
- Runs only on recorded results and synthetic data unless an R1 grant exists.
- Evidence: synthetic recovery tests pass; every explored combination appears as a registered variant.

### Phase F: robustness tests with synthetic fixtures

- Worker kill mid-task, duplicate workers, expired lease, push conflicts, failed gates, poisoned task, budget breach,
  broker outage, stale quotes, duplicate decision, rejected order, reconciliation mismatch, using a fake broker;
  then `office/trade_gate.py` tested against the fake broker and in demo dry-run (no orders).
- Execution tests on the real demo need O8 (tradeable demo) and a test-only DEM from the owner.

### Phase G: deploy in research-only mode, demonstrate unattended progress

- Enable the heartbeat (owner approval), run for an agreed period (suggest 14 days) with bounded budgets; report
  queue metrics, tasks completed, failures and recoveries, usage, and dashboard evidence. Execution stays off unless
  the owner grants a DEM.
- Success criterion for calling it "always on": no gap longer than two heartbeats without a successful worker run,
  zero duplicate executions, zero unrecorded tasks, measured usage within budget.

## 10. What can be automated immediately vs what needs permission

- Immediately after O1/O2 (no new permissions): read-only reconciliation and health monitoring, the record store,
  discovery and evidence collection, data audits, analysis of recorded results, spec preparation.
- Needs owner grants: any scheduled task (each one), R1 experiments (O5, O7), Check 4 completion (O6), D31 fix (O4),
  demo execution (O8, O9), retirements (O10). Live ISA: not in this plan (O13).

## 11. Main risks

- Calling the system always-on before Phase G proves it. Mitigation: the explicit criterion above.
- Many unattended analyses of the same 2015-2022 data inflate false discoveries. Mitigation: register first, count
  effective N, keep exploratory labels, one confirmation batch ever.
- Agent drift into gate or config edits. Mitigation: gates and mandates in code at fixed paths, owner-only changes
  via reviewed PRs, auditor checks every event.
- Contention with the equity pipeline and the monitor threads on git. Mitigation: separate `office-state` branch.
- Usage limits of the owner's Claude plan (Unknown). Mitigation: budgets enforced in code and visible on the dashboard.
- Demo results being read as evidence for the ISA. Mitigation: separate mandates, readiness review, and labels.

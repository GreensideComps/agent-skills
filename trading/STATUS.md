# System status: factual audit (2026-10-13, ~13:30 UTC)

"Verified" means observed directly (API responses, git commits, run logs). A schedule or a config file existing is not
treated as proof that something runs.

## 1. What runs automatically today

| Component | Schedule | State | Evidence of execution |
|---|---|---|---|
| Routine **T212 demo: trading ops** (`trig_015u78BVGNK8bFDbg26cwcn8`) | Weekdays 10:07 Europe/London | **Enabled, never run in its current form.** First run 2026-10-14 10:07 BST. | None yet. Each run commits `ops: trading run …` to the branch, which is how success is verified. |
| Routine **T212 demo: research loop** (`trig_019cbvFKHAnfuPE24Bqexu9L`) | Daily 01:13 and 13:13 Europe/London | **Enabled, never run in its current form.** First run 2026-10-14 01:13 BST. | None yet. Each run should commit `research: …`, a `LOG.md` row and an experiment record. |
| One-off check-in (`trig_01LAoMGvBxfcUNQXqgpKp17w`) | 2026-10-14 09:35 UTC | Pending | Will inspect both routines' first runs and report |
| **Daily intelligence report + email** | none | **Not scheduled.** Runs only when invoked; email not configured. | `reports/daily/2026-10-13.md` produced manually |

Both routines fire into one Claude session (`T212 demo: trading ops (scheduled, v2)`) that was created with the repo as its
source and `claude/trading212-agent-skills-r71zy3` as its output branch. That session gives them the allow rule in
`.claude/settings.json` and the right to push.

## 2. Research routine and push notifications

- **Research:** one earlier test run (a fresh routine session, 2026-10-13 12:19 UTC) did real work on P1 and P2 but **could not
  push** (git 403: the repo wasn't attached to that session). Its results are lost and recorded as `PENDING_RERUN` (E006/E007).
  The current routine targets a session with push access. **Not yet verified.**
- **Push notifications:** **unverified.** One test routine session called the push-notification tool (2026-10-13 12:16 UTC);
  whether it reached your phone is unknown. The current routines are bound to a persistent session, so routine-level push
  settings don't apply. They rely on the session calling the push-notification tool. Please confirm whether you received any.

## 3. Why the trading routine "looked disabled", and what enabling it needs

It is **enabled**, but has not yet run successfully under the schedule. The history:
1. A fresh-session routine (no repo attached) was **blocked by the auto-mode permission classifier** when it ran
   `bash trading/ops_run.sh` ("real-world transactions").
2. Fix: a narrow allow rule `Bash(bash trading/ops_run.sh)` in `.claude/settings.json`. That file is only read by sessions
   that start with the repo attached, so the routine was rebound to such a session, now also with an output branch so it can push.
3. Manual "run now" from this session (`fire_trigger`) and creating extra sessions (`create_session`) were **blocked by the
   classifier**. So the first real test is the scheduled 10:07 run on 2026-10-14.

**To verify sooner:** press **Run now** on the routine in claude.ai → Routines, or add `"mcp__claude-code-remote__fire_trigger"` to
`permissions.allow` in `.claude/settings.json` yourself. Claude may not change its own permissions.
**If the 10:07 run is still blocked:** the remaining option is to create the routine yourself in the claude.ai Routines UI with
the repo and branch selected (exact settings in `RUNBOOK.md`).
No permission changes were made in this milestone.

## 4. Reporting, reconciliation and performance tracking

| Capability | Before this milestone | Now |
|---|---|---|
| Portfolio report | `PERFORMANCE.md`: account vs shadow portfolios, fill slippage | + **daily intelligence report** (`reports/daily/`), 9 sections, provenance-labelled |
| Transaction reconciliation | Fills matched to orders (slippage) | + **R1–R5 identities**: total, positions, cash ledger, gain, quantities. All PASS on the live demo account today. |
| Performance | Snapshot values vs shadows | + deposits/withdrawals, net contributions, **time-weighted return**, high-water mark, drawdown, fees by type, dividends |
| Research reporting | `LOG.md` text | + structured **experiment registry** (`research/experiments/E001–E007`), with every number generated from committed CSVs |
| Withdrawal advice | none | **Adviser**: £0 by default, opt-in rules, scenarios, selling plan, separate ISA/GIA notes, de-duplicated notifications |

## 5. Email delivery infrastructure

- **Available:** nothing usable unattended. No email credentials exist in the environment. **Outbound SMTP is blocked** from
  these cloud sessions (ports 465/587 time out), while HTTPS email APIs (Resend, Mailgun, Postmark, SendGrid) are reachable.
  The claude.ai Gmail connector here can create drafts but not send, and routines carry no connectors anyway.
- **Implemented:** a provider-agnostic sender (Resend over HTTPS, SMTP for machines that allow it, and an outbox for dry runs).
  It has retries, a delivery ledger, idempotency keys, a crash-safe lock and a UK-local schedule gate. All are covered by tests
  with simulated providers.
- **Real email test: NOT done.** It's blocked on credentials. A `--send` attempt today correctly recorded `outbox` ("NOT emailed")
  and exited with code 3. Delivery must not be considered working until you add the variables in `REPORTING.md` and confirm an email arrived.

## 6. What remains incomplete

1. **Email:** add the Resend key and addresses, then run the real test and confirm receipt. *(Needs you.)*
2. **Report schedule:** choose option A, B or C in `REPORTING.md`. *(Needs you: creating routines or workflows wasn't part of this milestone.)*
3. **Routines:** first scheduled runs tonight and tomorrow are unverified. The check-in at 09:35 UTC tomorrow will report.
4. **Research:** E006/E007 (P1/P2) need a verifiable re-run.
5. **Push notifications:** delivery to your phone is unconfirmed.
6. **Adviser:** `account_type` is assumed `GIA` (the API can't tell), and flexible-ISA status is unknown. Confirm both if you ever use an ISA.
7. **Statistical power:** live results are far too short to judge the strategy. The report says so every day.

## Safety boundaries kept in this milestone

Practice account only. No live access. No orders placed, changed or cancelled. No routines or permissions created or modified.
Reporting code uses a read-only client that cannot reach order methods, and the adviser has no client at all. The test
`test_adviser_cannot_trade_or_move_money` enforces both.

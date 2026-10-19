# System status: factual audit (updated 2026-10-14)

> **2026-10-19: strategy retired (owner decision O10).** `config/strategy.json` is now mode `retired` with no targets;
> runs snapshot and reconcile read-only, then halt without planning an order. The previous `discretionary_intraday_v1`
> config is archived in `config/archive/`. Everything below is history.
>
> **Scheduled tasks that ran the old strategy are DISABLED, not deleted** (listed 2026-10-19). They still exist on the
> account and point at branch `claude/trading212-agent-skills-r71zy3`, which keeps the old config. Re-enabling one would
> run the old strategy from that branch; this retirement does not reach it. Deleting them is an owner decision.
>
> | Task | Id | Enabled | Branch it uses | Last fired |
> |---|---|---|---|---|
> | T212 demo: hourly trader + monitor | `trig_01Qh8CiQcWpUK4Jop7EvdEH4` | no | r71zy3 | 2026-10-14 |
> | T212 demo: hourly trader + monitor (older copy) | `trig_01HwinHAEB3cteN7zavwCGzQ` | no | r71zy3 | 2026-10-14 |
> | T212 demo: trading ops | `trig_015u78BVGNK8bFDbg26cwcn8` | no | r71zy3 | 2026-10-14 |
> | T212 demo: research loop | `trig_019cbvFKHAnfuPE24Bqexu9L` | no | r71zy3 | 2026-10-14 |
> | Weekday portfolio brief (old, persistent session) | `trig_0188Bhwdq38sQhN9zZAauah7` | no | read-only brief | 2026-10-15 |
>
> On this branch `ops_run.sh` refuses (exit 5) before any git sync while the strategy is retired.

> **Current strategy (2026-10-14): `discretionary_intraday_v1`** (`config/strategy.json`, mode `discretionary`).
> Owner override: Claude trades the whole Practice account intraday within the limits in `decision_limits`
> (universe LQQ3, EQQQ, VUAG, SGLN, 3LGO; at most 8 decisions a day; 10% daily loss stop; long-only, no borrowing,
> no inverse products). The previous rule, `nasdaq3x_trend_sma100_v1` (E009), now runs only as the paper shadow
> `B_live_rules_at_close`. The repository's research rejected every intraday approach it tested (E008, E010, E011,
> E012, E014); the owner chose this mode knowing that.
>
> **Scheduling as of 2026-10-14** is audited in [`../docs/AUDIT_AND_PLAN.md`](../docs/AUDIT_AND_PLAN.md) §4: trading
> ops and the research loop run; the hourly trader + monitor missed 3 of 6 expected runs on 2026-10-14; the daily
> report is still unscheduled. Section 1 below is the 2026-10-13 snapshot and is kept for history.
>
> 2026-10-13 ~17:43 UTC: account reset by the owner to £500 cash, strategy switched to `nasdaq3x_trend_sma100_v1`,
> old journal archived. Sections 2 onwards describe the pre-reset £100 period.

"Verified" means observed directly (API responses, git commits, run output). A schedule or config file existing is not
proof that anything runs. Assumptions and unknowns are labelled.

## 1. Scheduled automation (snapshot 2026-10-13; superseded by AUDIT_AND_PLAN.md §4)

| Component | Schedule | Verified state | Evidence of a successful run |
|---|---|---|---|
| Routine **T212 demo: research loop** (`trig_019cbvFKHAnfuPE24Bqexu9L`) | 01:13 and 13:13 Europe/London | Enabled; `last_run` empty; next run 2026-10-14 00:13 UTC | **None yet.** Not operational until a `research:` commit lands from it. |
| Routine **T212 demo: trading ops** (`trig_015u78BVGNK8bFDbg26cwcn8`) | Weekdays 10:07 Europe/London | Enabled; `last_run` empty; next run 2026-10-14 09:07 UTC | **None yet.** Not operational until an `ops: trading run` commit lands from it. |
| Check-ins (`trig_01QT1tG9RkecCbTkwPMDUn11`, `trig_01LAoMGvBxfcUNQXqgpKp17w`) | 2026-10-14 00:50 and 09:35 UTC | Pending | Each will inspect the run, fix failures and update this file |
| **Daily report + email** | none | **Not scheduled.** No GitHub workflows exist in the repo (GitHub API: `total_count: 0`), and no routine runs it. | Report produced manually: `reports/daily/2026-10-13.md` |

Both routines fire into the session `session_01F4uFy8TB6eMUyemT5Ba7e8`, which has the repo attached and an output branch
(needed for `.claude/settings.json` allow rules and for pushing). Earlier history: one fresh-session routine was blocked by
the permission classifier, and one research test run could not push (403). Its P1/P2 results were re-run and committed on 2026-10-13 (E006/E007).

**Push notifications:** unverified. Earlier test sessions called the push-notification tool 3 times (12:16–12:19 UTC);
whether anything reached your phone is unknown. Those session logs are no longer retrievable.

## 2. Email delivery

| Item | State |
|---|---|
| Credentials | **Configured** (Resend; From `onboarding@resend.dev`; To set). `email-check` OK. |
| Delivery semantics | `sent` = accepted only. The bot polls Resend `GET /emails/{id}` and records `confirmed_delivered` / `confirmed_failed` / `unconfirmed`. Only `confirmed_delivered` is PASS. |
| Failure handling, live | **Verified 13:30 UTC** against the real Resend API with an invalid key: recorded `failed` (HTTP 401, not retried), nothing recorded as sent or delivered. Evidence: `reports/verification/2026-10-13-email-failure-test.md` |
| Failure handling, after acceptance | Bounce, failure, suppression, complaint, delay: unit-tested with a simulated provider (113 tests pass) |
| Successful real delivery | **Verified 13:47 UTC:** today's report sent to the owner address; Resend reports `delivered`, `email-status` exit 0. Evidence: `reports/verification/2026-10-13-real-delivery-test.md`. Inbox vs spam placement: check once. |

Outbound SMTP (465/587) is blocked from Claude cloud sessions, while HTTPS email APIs are reachable (tested 2026-10-13).

## 3. Report vs account reconciliation

**Verified 13:33 UTC:** `verify-report` re-fetched the raw API through the read-only client and re-derived every figure with
separate code (`t212bot/verify.py`). **37 pass, 0 fail**: cash, holdings and quantities, cost basis, all 3 orders (fill
price, net value, fees), deposits, fees by type, quantities = Σ fills, cash ledger (£100.00 − £98.48 buys = £1.52),
TWR (−0.71%) and max drawdown (−0.72%). Evidence: `reports/verification/2026-10-13-report-vs-account.md`.

- **Explained difference, not an error:** position cost basis totals £98.41, while buy fills total £98.48. The £0.07 gap is the
  FX fee on the USD-listed IWMO buy. It's included in the fill's `netValue` but not in the position cost.
- **Bug found and fixed:** the report's TWR sorted snapshots by (time, value), so two snapshots with the *same* timestamp
  were ordered by value. Now sorted by time only, with a regression test. Live data had no tied timestamps (checked), so
  the published figures were unaffected.

**Recommendation-only adviser, verified statically:** the adviser module has no client, order or network code; the
read-only client allowlist contains only GET methods; and the cached official OpenAPI spec has 17 paths, none for
withdrawals, transfers or deposits. Today's recommendation: £0, no notification.

## 4. Scheduler decision

Recommended: **GitHub Actions for the daily report**, with the Claude routines kept for trading and research. Comparison and
exact setup are in `REPORTING.md` → "Scheduling". **Not active:** it needs you to add secrets and commit the workflow to `master`.

## 5. Open items

1. ~~Email credentials and real test~~: done 13:47 UTC (`confirmed_delivered`). Confirm the email is in your inbox, not spam.
2. **Report scheduler** (you): GitHub Actions setup steps in `REPORTING.md`.
3. **First routine runs:** research 00:13 UTC and ops 09:07 UTC on 2026-10-14. Unverified until the check-ins report.
4. ~~E006/E007 re-run~~: done 2026-10-13 ~18:30 UTC with committed code (`research/h01_momentum_sleeve.py`). P1 rejected; P2 insurance only. Champion unchanged.
8. **Fixed:** a safety test read the API spec from the gitignored `trading/cache/`, so it failed in every fresh container. Because `ops_run.sh` skips trading when any test fails, the scheduled ops run would have refused to trade. The official spec (17 paths, none that move money) is now committed at `trading/spec/t212_openapi.yaml`; 114/114 tests pass on a clean checkout.
5. **Push notifications:** confirm whether you received any.
6. **Adviser:** `account_type` is assumed GIA (the API can't tell), and flexible-ISA status is unknown.
7. **Statistical power:** less than one day of live data. Nothing about strategy quality can be concluded yet.

## Safety boundaries kept

Practice account only; no live access. No orders placed, changed or cancelled in this milestone. No routines, workflows or
permissions created or modified. No automated withdrawals (the API has no endpoint for them).

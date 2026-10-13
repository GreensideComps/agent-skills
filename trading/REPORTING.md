# Daily intelligence report, email delivery and withdrawal adviser

Everything here only **reads** from Trading 212, through a `ReadOnlyClient` that cannot reach order methods. The
withdrawal adviser makes recommendations and never acts. The Trading 212 API has no withdrawal or transfer endpoint, so
moving money out is impossible from this code.

## Commands (run from `trading/`)

| Command | What it does |
|---|---|
| `python3 -m t212bot daily-report` | Builds today's report, stores it, records a verified snapshot. No email. |
| `python3 -m t212bot daily-report --send` | The same, then emails it. Exit code 3 if it wasn't delivered. |
| `python3 -m t212bot daily-report --send --respect-schedule` | For schedulers. Runs only after the UK-local report time, and only if today's report hasn't already been delivered. Safe to trigger hourly. |
| `python3 -m t212bot daily-report --send --force` | Re-sends even if already delivered today (manual recovery or test). |
| `python3 -m t212bot daily-report --sample` | Writes the **EXAMPLE DATA** sample to `reports/daily/SAMPLE_daily_report.md`. |
| `python3 -m t212bot advise` | Prints today's withdrawal recommendation. |
| `python3 -m t212bot email-check` | Validates email configuration without sending. It does not prove delivery. |

Exit codes: `0` OK · `1` unexpected error · `2` report produced but **critical data problems** · `3` email not delivered or not configured · `4` not due yet, or already delivered today.

## What gets stored (commit these for history)

| Path | Content |
|---|---|
| `reports/daily/YYYY-MM-DD.md` / `.html` | The report, as sent |
| `reports/metrics/YYYY-MM-DD.json` | Every number in the report plus the delivery outcome. Used for day-to-day comparisons. |
| `reports/delivery_log.jsonl` | Append-only record of every email attempt, retry, success, failure, duplicate skip and lock recovery |
| `reports/adviser_state.json` | High-water marks and the last notified recommendation, which drives de-duplication |
| `journal/snapshots.csv` | Each report adds one verified account reading, used for the time-weighted return |

## Email setup (one-time, needs you)

**Why not iCloud or Gmail SMTP?** Outbound SMTP (ports 465/587) is blocked from the Claude cloud environment
(tested 2026-10-13), while HTTPS email APIs are reachable. Resend uses plain HTTPS, needs no extra packages, and has a free tier.

1. Create a free account at <https://resend.com>, signing up with the address you want the reports sent to.
2. Create an API key (Dashboard → API Keys), with "Sending access" only.
3. Until you verify a domain, Resend only lets you send **from** `onboarding@resend.dev` **to your own account email**.
   That's enough for personal reports. To send from your own address, verify a domain in Resend.
4. Add these as **environment variables** in the Claude environment (session title bar → environment → Edit).
   Never paste them into chat or commit them:

   ```
   REPORT_EMAIL_PROVIDER=resend
   REPORT_EMAIL_TO=<your address>
   REPORT_EMAIL_FROM=T212 Bot <onboarding@resend.dev>
   RESEND_API_KEY=<the key>
   ```
5. Start a new session (environment variables are read at start) and run
   `python3 -m t212bot email-check`, then `python3 -m t212bot daily-report --send --force`. **Confirm the email arrived.**
   The delivery log records `sent` only when Resend accepts the message. Your inbox is the final proof.

On a machine that allows SMTP, you can instead set `REPORT_EMAIL_PROVIDER=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD` (an app-specific password) and `SMTP_SSL=1` for port 465.

## Scheduling (choose one, needs you)

The report time is set in `config/reporting.json` (`report_time_local`, default `07:30`, `Europe/London`). Daylight saving
is handled with Python's `zoneinfo`. With `--respect-schedule`, a trigger that fires early or repeatedly does nothing until
the local time is reached, then sends exactly once.

| Option | How | Notes |
|---|---|---|
| **A. Claude routine** | claude.ai → Routines → New: repo `GreensideComps/agent-skills`, branch `claude/trading212-agent-skills-r71zy3`, this environment, schedule daily 07:31 Europe/London, prompt: *"Run `cd trading && python3 -m t212bot daily-report --send --respect-schedule`, then commit `trading/reports` and `trading/journal` and push. Report the exit code. Read-only; never place orders."* | Uses the environment variables above. The session needs the repo attached so it can push. |
| **B. GitHub Actions** | Copy `deploy/daily-report.github-actions.yml.example` to `.github/workflows/daily-report.yml` and add repository secrets `T212_API_KEY`, `T212_API_SECRET`, `RESEND_API_KEY`, `REPORT_EMAIL_TO`, `REPORT_EMAIL_FROM` | Independent of Claude. GitHub cron runs in UTC and can be late, which the hourly trigger plus `--respect-schedule` absorbs. |
| **C. Your own always-on machine** | `crontab`: `CRON_TZ=Europe/London` then `31 7 * * * cd …/trading && python3 -m t212bot daily-report --send --respect-schedule` | SMTP works here if your network allows it |

Without one of these, nothing sends a report on its own: the commands only run when invoked.

## Withdrawal adviser (`config/adviser.json`)

- Default answer: **£0**. Every rule that can produce a positive amount is off until you switch it on:
  - `liquidity_needs`: planned expenses, e.g. `[{"amount": 40, "by": "2027-03-01", "label": "holiday"}]`. The adviser suggests taking the money out within `liquidity_need_lead_days` of the date, so you aren't forced to sell in a slump.
  - `max_capital_at_risk_gbp`: anything above this cap is suggested for withdrawal.
  - `profit_lock`: once gains reach a share of contributions, harvest a fraction of *new* gains only.
- It always shows: the gain after deposits and withdrawals, the calculation, the assumptions, conservative/base/adverse
  scenarios, the cost to future compounding, whether investments would have to be sold (with estimated costs and a
  per-holding plan), and separate ISA or GIA tax notes. The API can't tell ISA from GIA, so `account_type` comes from config.
- Gates: unreliable data, or an amount below the meaningful threshold, means £0.
- Notifications: a separate email goes out only for a new or materially changed positive recommendation, a monthly reminder, or when a previous recommendation no longer stands. £0 appears only in the daily report.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `email-check`: NOT CONFIGURED FOR DELIVERY | Provider is `outbox`. Set the variables above and start a new session. |
| Delivery log `failed` with `resend HTTP 401` | Wrong or revoked API key |
| Delivery log `failed` with `resend HTTP 403/422` | Sender or recipient not allowed. Until a domain is verified, send from `onboarding@resend.dev` to your Resend account email only. The error text in the log gives Resend's exact reason. |
| `retry` entries then `sent` | Transient network or 5xx errors were retried. No action needed. |
| `skipped_duplicate` | Already delivered for that date. Use `--force` to resend. |
| `lock_recovered` | An earlier job crashed mid-send. The stale lock was cleared, and Resend's idempotency key prevents a double send. |
| Report banner **CRITICAL: reconciliation failed** | Account records don't add up. The adviser refuses to recommend anything until fixed. Check the R1–R5 rows in section 8. |
| Health WARN "trading bot has not run" | The scheduled ops routine didn't run. See RUNBOOK.md. |
| Health WARN "Market data is stale" | Yahoo price history didn't update. Benchmarks and volatility are then estimates from old data. |

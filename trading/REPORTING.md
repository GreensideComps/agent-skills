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
| `python3 -m t212bot email-status` | Shows the latest delivery, re-checks it with Resend, and exits 0 only if Resend reports it **delivered** |
| `python3 -m t212bot verify-report [--date D]` | Re-fetches the raw API and independently re-derives every report figure. Writes `reports/verification/D-report-vs-account.md`; exit 2 on any discrepancy. |

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
   `python3 -m t212bot email-check`, then `python3 -m t212bot daily-report --send --force`, then `python3 -m t212bot email-status`.
   **Delivery statuses:** `sent` means only that Resend *accepted* the message. After sending, the bot polls
   `GET /emails/{id}` and records `confirmed_delivered`, `confirmed_failed` (bounced, failed, suppressed, complained,
   canceled) or `unconfirmed` (still queued or delayed). Only `confirmed_delivered` counts as PASS in the report's
   health table. Check your inbox too.

On a machine that allows SMTP, you can instead set `REPORT_EMAIL_PROVIDER=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD` (an app-specific password) and `SMTP_SSL=1` for port 465.

## Scheduling: comparison and recommendation

Report time is set in `config/reporting.json` (`report_time_local` `07:30`, `Europe/London`; DST handled by `zoneinfo`).
With `--respect-schedule`, a trigger that fires early or repeatedly does nothing until that local time, then sends once.

**As of 2026-10-13 no scheduler runs the report.** The repository has no GitHub workflows (checked via the GitHub API),
and neither Claude routine runs `daily-report`.

| Criterion | Claude routine | GitHub Actions |
|---|---|---|
| Reliability | An LLM session interprets a prompt each run. Our routines have already been **blocked by the auto-mode permission classifier** once and **failed to push (403)** once. The rebound routines are not yet proven. | Deterministic script, exit codes. GitHub warns the `schedule` event "can be delayed" under load and queued jobs "may be dropped" ([docs](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)). Mitigated by four hourly attempts plus the idempotent schedule gate. |
| Security | Credentials are environment variables of the Claude environment, visible to every session in it. The model has a shell holding them. | Encrypted repository secrets, available only to this job. No model in the loop. The job runs only read-only Trading 212 calls. |
| Cost | Uses your Claude plan's usage on every run | Free on public repos. On private repos it counts against the plan's included Actions minutes; about 1 minute per attempt, so roughly 120 minutes a month. |
| Maintainability | Behaviour lives in a prose prompt that can drift between runs | Versioned YAML in the repo, with `deploy/daily-report.github-actions.yml.example` as the source |
| Alerting | Only if the session decides to send a push notification. Delivery of those is unverified. | A failed job (exit 1/2/3, or a verifier discrepancy) triggers GitHub's own failure email. That works even when Resend itself is the thing that's broken. Notifications for scheduled workflows go to "the user who last modified the cron syntax". |
| Constraints | Minimum interval hourly; needs the repo attached and an output branch to push | `schedule` runs **only from the default branch** (`master`). Scheduled workflows in a *public* repo are disabled after 60 days without repository activity; the daily commits keep it active. |

**Recommendation: GitHub Actions for the daily report.** Keep the Claude routines for the trading ops and research loop,
which need judgement. A report email is a deterministic job whose failure must be noticed even when the email path is
broken, and that's exactly what Actions provides.

**Avoiding duplicate reports:** use one scheduler only. If two ever run, the committed `reports/delivery_log.jsonl`
skips a date that is already delivered, and the Resend `Idempotency-Key` (the same key for the same date and recipient)
stops a double send within 24 hours, even if two jobs race before either has pushed.

### Manual setup (needs you; Claude may not create schedules or change permissions)

1. Do the **Email setup** above, then send the one-off test from a Claude session and check `email-status` shows
   `confirmed_delivered`.
2. GitHub → `GreensideComps/agent-skills` → Settings → Secrets and variables → Actions → **New repository secret**, five times:
   `T212_API_KEY`, `T212_API_SECRET` (the **Practice** key pair), `RESEND_API_KEY`, `REPORT_EMAIL_TO`, `REPORT_EMAIL_FROM`.
3. On the **default branch `master`**, create `.github/workflows/daily-report.yml` with the contents of
   `trading/deploy/daily-report.github-actions.yml.example`. In the GitHub web UI: Add file → Create new file → paste →
   Commit directly to master. It must be on `master`, or GitHub never schedules it.
4. Settings → Actions → General: make sure Actions are allowed, and that **Workflow permissions** allow read and write
   (the job commits the report history back to the bot branch).
5. Actions tab → `t212-daily-report` → **Run workflow** (branch `master`). After 07:30 UK time this sends today's report, unless today's
   is already delivered. Before 07:30 it exits 4 ("not due"), which also shows green. Check that the run is green, that
   a `report:` commit landed on the bot branch, and that the email arrived.
6. Make sure GitHub notifications for Actions are on (Settings → Notifications → Actions → "Only notify for failed workflows").

**What a run does:** `daily-report --send --respect-schedule` builds the report, sends it, then polls Resend until it reads
`delivered` (exit 0) or a failure such as a bounce (exit 3). Next it runs `verify-report`, which re-derives every figure
from the raw API (exit 2 on any discrepancy), and finally commits `trading/reports` and `trading/journal`.

**Option C, your own always-on machine** (unchanged): add to `crontab` the line `CRON_TZ=Europe/London` and then
`31 7 * * * cd …/trading && python3 -m t212bot daily-report --send --respect-schedule`. SMTP works there if your network allows it.

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
| `sent` then `unconfirmed` | Resend accepted the message but hadn't delivered it within about a minute (queued or `delivery_delayed`; Resend retries for up to 14 hours). Run `email-status` later. |
| `confirmed_failed` | Resend reports a bounce, failure, suppression or complaint. The report exits 3 and the next report raises a CRITICAL alert. Check the recipient address and the Resend dashboard → Emails. |
| `skipped_duplicate` | Already delivered for that date. Use `--force` to resend. |
| `lock_recovered` | An earlier job crashed mid-send. The stale lock was cleared, and Resend's idempotency key prevents a double send. |
| Report banner **CRITICAL: reconciliation failed** | Account records don't add up. The adviser refuses to recommend anything until fixed. Check the R1–R5 rows in section 8. |
| Health WARN "trading bot has not run" | The scheduled ops routine didn't run. See RUNBOOK.md. |
| Health WARN "Market data is stale" | Yahoo price history didn't update. Benchmarks and volatility are then estimates from old data. |

# Real email delivery test (2026-10-13)

**Purpose:** prove end-to-end delivery of the daily report to the owner's configured address, not a test sink.
**Config:** `REPORT_EMAIL_PROVIDER=resend`, `REPORT_EMAIL_FROM=T212 Bot <onboarding@resend.dev>`, `REPORT_EMAIL_TO` set
(owner address; stored in the ledger only as hash `f018f3e5b1bd`). `email-check` returned OK.

Commands run from `trading/`:

1. `python3 -m t212bot email-check` → `OK - configuration complete`
2. `python3 -m t212bot daily-report --send --force` → exit 0
3. `python3 -m t212bot email-status` → exit 0

Observed (from `reports/delivery_log.jsonl`):

| ts_utc | status | detail |
|---|---|---|
| 13:47:28 | `sent` | accepted by provider, 1 attempt |
| 13:47:40 | `confirmed_delivered` | provider last_event='delivered' |

Resend email id: `01a13584-a89b-7ad2-82e8-27b2a8100ee5`.

**Proven:** Resend accepted the real report for the owner's address and reports it `delivered` (accepted by the
recipient's mail server). **Not proven by this:** that it landed in the inbox rather than spam. Check the inbox once.

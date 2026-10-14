# Resend key and confirmation-path check (2026-10-13)

**Purpose:** confirm the configured `RESEND_API_KEY` works and that provider-side confirmation works against the live API,
without emailing the owner.
**Method:** `emailer.deliver()` sent to Resend's test sink address `delivered@resend.dev`, from
`T212 Bot <onboarding@resend.dev>`, using a scratch ledger. Then `confirm_delivery()` polled `GET /emails/{id}`.

Observed output (verbatim):

```
send: sent | accepted by provider
provider status: confirmed_delivered delivered
```

**Proven:** the key is valid; Resend accepts our payload; the bot reads `last_event` back and records `confirmed_delivered`.
**Not proven:** delivery to the owner's inbox. The environment as configured had `REPORT_EMAIL_TO` unset, and
`REPORT_EMAIL_FROM` was missing the angle brackets (`T212 Bot onboarding@resend.dev`). `email-check` now flags both.

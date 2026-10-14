# Email failure-handling test against the live Resend API (2026-10-13 13:30 UTC)

**Purpose:** prove that a failed send is recorded as failed and never as sent or delivered.
**Method:** `emailer.deliver()` was called against the real `https://api.resend.com/emails` with a deliberately invalid
API key (`re_deliberately_invalid_0000`). The recipient was Resend's test address `delivered@resend.dev`. A scratch ledger
was used, so the production `reports/delivery_log.jsonl` was not touched.

Observed output (verbatim):

```
result: failed | permanent: resend HTTP 401: {"message":"API key is invalid","name":"validation_error","statusCode":401} | attempts 1
confirmation: not_applicable
ledger: 2026-10-13T13:30:18+00:00 failed permanent: resend HTTP 401: {"message":"API key is invalid","name":"validation_error","statusCode":401}
PASS: failed send recorded as failed; nothing recorded as sent/delivered
```

- The 401 was classified as permanent, so it was not retried. (429 and 5xx are retried with backoff; covered by unit tests.)
- No provider confirmation was attempted, because nothing was accepted.
- Bounced, failed, suppressed and complained outcomes *after* acceptance are covered by unit tests with a simulated provider
  (`test_provider_failure_is_never_recorded_as_delivered`, `test_end_to_end_bounce_exits_3_and_next_report_says_not_delivered`).

**Not yet proven:** a successful real delivery. That needs a real `RESEND_API_KEY` in the environment (see `REPORTING.md`).

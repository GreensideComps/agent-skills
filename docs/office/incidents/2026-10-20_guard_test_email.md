# Incident 2026-10-20: a guard-removal test sent one real demo report email

Status: closed, pending owner review. Severity: low (one email to the owner's own configured report address; demo
account only; no order, cancellation or account change was possible).

## What happened

While checking that the new bot-branch retirement tests fail when a guard is removed (a mutation check), the
bot-branch suite was run once in a scratch copy with the CLI guard deleted.

| Field | Value |
|---|---|
| Test path | `trading/tests/test_retired_branch.py::test_every_cli_command_refuses_before_touching_credentials_or_the_broker[argv8]`, the `["daily-report", "--send", "--force"]` case |
| Code state | scratch copy `/tmp/claude-0/o10b/mut` of branch `claude/trading212-agent-skills-r71zy3` before commit `e07a3e3`, with the `if retired.BRANCH_RETIRED:` block removed from `t212bot/__main__.py` (now deleted) |
| Why it escaped | that test patched `config.load_credentials` for the CLI, but `daily.run` loads its own credentials and the session environment held the demo key and email settings; the module had no network block yet |
| Provider | Resend, message id `01a15831-ad1e-755b-895d-85520f14c216` |
| Sent | `2026-10-20 07:23:33.24 UTC`, last event `delivered` |
| Subject | `[T212 demo] Daily report 2026-10-20 - £1227.55, gain £-72.45 - warnings` |
| Recipient | one address, equal to the configured `REPORT_EMAIL_TO` (sha256 `f018f3e5…ece71`); cc and bcc empty |
| Sender | equal to the configured `REPORT_EMAIL_FROM` |

The provider's sent list holds three messages in total (13 Oct 13:43, 13 Oct 13:47, 20 Oct 07:23), so this run sent
exactly one email. Evidence copied unchanged into `2026-10-20_guard_test_email/`:

| File | sha256 |
|---|---|
| `provider_record.json` (the one message, recipient as a hash) | `e44a024b…14c2c5d` |
| `provider_sent_list.json` (every message the account has sent) | `c940e5e0…3e51d7` |
| `trapped_replay_of_mutant.txt` (the same mutant replayed with all network calls trapped) | `54782c46…44deec` |

## What else the run touched

From the trapped replay of the same mutant (every outbound call recorded and refused):
- `monitor`, `advise` and `daily-report` made **GET** requests only, to the demo API (`account/summary`, `positions`,
  `orders`, `history/orders`, `history/transactions`, `history/dividends`) and to Yahoo chart prices.
- `status`, `run`, `reconcile`, `report` and `decide` stopped at their other guards before any call.
- The replay lists **no POST, PUT, PATCH or DELETE** to any host. In the mutant the client's non-GET refusal and the
  `Bot.run`, `_place` and `decide` refusals were still in place, so an order or cancel could not be sent.

## Fix

- Bot branch, commit `e07a3e3`: autouse fixture in `tests/test_retired_branch.py` strips every `T212*`,
  `REPORT_EMAIL*`, `RESEND*` and `SMTP*` variable and replaces `urllib.request.urlopen`, `OpenerDirector.open`,
  `socket.create_connection` and `socket.socket.connect` with a function that raises, before any test body runs.
- Bot branch, commit `b61e8f7`: two tests of the harness itself.
  - No credential variable is present, and urlopen and both socket routes raise.
  - With `BRANCH_RETIRED` switched off on purpose and a fully configured fake Resend setup: the email send fails
    inside the process (`TransientEmailError`), a broker GET is refused on every retry, and a market-order POST
    fails as `AmbiguousOrderError: transport error AssertionError`. Every attempt is recorded and none leaves.
  - Mutation check: removing the network block fails the harness test, and so does removing the credential strip
    (run with a fake `T212_API_KEY`). Both were run with `env -i` and a dead proxy, so nothing could be sent.
- Master side (PR #20): the same fixture and harness test in `trading/tests/test_retired.py`, and the `ops_run.sh`
  subprocess test now strips the email variables as well as `T212*`.
- No real email was sent and no broker request was made to test the fix.

## Limits of this evidence

- The mutant's own journal and report files were deleted with the scratch directory, so the live run's exact call
  list was not kept. The call list comes from a replay of the same code with calls trapped, not from the live run.
- The replay prints at most 12 distinct calls per command, sorted. The daily-report delivery attempt (a POST to the
  email provider) sorts after the GETs and is cut off the list; the provider record shows it happened.
- No broker-side log was queried, by design: the owner asked for no further broker requests, and the public API exposes
  no request log (inferred from its documentation, not tested). "No orders or cancellations" rests on the code paths above and the trapped replay, not on a broker
  audit. The demo account's order history could confirm it on the next routine read.
- The recipient is recorded as "equal to the configured REPORT_EMAIL_TO" plus a hash; the address itself is not
  written here.

# Demo execution tests: exact proposal (O8/O9 stay BLOCKED)

Status: **proposal only. Nothing is authorised by this file.** O8 (make the demo tradeable) and O9 (the demo test
permission) stay blocked until the owner gives an explicit decision that names this file's commit. No order has been
placed, and no code in this repository can place one through the office package: it has no broker adapter yet. The
adapter is M2 work and is tested against the fake broker before any real order.

## 0. The earlier £10 / £20 ambiguity, resolved

The earlier draft (DECISION_REGISTER §4) said "at most 6 orders", "at most £10 per order" and "£20 in total". Those
limits contradict each other: six £10 orders would be £60. This proposal **replaces all three** with one consistent
set of limits:

| Limit | Value | Enforced by |
|---|---|---|
| Orders submitted to the broker, whole test | **at most 5** (T2 submits none) | hard counter in the event log; the 6th is refused before submission |
| Notional per buy | **at most £5.00** at the last price before intent | intent check (quantity × price) |
| Cumulative gross buys | **at most £15.00** | sum of all test buy intents, checked before each intent |
| Net open test exposure | **at most £10.00** at any moment | position delta × price, checked before each buy intent |
| Sells | only quantity bought by these tests, never more | intent check against the test's own net delta |
| Instrument | **VWRP only** (`VWRPl_EQ`, LSE, GBP) | allow-list of one |
| Final test position | **zero**: the VWRP quantity returns to its pre-test value | final reconciliation (T5) |

The planned buys are T1 (£5) and T5 (£5), £10 gross. T4's buy is rejected by the broker but counts against the
gross cap at intent (about £0.01). The £15 cap leaves headroom for price movement between intent and fill. Net open
exposure never exceeds £5 in the planned sequence, because T1 is closed by T3 before T5 buys. The £10 net cap is
the hard stop if a sequence goes wrong.

## 1. Prerequisite (owner, in the app)

The demo has £0 free cash, and all 22 holdings sit in the ISA-mirror pies (verified 19 Oct 14:40Z). The tests
need **at least £20 free demo cash, added without touching any pie** (O8 option a). If the app cannot add demo cash
without changing a pie or resetting the account, the tests stay blocked. They never sell, move or change a pie
holding.

## 2. Account verification (before T1, and again after T5)

All of these must hold, or nothing is submitted. If any fails after T5, it raises a critical alert:

1. the client's base URL is `https://demo.trading212.com` (the client refuses any other host, and the check is
   repeated here);
2. the account currency is GBP, and the account id matches the fingerprint the owner confirms in the decision
   (sha256 of the id, so the id itself is not written down);
3. free cash is at least £20;
4. **pie snapshot hash:** sha256 of the sorted (ticker, quantity) list of every position plus the pie list, taken
   before T1. After T5, every non-VWRP position matches it exactly, and VWRP matches its pre-test quantity;
5. there are no pending orders before T1;
6. the market is open (LSE 08:00-16:30 London) and more than 30 minutes remain before close.

## 3. The five tests (run in this order; stop at the first failure)

| Test | Direction and size | Expected outcome | Cancellation and recovery | Pass criteria |
|---|---|---|---|---|
| **T1 Fill and reconcile** | BUY VWRP, quantity for at most £5.00 | intent → submitted → filled → reconciled | if it is still working after 60 s, cancel it; an unknown cancel outcome pauses trading | the broker order is filled; the position delta equals the filled quantity within the instrument step; one intent, one broker order |
| **T2 Duplicate refused** | the same decision key as T1, sent again | refused **before** submission; no broker call | none needed | `refused: decision key already used`; the broker's pending and history lists show no new order |
| **T3 Close T1** | SELL exactly T1's filled quantity | filled → reconciled; the test's net delta returns to 0 | as T1 | the position equals its pre-T1 quantity; there is no other change to the account |
| **T4 Broker rejection** | BUY VWRP at a quantity below the instrument's minimum | the broker rejects it; recorded as `rejected`; not retried | none | exactly one submission; the position is unchanged; no resubmission |
| **T5 Ambiguous outcome** | BUY VWRP for at most £5.00; the adapter **discards the broker's response** after sending, then SELL the adopted quantity | `unknown` → lookup finds exactly one matching order → `adopted` → filled → reconciled; then the closing sell is reconciled | if the lookup finds zero orders after the 120 s settle window, or more than one, trading pauses with a critical alert and the closing sell waits for the owner | exactly one broker order for the buy (never resubmitted); the closing sell brings the net delta back to 0 |

Submissions: T1 (1), T3 (1), T4 (1), T5 buy (1), T5 sell (1) = **5**.

## 4. Behaviour on anything unexpected

- **Unknown outcome** of a submit or a cancel: the order is never resubmitted. The adapter looks it up by ticker
  and time window. Exactly one match is adopted; any other result pauses all trading with a critical alert.
- **Reconciliation mismatch** (the position delta differs from fills by more than one instrument step): trading
  pauses with a critical alert, and the remaining tests do not run.
- **Pause:** while paused, every new intent is refused. Only an owner message (a cmsg_ id recorded in the log)
  resumes. A resume does not re-run tests; the owner decides what happens next.
- **Leftover exposure:** if the run stops with a non-zero net test delta, the closing sell is **not** sent
  automatically. The alert names the quantity, and the owner decides.

## 5. Reconciliation criteria (evidence pack)

After the run, the evidence pack (committed to the office branch) contains:

- the event log slice for the run: every intent, submission, broker id, state change and reconciliation, with its
  hash chain;
- the broker's history-orders listing for VWRP for the run window. There must be exactly the 5 orders above
  (T4's as rejected), and no other order in the account in that window;
- position snapshots before and after, with the pie snapshot hash check;
- cash before and after, with the difference explained by fills and fees to within £0.01.

## 6. The permission requested (for later; not now)

**Demo Execution Test Permission:**
- demo host only;
- the 5 tests above, in order, once;
- VWRP only, with the limits in §0;
- one named date window, during LSE hours;
- no pie holdings touched.

It is spent automatically when T5 reconciles, when any test fails, or when the window ends. It does not authorise
autonomous demo trading (L4), any other instrument, any rerun, or anything on the live ISA. Running the tests also
needs the M2 adapter, reviewed and tested against the fake broker first.

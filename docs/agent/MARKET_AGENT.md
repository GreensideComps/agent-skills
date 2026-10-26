# Always-on demo market agent (agent-1.0)

**Mandate:** the owner's 26 Oct 2026 handoff (`cmsg_01U4KMvkBYNknqm4HRVie8uvK9gRYqGXBK4bQP49dBz49i`), covering
the demo account only. The Trading 212 client refuses any host but `demo.trading212.com`, and `load_credentials`
refuses anything but `T212_ENV=demo`.

## What runs

`agent/run.sh` is the supervisor. It starts `python3 -m market_agent run` and restarts it after any exit, with a
backoff from 10 s to 5 min.

| Duty | Interval | Source |
|---|---|---|
| Prices: holdings, VWRP.L, GBPUSD=X, SPY | 60 s | Yahoo spark, polled (no free streaming feed) |
| Account, positions, pending orders, order reconciliation, snapshot, decision | 5 min | Trading 212 demo API |
| Market calendar | 6 h | the broker's own working schedules, holidays included |
| News headlines for holdings | 30 min | Yahoo search |
| Heartbeat | 60 s | `heartbeat.json` plus a `heartbeat` event |

Each duty fails on its own:
- The failure is recorded as `duty_failed` and retried with a backoff (up to 30 min).
- Three failures in a row raise an alert.

## Validation before any use of a price

A price is used only if all of these hold:
- It is a positive, finite number.
- Its timestamp is not in the future.
- It is fresh enough for the market's state, using the broker calendar:
  - 10 min while the market is open;
  - 25 min for London lines, whose Yahoo quotes arrive about 15 min late;
  - 4 days while the market is closed.
- A move of more than 25% from the previous close is held back until a second, later reading confirms it.

A market whose calendar is unknown is treated as closed.

## Decisions (the only actions)

1. **Exits of INTC, BE and TEM** (authorised by the owner): sell the quantity available to trade.
   - Shares held inside a pie show 0 available, and the API cannot sell them. The agent records that as a blocked
     exit and raises an alert.
2. **Core:** idle cash above £20 is invested in VWRP (`VWRPl_EQ`), keeping a £5 buffer.
   - At most one core buy a day.
   - VWRP stays the default core while no tactical strategy has passed the research gates.

Every other pass is recorded as a `decision` with `no_trade: true` and its reasons.

## Risk gate (`execution.risk_check`)

The gate is independent of the decision logic. It refuses an order when any of these is true:
- The kill switch is off.
- Any earlier order intent is unresolved.
- The broker shows a pending order for the ticker.
- There is no validated price.
- The market is closed.
- There have been 2 or more consecutive order errors.
- It is a buy of a ticker outside the whitelist (VWRP only).
- It sells more than is available.
- The order is over £600.
- It would be more than 8 orders in a day.
- It would take the day's turnover over £1,300.

## Duplicate prevention and recovery

**Intent journal:** every order first writes an `intended` record, then its acknowledgement or error, then its outcome
(filled, cancelled or rejected), taken from the broker's order history.

**Ambiguous outcomes:** a timeout or 5xx makes an order `ambiguous`.
- It is never re-sent.
- It blocks all trading until the broker's records explain it.

**Crashes:** an intent left `intended` by a crash is matched against the broker's history after a restart. It is
closed as `not_sent` only when no matching broker order exists.

**One agent at a time:** a lease (`lease.json`, 180 s TTL, renewed every pass) allows only one agent per state
directory.

## State (survives container restarts)

Everything is kept under `/mnt/project-files/market-agent/state/`:

| Path | Contents |
|---|---|
| `events/YYYY-MM-DD.jsonl` | append-only log of every snapshot, decision, alert, quote-state change, failure and start or stop |
| `intents/intents.jsonl` | append-only order journal |
| `baseline.json` | portfolio value and VWRP price at the first priced snapshot, written once |
| `control.json` | the kill switch. If it is missing or unreadable, trading is OFF |

Kill switch commands:
- `python3 -m market_agent halt "reason"` stops all order sending at once.
- `python3 -m market_agent resume "reason"` allows it again.

## Health and uptime

- `python3 -m market_agent status` exits:
  - 0 when healthy;
  - 1 when degraded (stale prices or broker data, failures);
  - 2 when down (no heartbeat for more than 5 min).
- `python3 -m market_agent uptime --hours 24` measures uptime from the heartbeat events and lists every gap over
  3 min.

## Hosting, and its limits

- **Where it runs:** in the Claude Code cloud container of the "Always-on research office plan" thread. A watcher
  process there keeps the session active.
- **Restarts:** an hourly scheduled wake of that session checks `status` and restarts the supervisor if the agent is
  down.
- **Limit:** the platform may reclaim that container, for example on a usage-limit hold. If it does, the agent stays
  down until the next hourly wake. The gap is then visible in `uptime`.
- **No free persistent server exists in this project:**
  - the repository is private, so GitHub Actions has about 2,000 free minutes a month;
  - no device serves Remote Control;
  - paid hosting is excluded.

  This setup is the strongest permitted alternative, and its measured uptime is reported as it is.

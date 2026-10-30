# Always-on demo market agent (agent-1.7)

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

The agent places at most one order per pass, and sends nothing while an earlier order is unresolved. Sells come
before buys.

1. **Full exits:** INTC, BE and TEM (authorised by the owner), and IBTA (decision C2). The agent sells the quantity
   available to trade.
   - Shares inside a pie show 0 available, and the API cannot sell them. The agent records a blocked exit and
     raises an alert.
2. **Active exits** (agent-1.2): each open active trade has its own hard stop, take-profit and time stop.
   - These are checked against validated prices at every decision, which is about every 5 minutes.
3. **Passive rebalance** (agent-1.1/1.2):
   - Trigger: the passive picks exceed 17% of the book, or a name exceeds the 5% cap.
   - Plan: the agent fixes a plan (`state/rebalance_plan.json`) that trims the picks pro rata to 15%. A pick worth
     under £2 after the trim is sold in full.
4. **Core:** cash above the active sleeve's reserve (5% of the book) plus £20 is invested in VWRP.
   - The agent leaves an 8% margin for the broker's hold on buys.
   - Each buy is capped at £600, with 10 minutes between buys.
5. **Active entries** (agent-1.2, decision C6): watchlist names only. No leverage, CFDs or shorting.
   - Each entry is 2% of the book and is tagged with its strategy and rule.
   - `drop_rebound`: a name down 5% or more on the day. Stop −8%, take-profit +6%, time stop 10 days.
   - `breakout_momentum`: a name up 5% or more on the day. Stop −5%, take-profit +10%, time stop 5 days.
   - Sleeve limits:
     - The sleeve's P&L for the day reaching −3% of the book stops entries until the next day.
     - A cumulative active loss of 25% of the £239 sleeve freezes entries and raises a critical alert.
   - Kill rule: after 30 closed trades, a strategy whose average net return (after FX fees) is at or below
     VWRP's over the same holding periods is switched off automatically (`state/strategies.json`).
   - Neither strategy is a proven edge. They exist to learn on forward data only.

6. **Broker-side stops** (agent-1.4): the agent runs only while its host is awake, so each open active trade also
   gets a resting stop sell at the broker, at the trade's own stop-loss price (`state/stops.json`).
   - It is placed during the market's own hours, once per trade, and respects the kill switch. A refusal is
     recorded once and alerted; the agent's own stop still applies while it runs.
   - A broker stop that fills is recorded from the broker's history as the trade's exit (`why: broker_stop`),
     so P&L and the kill rule count it like any other exit.
   - Before the agent's own take-profit, time or stop exit, it cancels the broker stop, then sells on a later pass
     once the broker no longer shows it pending.
7. **Attention spike** (agent-1.4, logged forward only, owner 26 Oct 15:13Z): every 6 hours, each watchlist
   name's English Wikipedia views for the last full day are compared with its own 28-day norm (z-score on log
   views). A z of 3 or more is logged as an `attention_signal` with that day's price move; nothing trades on it
   until it has a forward record. Requests are paced, and a rate-limited name is logged as an error (UNVERIFIED).

8. **Multi-horizon review** (agent-1.5, owner 30 Oct 08:05Z, `review.py`): every 2 hours, each watchlist name
   and open trade is scored from a year of free daily data (Yahoo), the attention z, and Nasdaq's earnings
   calendar.
   - Short: trend vs the 20-day average, RSI(14), volume surge with the day's direction, attention z.
   - Medium: 3- and 6-month momentum, distance from the 52-week high, 20-day volatility.
   - Long: trend vs the 200-day average, 12-1 month momentum, 50-day vs 200-day average.
   - Composite = 0.4 short + 0.35 medium + 0.25 long; components are clipped to [-1, 1]. The weights are a stated
     prior, not fitted.
   - Entries: a 5% move only nominates a name. `breakout_momentum` needs a composite of 0.25 or more;
     `drop_rebound` needs long ≥ 0 and medium ≥ -0.3. No entry within 3 days of earnings, and none without a
     review under 6 hours old (missing data is UNVERIFIED).
   - Exits: an open trade whose composite falls to -0.35 or below exits early (`why: review`), on top of its stops.
9. **social_trend** (agent-1.6, decision C8, owner 30 Oct 08:15Z, `social.py`, spec
   `research/strategies/C8_SOCIAL_AND_MERGER_ARB.md`): a fixed universe of 32 US consumer brands
   (`active.social.universe`, written 30 Oct before any signal), each mapped to its English Wikipedia article.
   - After each Friday US close: the brand's 28-day mean of views vs the 28-day means ending each of the 52 weeks
     before; a candidate needs z ≥ 3, the last 7 days above the 7 before, and the stock not up more than 15% over
     20 trading days. Results go to `state/social.json` and `social_scan` / `social_signal` events.
   - Google Trends (429) and Reddit (403) refuse this host, so candidates count as confirmed without them, as the
     spec allows; every scan records that.
   - Entry: 2% of the book at the next US session (until the Friday + 4 days), once per brand per week.
   - Exits: -12% (also as a broker stop), +25%, 84 calendar days (60 trading days), or attention back below
     baseline + 1 SD at the next weekly scan (`why: attention`). The price review neither gates nor exits these
     trades, but its scores are logged on the entry.
   - Wikimedia rate-limits this host's shared IP, so the scan goes 12 brands a run at 7 s pacing, honours
     Retry-After, and resumes until done. A brand with no data gets no signal.
10. **merger_arb** (agent-1.7, decision C8, `merger.py`): agreed all-cash takeovers found in SEC EDGAR full-text
   search. The SEC requires a contact User-Agent; the owner supplied it (30 Oct 09:47Z). It is read at run time from
   `state/sec_user_agent.txt` or `SEC_USER_AGENT`, is never committed, and is sent only to sec.gov.
   - Every 6 hours: search 180 days of DEFM14A, PREM14A, SC TO-T, SC 14D9 and 8-K filings for "per share in cash";
     read up to 40 filings a run (cached); one record per target in `state/merger.json`.
   - A target is named only by filings about it (proxy, 14D9, tender offer), never by an 8-K alone, since acquirers
     file 8-Ks too. The price must agree in two filings. Skipped: stock or election consideration in the
     consideration clause, a 14D9 whose board recommends rejecting, no merger agreement, no stated close date (a
     tender offer's expiry + 30 days counts), not on T212.
   - Entry: live spread 2–15%, close within 12 months, annualised ≥ 8%; 2% of the book; at most 3 open deals.
   - Exits: a target 8-K with item 1.02 and no 2.01 (`why: deal_terminated`), -10% (broker stop), or the cash-out:
     shares gone from the account for a day are recorded as sold at the offer, marked `estimated`.
   - Interim review at 10 deals is information only; the kill rule after 30 trades still applies.

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

# Always-on demo market agent (agent-1.18)

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
   - A "price too far" refusal (agent-1.16; T212 only accepts stops within a band around the price, which a wide
     rule stop such as value_timing's -50% falls outside) is retried at 30%, 20%, 15%, then 10% below the current
     price, never below the rule stop, and the first accepted price is kept (`clamped_from` in `stops.json`).
     The clamped stop can exit earlier in a fall than the rule would; it never exits later. One ladder per trade.
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
11. **vol_squeeze** (agent-1.8, decision C9, owner 30 Oct 11:35Z, `swing.py`, spec
   `research/strategies/C9_SQUEEZE_AND_GAP.md`): on the watchlist, from two years of Yahoo daily bars read in the
   review pass. Signal on the last finished session: 20-day Bollinger bandwidth (4 SD / mean) on the previous close in
   the lowest 10% of 250 days, a close above the prior 20-day high on ≥ 1.5x 20-day volume, above the 200-day average,
   price > $10 and 20-day dollar volume > $50m. Bought in the next session unless already > 3% above the trigger
   close; tightest squeeze first. Stop at the 20-day low or -8% (the tighter; held at the broker, so it acts
   intraday rather than on the close), trailing exit at the 10-day low once the trade has been up 10%
   (`why: trailing`), 28 calendar days (20 trading days).
12. **gap_go** (agent-1.8, C9): once per name per day, 30–60 minutes after its US open, a name up at least 0.6% has
   its 1-minute bars read. It qualifies with a 3–12% opening gap, ≥ 20% of the gap still held, and a price above the
   open and the first-30-minute VWAP. Buy at market; stop at the first-30-minute low (broker stop), +6% target, sold
   15 minutes before the close or at the first run of a later day (`why: flat_by_close`); at most 2 a day. A window
   the agent slept through is logged as `gap_go_missed` and never traded late. Catalysts are not checked.
13. **value_timing** (agent-1.9, research loop Q48a, passed its pre-registered test 30 Oct 2026,
   `research/always-on/results/Q44_Q48.md`, `value_timing.py`): after each US month end (the month's last weekday,
   read after 21:00 UTC), the 12-month total return of Russell 1000 Value (IWD) is compared with Russell 1000 Growth
   (IWF) from Yahoo adjusted closes. Value ahead: hold Vanguard Russell 1000 US Value (`VRVAl_EQ`, USD); otherwise the
   S&P 500 (`VUSAl_EQ`, GBP). One 2% position; a new month-end target exits the held ETF (`why: switch`) and buys the
   other. Only a -50% disaster stop at the broker (the tested rule has none). Switched off after 30 closed trades or
   730 days from its first entry, whichever comes first, if its compounded return has not beaten VWRP's
   (`why: killed`). The edge has been much smaller since 2007 (+1.3%/yr).
   Low confidence: the same rule outside the US is weak (Q49-Q52: t 1.74 developed ex-US, t 1.56 EM).
14. **momentum_timing** (agent-1.10, research loop Q50a, `results/Q49_Q52.md`; same code as value_timing, config
   `active.timing`): month-end MTUM (MSCI USA Momentum) vs IWB (Russell 1000) 12-month total return; momentum ahead:
   hold iShares Edge MSCI USA Momentum Factor (`IUMOl_EQ`, USD), else Vanguard S&P 500 Acc (`VUAGl_EQ`, GBP, a
   different line from value_timing's VUSA so the two never share a position). Same 2% size, -50% disaster stop and
   kill rule. Deliberate approximation: the test compared the winners decile with the losers decile, which has no
   ETF. Low confidence: the exact traded signal (Q55a) has earned +0.2%/yr since 2007 and fails outside the US
   (t 0.64); it runs as a cheap forward test.
15. **january_small** (agent-1.11, research loop Q65a, `results/Q61_Q65.md`; a calendar entry in `active.timing`):
   holds Vanguard Russell 2000 US Small-Cap (`VRSGl_EQ`, GBP) from the first LSE open of January to the first open of
   February (`why: switch`), nothing otherwise. Same 2% size, -50% disaster stop and kill rule (the 730 days binds
   first). Low confidence: the classic January effect, +3.0%/yr 1926-2022 (t 5.07) but -0.8%/yr since 2007.
16. **stock_screen** (agent-1.12, research loop Q199, `results/Q199.md`, `stock_screen.py`, `active.stock_screen`):
   a basket of individual US stocks from the system-designed screener, 2% of the book each, held with no stop,
   take-profit or time stop. Monthly 1/12 refresh (agent-1.15, research Q214, from the 30 Nov 2026 US close; the
   yearly January rebalance is retired, since Q214 found its result partly luck in the rebalance month). Run weekly
   since agent-1.16.2 (6 Nov, results season): as soon as each research data rebuild finishes (weekly, Mondays 05:41Z; owner 6 Nov:
   do it now, never wait for a set time; skipped if prices_monthly was not modified that day or the month has
   no monthly_metrics rows), the current month's `pick1.py live` scoring goes through
   `python3 -m market_agent screen-refresh out.csv --month YYYY-MM`. At most ONE scheduled swap per calendar month
   (recorded with `--record` in `state/screen_refresh.json`), so turnover stays at the tested 1/12: later Mondays
   that month return `log_only`, except an extra swap for a held name gone from the gated list. The refresh skips when every held
   name is in the top 15, else names one sale (oldest entry; ties: lowest score, or a name gone from the gated list)
   and the best-scored name not held (max 3 per SIC2), plus a refill for any hard-event sale. After the ±10pt sector
   check, `picks` is edited to match; the sold name exits with `why: rebalance`, and each sale is one closed trade
   scored against VWRP. About 12 swaps a year, the same turnover as the yearly rebalance. Kill after 30 closed
   trades or 730 days if it has not beaten VWRP. When cash above the sleeve's 10% reserve cannot cover the next buy,
   one VWRP sale a day frees the remaining spend (`screen_fund`), and the core buy leaves that cash alone. Its P&L is
   kept out of the sleeve's daily loss stop and freeze. Low confidence: the pre-registered backtest failed (+3.4%/yr
   vs its universe, t 0.85). First picks (October 2026 data): 15 names, all on T212; 9 are consumer discretionary,
   which at 2% each is about +13pt active vs VWRP look-through (UNVERIFIED: FTSE All-World discretionary taken as
   about 10-13%), over the +-10pt sector limit, so the three lowest-scored (CROX, COLM, CALY) are left out: 12
   names, about +8pt.
   Continuous watch (agent-1.12.3, owner 3 Nov "on all of the time"; rules from research Q200/Q201, where interim
   selling on ranks, gate breaks or a 25% crash guard all did worse than holding): every 15 minutes the agent reads
   each held name's SEC submissions. It SELLS on an 8-K with item 1.03 (bankruptcy), 3.01 (delisting notice), 4.01
   (auditor change) or 4.02 (non-reliance), or a delisting (25, 25-NSE, 15-12B/G), merger (DEFM14A, PREM14A) or
   tender (SC TO-T, SC 14D9) filing, and holds the cash until the next refresh. It only LOGS, with no alert or brief line (`stock_screen_alert` events, event log only)
   on any other 8-K, a new 10-Q or 10-K (the gates still need re-checking by hand), a 25% fall from entry, or no
   quote while the market is open (a possible halt). Orders use 3 decimals (T212 refused 4 on CARG and HRMY); any
   other precision refusal is learned per line in `state/precision.json`.

Every other pass is recorded as a `decision` with `no_trade: true` and its reasons.

17. **gap_rebound** (agent-1.13, research loop Q205 from the Q203 control group, `gap_rebound.py`,
    `active.gap_rebound`): a live-only forward test of single-stock mispricing; edge "unproven, forward test only".
    Every 30 minutes on weekdays, for each recent earnings day (Nasdaq calendar) whose day +1 close is in, it measures
    each Trading 212-listed US stock (market cap >= $300m) over days -1..+1 against SPY. A liquid (20-day median
    dollar volume >= $10m) fall of 10% or more is checked against SEC companyfacts filed before day 0: weak = TTM
    free cash flow <= 0 or TTM revenue down y/y (missing data is UNVERIFIED, no trade). A weak name is bought at 2%
    in the last 90 minutes of New York trading on day +2 and sold by its time stop 60 trading days later; no stop or
    take-profit; at most 8 open; kill after 30 closed trades or 730 days if it has not beaten VWRP. Every liquid
    drop (bought or not) is appended to `research/always-on/forward/Q205.csv`; state in `state/gap_rebound.json`.

18. **buyback_value** (agent-1.14, research loop Q206, `buyback_value.py`, `active.buyback_value`): edge "unproven"
    (+3.0%/yr vs universe 2015-22, DSR 0.02 after Q207 rebuilt it from real monthly holdings). The research loop writes each month-end's point-in-time picks to
    `research/always-on/forward/Q206_picks_YYYY-MM.csv` (columns symbol, sic, rank, fcf_ev, ...; best FCF/EV first).
    The agent buys the newest list (ignored once 45 days past its month-end) at 2% each, at most 10 open and 2 per SIC
    two-digit group, funded by selling VWRP like stock_screen, and sells each by its 182-day time stop; no stop-loss;
    P&L kept out of the sleeve's loss stop; kill after 30 closed trades or 730 days if it has not beaten VWRP.

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

## agent-1.17: gap_rebound VIX tag (research Q218b, 6 Nov 2026)

Every gap_rebound signal records the VIX close on its day 0 (Yahoo ^VIX, the same quote source; the last close before
it if that day has none) and a tag: `vix_hi` at 25 or above, `vix_lo` below, `vix_unknown` with no VIX. A vix_hi trade
carries the edge line "gap-down rebound in high fear (VIX>=25): unproven, Q218b +4.5%/trade 2010-22, DSR 0.02"
(`edge_vix_hi`). Rules, 2% sizing, the go-live rule and the 30-trade kill test are unchanged: the tag only labels
trades. `strategy_scores` reports each tag's trades apart under `variants`, and the kill rule still counts the whole
strategy. Signals recorded before 1.17 are tagged on the next scan.

## agent-1.18: momentum OFF-switch (research Q219, 6 Nov 2026, unproven)

No new breakout_momentum, momentum_timing or vol_squeeze entries while SPY's last close is below the average of its
last 10 month-end closes, or VIX last closed at 25 or more (`active.momentum_off`). In 2011-22 momentum lost about
0.8% a month in those conditions (the Daniel-Moskowitz crash pattern); the overall Q219 test failed, so this is an
unproven demo switch. Open trades keep their normal exits. Each blocked entry is logged once a day per name as a
`momentum_blocked` event with the reason "momentum off-switch: SPY<10m MA or VIX>=25 (Q219, unproven)" and the SPY,
MA and VIX readings, so the scoreboard can show what the switch avoided. Missing SPY or VIX history blocks the
entry (UNVERIFIED). Readings refresh hourly.

## agent-1.19 / 1.19.1: exit review (6 Nov 2026)

Owner, 14:39Z: "at what point would this system sell a stock? ... there should be a conscious thing for this".
Every open trade now gets a recorded hold-or-sell decision. An `exit_review` event fires once a day per trade and again
whenever its verdict changes. It carries the verdict, `held_because` (the strategy's tested hold rule) and `sells_if`
(stop, broker stop, time exit date, and any other rule that is live). The current table is in
`state/exit_review.json` under `plans`. Every sale already logs its reason in the order intent.

Three extra sell rules were built and tested the same day:
- **Buyback thesis check:** sell when the SEC share count rises year on year.
- **Profit lock:** after a gain of 25% or more, sell once half of the best gain is given back.
- **SEC hard events for buyback and gap names.**

Research Q221 (N=436-439) failed both the thesis check and the profit lock. Each did worse than the plain tested hold:
- thesis check on buyback: -0.54%/trade, t -4.45;
- profit lock on buyback: -0.12%, t -2.20;
- profit lock on gap_rebound: -0.08%;
- profit lock on pick-1: -1.25%.

The hard-event extension has no supporting test, and the closest one (Q201) was negative. agent-1.19.1 therefore
switches all three off in config, with the code kept so each can be switched back on. The decision for each position
is its tested hold, plus the broker-held stop and the strategy's kill rule.

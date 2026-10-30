# Go-live rule for real ISA money (pre-registered 30 Oct 2026)

Written before any demo strategy has closed a trade (scoreboard on 30 Oct 2026 11:45Z: 3 open
breakout_momentum trades, 0 closed). It must not be loosened after results come in. Tightening is
allowed. Any change gets a new dated section below, never an edit of this one.

The owner said (30 Oct 2026 11:46Z, cmsg_01U4KMvkBYNknqm4HRVie8uv3QrJXjnhm6aX1UytynxsrE):
"there will be no taxes as this will all be in an ISA ... we will go live after you confirm".
So: Claude checks this rule every day, and when a strategy passes, Claude tells the owner and
hands over a readiness report. **The owner places the real ISA orders.** Claude never places,
queues or automates real or ISA orders; that hard limit is unchanged.

## 1. What counts

- One **strategy tag** on the demo active sleeve (today: breakout_momentum, social_trend,
  merger_arb, vol_squeeze, gap_go, attention_spike). Each tag is judged on its own trades.
- A **trade** is one entry and its exit. The measure per trade is its **excess return**: the
  trade's net return after all Trading 212 costs (FX fee 0.15% each way, the spread inside the fill)
  minus VWRP's return over exactly the same days. No tax (ISA).
- The rules of a tag must stay as registered. A material rule change (entry, exit, size, universe)
  starts a new tag with a count of zero. The old tag stays in the count of strategies tested.
- Source of truth is the market agent's journal and broker fills, computed by
  `scoreboard.py` into `SCOREBOARD.json` (field `go_live_eligible`).

## 2. The proof a strategy needs (all six)

1. **At least 30 closed trades.**
2. **At least 91 days (3 months)** between its first demo trade and today.
3. **Mean excess return per trade above zero.**
4. **Statistically clear of luck, adjusted for multiple testing:** the one-sided t-statistic of the
   per-trade excess must reach the critical value at 5% / k, where k is the number of strategy
   tags ever run on the demo, killed ones included (Bonferroni). With k = 6 and 30 trades that is
   t of about 2.54. In plain terms: if trades swing by 6% either way, the average trade must beat
   VWRP by about 2.8%.
5. **Both halves positive:** the mean excess of the first half and the second half of its closed
   trades are each above zero, so one lucky burst cannot carry it.
6. **More pounds than VWRP:** the summed £ result of its closed trades beats what the same money
   would have made in VWRP over the same days.

Also required before the report goes to the owner (Claude checks these by hand):
- every instrument it trades is ISA-eligible on Trading 212, it is long-only (no shorting, no CFDs),
  and it fits inside the £20,000 yearly ISA allowance;
- no unresolved incidents in `market-agent/INCIDENTS.md` that touch its trades;
- the research-side record for the idea (if one exists) is not a fail.

The 30-trade kill rule still runs alongside: after 30 closed trades with mean excess at or below
zero, the tag is switched off on the demo.

## 3. The first real step (small)

- **Sleeve size:** the smaller of **5% of the ISA's value or £500**, for that strategy alone.
  Everything else stays in VWRP. Per trade: the same 2% of the ISA as on the demo, but never more
  than the sleeve.
- **Who trades:** the owner, by hand or with a Trading 212 feature they choose. Claude sends the
  signals and the scoreboard; it does not touch the real account.
- **Probation:** the demo version keeps running in parallel. The real sleeve is judged on its own
  trades against VWRP, with the demo as the check that real fills match demo fills.
- **Stop:** close the real sleeve if its loss reaches 15% of the sleeve, or if after 15 real
  trades the mean excess is below zero, or if the demo version gets killed.
- **Scale up:** only after another 30 real trades that again meet checks 3, 5 and 6, up to the
  owner's existing ceiling of at most 20% of the ISA outside VWRP and at most 5% in any company.

## 4. What to expect

Most short-term strategies fail this rule; that is its job. The research so far: 0 of 15 Stage 2
signals, B5 failed, 0 of 94 regime variants. A strategy that passes is rare, and even then the first
real step is deliberately small.

## Amendment 1 (30 Oct 2026 12:00Z, tightening only)

The office thread confirmed the live trading tags: drop_rebound, breakout_momentum, social_trend,
merger_arb, vol_squeeze, gap_go. drop_rebound is added to the count. attention_spike is logged
forward only and never trades, but stays in the count (more conservative). k is now 7, so with 30
trades the t-statistic needed is about 2.61.

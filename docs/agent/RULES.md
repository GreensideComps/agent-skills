# What the demo agent buys and sells, and why

Generated from `agent/market_agent/config.json` (agent-1.25.1) by `python3 -m market_agent rules`. Do not edit by hand: change the config or `rules.py`, then run `python3 -m market_agent rules --write docs/agent/RULES.md`. The tests fail if this page is out of date.

Demo account only. No strategy here has passed the go-live rule; each is a small forward test.

## The book

- Core: everything not in a strategy is held in VWRP. Spare cash above £20 is put into VWRP.
- Listed exits: INTC, BE, TEM, IBTA are sold in full whenever held.
- Single-name cap: 5% of the book (VWRP exempt).
- Order limits: at most £600 an order, 60 orders and £3000 of trading a day. Buys only from the approved list of 65 tickers.
- Short-term sleeve brakes: no new short-term buys for the day after a loss of 3% of the book in one day; frozen for good if the sleeve loses 25% of its £239 start.
- Cash kept back: 10% of the book while short-term strategies are on.
- Self-check: on every broker pass the agent tests nine promises about the whole book (every holding that needs a stop has one resting at the broker, nothing is held without a rule that will sell it, no overdue exits, no unknown orders or positions, no oversized or unpriced holdings) and raises an alert when one stays broken. `python3 -m market_agent audit` prints the latest result.

## Strategies at a glance

| Strategy | Status | Size | Evidence |
|---|---|---|---|
| drop_rebound | new buys paused since 7 Nov 2026 (research Q223: the closest backtest lost money); the pause itself is held in state/strategies.json, open trades keep their exits | 2% of the book per trade | no tested edge: a cheap forward test under the kill rule |
| breakout_momentum | on | 2% of the book per trade | no tested edge: a cheap forward test under the kill rule |
| social_trend | on | 2% of the book per trade | tested and failed overall (Q226); trades only in the one condition that held up, unproven |
| merger_arb | on | 2% per deal, at most 3 deals | a known premium for deal risk, not tested here: forward test |
| vol_squeeze | on | 2% of the book per trade | no tested edge: forward test under the kill rule |
| gap_go | on | 2% of the book per trade | no tested edge: forward test under the kill rule |
| value_timing | on | 2% of the book | passed its long-history test (1920s to 2022) but weak since 2007 and outside the US: low confidence |
| momentum_timing | on | 2% of the book | passed its long-history test (1920s to 2022) but weak since 2007 and outside the US: low confidence |
| january_small | on | 2% of the book | passed its long-history test but has lost money since 2007: low confidence |
| quality_tilt | on | 2% of the book | gate-v3 pass (Q246: +1.16% a year vs the US market 1963-2022, confirmed 2000-22 at +1.52% a year), but a published idea: forward test |
| stock_screen | on | 2% per name, 12 names now | tested and failed (Q199, +3.4% a year, not significant): a low-confidence forward test |
| buyback_value | on | 2% per name, at most 10 names | tested, positive but not significant (Q206, +3.0% a year): unproven forward test |
| gap_rebound | on | 2% per name, at most 8 names | not a registered test result (Q205 idea; Q218b high-fear version +4.5% a trade): unproven |
| news_shock_vix_hi | on | 2% per name, at most 10 names | tested and failed the go-live bar (Q222; most of the gain came from 2020): unproven |

## drop_rebound

Status: new buys paused since 7 Nov 2026 (research Q223: the closest backtest lost money); the pause itself is held in state/strategies.json, open trades keep their exits. Size: 2% of the book per trade.

Buys when:

- a watchlist stock (15 large US names) is down 5% or more on the day
- the multi-horizon price review must score at least +0.25, and there must be no earnings report within 3 days

Sells when (whichever comes first):

- stop: a stop resting at the broker 8% below the buy price
- target: sold once it is 6% above the buy price
- time limit: sold after 10 days whatever the price
- review: sold if the multi-horizon price review falls to -0.35 or lower
- kill rule: after 30 closed trades, if it has not beaten VWRP it is switched off and everything it holds is sold

## breakout_momentum

Status: on. Size: 2% of the book per trade.

Buys when:

- a watchlist stock (15 large US names) is up 5% or more on the day
- the multi-horizon price review must score at least +0.25, and there must be no earnings report within 3 days
- no new buys while the S&P 500 (SPY) is below its 10-month average or the VIX last closed at 25 or more (open trades keep their exits)

Sells when (whichever comes first):

- stop: a stop resting at the broker 5% below the buy price
- target: sold once it is 10% above the buy price
- time limit: sold after 5 days whatever the price
- review: sold if the multi-horizon price review falls to -0.35 or lower
- kill rule: after 30 closed trades, if it has not beaten VWRP it is switched off and everything it holds is sold

## social_trend

Status: on. Size: 2% of the book per trade.

Buys when:

- one of 32 US consumer brands: the 28-day average of its Wikipedia page views is at least 3 standard deviations above its 52-week norm and still rising
- the stock is not already up more than 15% in 20 trading days
- the VIX closed at 25 or more on the signal day
- bought at the next US session

Sells when (whichever comes first):

- stop: a stop resting at the broker 12% below the buy price
- target: sold once it is 25% above the buy price
- time limit: sold after 84 days whatever the price
- attention faded: sold once page views are back within 1 standard deviation of normal
- kill rule: after 30 closed trades, if it has not beaten VWRP it is switched off and everything it holds is sold

## merger_arb

Status: on. Size: 2% per deal, at most 3 deals.

Buys when:

- an agreed all-cash takeover found in SEC filings, with the price confirmed in two filings, not hostile
- the stock trades 2% to 15% below the offer, the deal is due to close within 12 months, and the gap is worth at least 8% a year

Sells when (whichever comes first):

- deal closes: the shares are paid out in cash
- deal terminated: sold when an SEC filing says so
- stop: a stop resting at the broker 10% below the buy price
- kill rule: after 30 closed trades, if it has not beaten VWRP it is switched off and everything it holds is sold

## vol_squeeze

Status: on. Size: 2% of the book per trade.

Buys when:

- a watchlist stock whose 20-day trading range has been in its narrowest 10% of the last 250 days closes above its 20-day high on at least 1.5x normal volume
- bought the next session unless it has already run more than 3% further
- no new buys while the S&P 500 (SPY) is below its 10-month average or the VIX last closed at 25 or more (open trades keep their exits)

Sells when (whichever comes first):

- stop: a stop resting at the broker 8% below the buy price
- time limit: sold after 28 days whatever the price
- trailing exit: once it has been up 10%, sold if it falls below the lowest price of the last 10 days
- kill rule: after 30 closed trades, if it has not beaten VWRP it is switched off and everything it holds is sold

## gap_go

Status: on. Size: 2% of the book per trade.

Buys when:

- a watchlist stock opens 3% to 12% higher and, 30 to 60 minutes after the US open, still holds at least 20% of the jump and is above its open and its average price so far
- at most 2 a day

Sells when (whichever comes first):

- stop: a stop resting at the broker at the low of the first 30 minutes
- target: sold once it is 6% above the buy price
- end of day: sold 15 minutes before the US close, never held overnight
- kill rule: after 30 closed trades, if it has not beaten VWRP it is switched off and everything it holds is sold

## value_timing

Status: on. Size: 2% of the book.

Buys when:

- at each month end, hold VRVA when IWD's 12-month return beats IWF's, otherwise hold VUSA

Sells when (whichever comes first):

- switch: sold when the month-end signal names the other fund
- crash stop: a stop resting at the broker 50% below the buy price (a safety net, not a tested rule)
- kill rule: after 30 closed trades or 24 months from its first buy, whichever is first, if it has not beaten VWRP it is switched off and everything it holds is sold

## momentum_timing

Status: on. Size: 2% of the book.

Buys when:

- at each month end, hold IUMO when MTUM's 12-month return beats IWB's, otherwise hold VUAG
- no new buys while the S&P 500 (SPY) is below its 10-month average or the VIX last closed at 25 or more (open trades keep their exits)

Sells when (whichever comes first):

- switch: sold when the month-end signal names the other fund
- crash stop: a stop resting at the broker 50% below the buy price (a safety net, not a tested rule)
- kill rule: after 30 closed trades or 24 months from its first buy, whichever is first, if it has not beaten VWRP it is switched off and everything it holds is sold

## january_small

Status: on. Size: 2% of the book.

Buys when:

- calendar: hold US small caps (Vanguard Russell 2000, VRSG) from the first LSE open of January to the first open of February; no position otherwise

Sells when (whichever comes first):

- calendar: sold at the first London open after the holding month ends
- crash stop: a stop resting at the broker 50% below the buy price (a safety net, not a tested rule)
- kill rule: after 30 closed trades or 24 months from its first buy, whichever is first, if it has not beaten VWRP it is switched off and everything it holds is sold

## quality_tilt

Status: on. Size: 2% of the book.

Buys when:

- always: hold US quality (iShares Edge MSCI USA Quality Factor, IUQA) as one fixed 2% line; gate-v3 pass, forward test

Sells when (whichever comes first):

- no signal exit: held continuously until the review the kill rule sets
- crash stop: a stop resting at the broker 50% below the buy price (a safety net, not a tested rule)
- kill rule: after 30 closed trades or 24 months from its first buy, whichever is first, if it has not beaten VWRP it is switched off and everything it holds is sold

## stock_screen

Status: on. Size: 2% per name, 12 names now.

Buys when:

- the top 15 US stocks by a combined score (gross profitability, free-cash-flow yield, momentum, low debt, buybacks), skipping any that would break the sector limit or put more than 3 names in one industry group
- a new name is bought only to replace one that was sold

Sells when (whichever comes first):

- 12-month review: once a name has been held 12 months it is replaced by the best name not held, at most one replacement a month, unless it is still in the top list, in which case it is kept and its 12 months start again (the tested rule; selling a name the screen would still pick was a drift from it)
- a name that merely drops out of the top list is NOT sold early (that rule tested worse than holding and is off)
- SEC hard event: sold at once on a bankruptcy, delisting, auditor change, restatement, merger or tender filing
- safety-net stop: a stop resting at the broker 30% below the buy price; if the broker refuses or loses it, the agent sells at the same level itself and keeps trying to put the stop back (unproven: tighter stops tested worse than holding)
- monthly reset from 2026-12: each name is trimmed or topped up to an equal share (unproven)
- kill rule: after 30 closed trades or 24 months from its first buy, whichever is first, if it has not beaten VWRP it is switched off and everything it holds is sold

## buyback_value

Status: on. Size: 2% per name, at most 10 names.

Buys when:

- a monthly screen of US companies worth $2bn or more (no banks or utilities): among the heaviest buyers of their own shares, share count falling, positive free cash flow, modest debt, and cheap on free cash flow
- cheapest first, at most 2 per industry group

Sells when (whichever comes first):

- time limit: sold after 9 months (6 months for trades opened before 9 Nov 2026)
- safety-net stop: a stop resting at the broker 30% below the buy price; if the broker refuses or loses it, the agent sells at the same level itself and keeps trying to put the stop back (unproven: tighter stops tested worse than holding)
- kill rule: after 30 closed trades or 24 months from its first buy, whichever is first, if it has not beaten VWRP it is switched off and everything it holds is sold

## gap_rebound

Status: on. Size: 2% per name, at most 8 names.

Buys when:

- a liquid US stock worth $2bn or more falls 10% or more against the market around its earnings report, and its business looks weak (no free cash flow or falling sales)
- bought near the close two days after the report

Sells when (whichever comes first):

- time limit: sold after 60 trading days
- safety-net stop: a stop resting at the broker 30% below the buy price; if the broker refuses or loses it, the agent sells at the same level itself and keeps trying to put the stop back (unproven: tighter stops tested worse than holding)
- kill rule: after 30 closed trades or 24 months from its first buy, whichever is first, if it has not beaten VWRP it is switched off and everything it holds is sold

## news_shock_vix_hi

Status: on. Size: 2% per name, at most 10 names.

Buys when:

- only when the VIX closed at 25 or more: a liquid US stock worth $2bn or more falls 8% or more against the market over two days after a company announcement that is not an earnings report
- bought near the close of the following day; not again in the same name within 10 sessions

Sells when (whichever comes first):

- time limit: sold after 5 trading days
- safety-net stop: a stop resting at the broker 30% below the buy price; if the broker refuses or loses it, the agent sells at the same level itself and keeps trying to put the stop back (unproven: tighter stops tested worse than holding)
- kill rule: after 30 closed trades or 24 months from its first buy, whichever is first, if it has not beaten VWRP it is switched off and everything it holds is sold

# Demo strategy review (11 Nov 2026, second-pass audit)

Inputs: the hosted agent's event log 26 Oct to 11 Nov (mirror at 19:32Z), the scoreboard (38 trades, 5 closed), the
config of agent-1.23, the research registry. Demo account only. Nothing here re-judges a research result.

## Verdict in one line

Cut nothing on results: five closed trades say nothing about any strategy. The problem the log does show is that
several strategies were not running as designed, because their data was missing. agent-1.24 fixes that.

## What the log showed, by strategy

| Strategy | Evidence before the demo | Trades so far (closed / open) | Running as designed? | Change |
|---|---|---|---|---|
| merger_arb | strongest outside evidence of the set (published merger-arbitrage premium); no own backtest | 0 / 0 | **No.** 61 deals read, 10 eligible on 11 Nov (DV, LNTH, MG, OGN, PCRX, PRTH, SAFT, SYNA, TBPH, TECH), every one refused for "no validated quote" (Tiingo budget). Two more were refused as "not tradeable" because their T212 tickers are old symbols | agent-1.24: Yahoo quotes; broker-symbol mapping |
| gap_go | none (forward-only, C9) | 0 / 0 | **No.** On 11 Nov every watch-list name had "no validated quote" at the 15:00Z check; 285 "missed" events were false (restarts re-logging checked names) | agent-1.24: Yahoo quotes; checked-today list kept in state |
| gap_rebound | Q205 idea, +5.0%/trade t 2.75 (not a registered result) | 0 / 8 | Partly: 27 runs failed on the Tiingo budget | Yahoo bars. Note: it buys weak-health names, so its backtest carries up to +1.7 pp/yr survivorship flattery (SURVIVORSHIP.md) |
| news_shock_vix_hi | Q222 benched, mostly 2020 | 0 / 1 | Partly: 29 runs failed on the Tiingo budget | Yahoo bars |
| buyback_value | Q206 +3.0%/yr, not significant | 0 / 10 | Yes | none |
| stock_screen | Q199 FAIL (t 0.85), low-confidence demo | 2 / 12 | Yes, but two held names (GPS = Gap, VSCO = Victoria's Secret) had no market price: their T212 tickers are old symbols | broker-symbol mapping |
| value_timing, momentum_timing, january_small | Ken French long-history tests | 0 / 2 | Yes (18 timing runs failed on the budget) | Yahoo bars |
| breakout_momentum, vol_squeeze | none (forward-only) | 3 / 0 | Yes | none |
| social_trend | none | 0 / 0 | Partly: prices for its universe failed on the budget | Yahoo quotes |
| attention_spike | none; logs only, never trades | - | Yes | none |
| drop_rebound | Q223 FAIL | paused since 7 Nov | - | stays paused |

The core VWRP buy also waited for days ("no validated VWRP.L price"): London lines had no source but the broker's own
price for held lines. Yahoo prices VWRP.L.

## How long until each strategy can be judged

The 30-trade kill rule and the go-live rule both need closed trades. At each strategy's own capacity:

| Strategy | Capacity | 30 closed trades by about |
|---|---|---|
| gap_rebound | 8 open, 60 trading days each | late 2027 |
| stock_screen | about 15 to 25 exits a year (12-month hold plus swaps) | mid 2028 |
| buyback_value | 10 open, 9-month hold | early 2029 |
| merger_arb | 3 open, deals close in 3 to 9 months | 2030 or later |
| news_shock_vix_hi | only on VIX >= 25 days | unknown (years in calm markets) |
| three timing strategies | one switch every few months | never inside their 730-day kill window |

So for most strategies the demo is an implementation check (does the agent trade the rule correctly and at what
real cost), not an edge test. Edges have to be judged from history under research gate v3, which is what the
research loop is for. Two consequences for the standing backlog:

1. The timing strategies cannot meet the 30-trade rule at all; their 730-day kill is their real test. That is already
   in config (`kill_after_days`). No change.
2. With 14 tags counted in the go-live Bonferroni, a strategy needs a one-sided t at 0.0036. That bar is only worth
   revisiting when some strategy actually approaches 30 closed trades (gap_rebound first, late 2027). Any loosening is
   a change to the real-money rule and goes to the owner as a proposal, not a decision taken here.

## Checks after agent-1.24 is deployed (office thread)

- `duty_failed` with BudgetError or HTTP 429 falls to near zero within a day.
- merger_arb places its first trade, or logs a reason other than "no validated quote".
- gap_go logs `gap_check` rows with a gap figure, not "no validated quote", and no false "missed" after restarts.
- `quote_state` shows VWRP.L, GPS_US_EQ (as GAP) and VSCO_US_EQ (as VSXY) valid.
- `state/yahoo_down.json` stays absent or short-lived. If Yahoo refuses GitHub Actions addresses, the old sources still
  run and the file shows it.

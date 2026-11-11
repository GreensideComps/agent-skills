# Q244 result: holding the screener's top 15 within the sector limit (11 Nov 2026)

Prereg: prereg/Q244.md (sha256 732c3e7e...). Code: research/stock_screener/q244_hold_top15.py. Raw: results/Q244.json. N = 484-486.
96 months, 2015-2022, survivor-biased panel (upper bound). d = variant minus the current live rule (R0), net of costs.

| Rule | vs current rule | t | Thirds (%/month) | Costs x2 | 1-month lag | Trades/yr | Empty slots (avg) | Verdict |
|---|---|---|---|---|---|---|---|---|
| b. Top 15 each month, sector cap, leftover slots in VWRP | +0.65%/yr | 0.34 | +0.05 / +0.04 / +0.07 | -0.04 | -0.21 | 48 | 1.8 | FAIL, no switch |
| c. MAIN (owner): keep until it leaves the top 15, buy only top 15 within the cap, else VWRP | +0.44%/yr | 0.25 | +0.13 / -0.14 / +0.12 | -0.04 | -0.24 | 42 | 1.8 | FAIL, no switch |
| d. As c, sell only below rank 30 | -1.24%/yr | -0.83 | +0.01 / -0.40 / +0.08 | -0.11 | -0.05 | 23 | 0.5 | FAIL |

Legs (net): current rule R0 6.9%/yr USD, -1.2%/yr vs EW universe, +1.4%/yr vs VWRP GBP, 19 trades/yr;
c 7.6%/yr, -0.8% vs EW, +1.8% vs VWRP. For reference the yearly plain hold (Q199) was +3.4%/yr vs EW.

Plain English: the owner's rule did slightly better than the current one (+0.4% a year), but that is noise.
It flips to a loss with double costs or a one-month delay, and it trades twice as often. Under the
pre-registered switch rule (t >= 1, robust to costs and delay), the current rule stays. The buffer version did worse.
All monthly-churn rules still trail a plain yearly hold (as Q233/Q243 found).
Caveat: sector cap approximated as max 6 of 15 names per broad sector (live uses +-10pt vs VWRP).

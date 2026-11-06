# Q199 pick-1 stock screener: FAIL in backtest, runs as a low-confidence demo forward test (3 Nov 2026)

The system's own screener (gates: positive FCF and operating income, net debt/EBITDA < 3, no dilution, positive
equity; rank: gross profit/assets + FCF/EV + 12-1 month momentum; top 15, max 3 per SIC2, yearly January
rebalance, US $2bn+, ex financials/utilities) beat the equal-weight universe by +3.4%/yr after costs over
2015-2022, but t was only 0.85 and DSR 0.0001 at N=418. Only the last third was positive (-4.3%, -0.1%, +14.6%),
a February rebalance kept just +0.1%/yr and a half-yearly rebalance lost 1.2%/yr, so the gain is fragile.
In GBP it compounded 14.8%/yr vs VWRP 10.1%/yr (+5.8%/yr, t 1.13), but most of that is the universe itself
(US-only, survivor-biased) beating VWRP, not stock selection. Large caps only: +3.6%/yr t 1.49 (the best view).
Gross edge (+3.9%/yr) is well above the cost drag (0.5%/yr), so yearly rebalancing is cheap enough.

Per the pre-registration, the screen still runs in the demo as a low-confidence forward test because the
owner asked for live individual picks: tag `stock_screen`, 2% per name, 15 names, kill after 30 closed trades
or 730 days if not beating VWRP. First picks from October 2026 data: picks_2026-11.csv.

```
Q199 pick-1 screener (exploration 2015-22, N=418, 1 trial)
vs EW universe: +3.43%/yr after costs, t 0.85, DSR 0.0001
vs VWRP (GBP, survivor-biased): 14.8% vs 10.1% CAGR, +5.8%/yr t 1.13
thirds -4.3/-0.1/+14.6%; bull +7.8 bear -5.8; costs x2 +2.9; lag1 +0.1; 6-monthly -1.2; large-only +3.6 (t 1.49)
verdict: FAIL (noise-level). Demo forward test anyway (prereg), tag stock_screen, 2%/name x15
```

# Other buy/sell timing rules: can dates or trends dodge the bad times?

Run 2 Nov 2026. Script `backtest.py`, table `results.txt` / `results.csv`.
Data: US total market incl. dividends (Ken French / CRSP, close to the S&P 500), monthly and daily, 1927-2022 main test; 2007-2022 recent check; 2023-Sep 2026 shown separately (partly seen holdout, not used for the verdict). Out of the market = 1-month T-bills. Cost 0.10% per trade. Signals only use data available before the trade.

## Verdict

**No rule reliably beats buying and holding.** The calendar rules give at most a small edge that is not statistically real and fades after 2007. The trend rules cut the worst crashes roughly in half, but they make about the same or less money, lose to buy and hold in most years, and have lagged badly since 2007 and again in 2023-26.

## Results, 1927-2022 (CAGR; buy and hold = 9.9%, worst fall -84%)

| Rule | CAGR | Gap | Worst fall | Years won | Gap 2007-22 | Gap 2023-26 |
|---|---|---|---|---|---|---|
| Skip September | 11.1% | +1.2 | -72% | 52% | +0.7 | +0.2 |
| Skip Sep and Oct | 11.0% | +1.2 | -66% | 44% | -0.2 | +0.9 |
| Skip Aug and Sep | 10.3% | +0.4 | -73% | 36% | +0.7 | -1.0 |
| Avoid worst month so far (rolling 30y, no hindsight) | 10.0% | +0.1 | -84% | 40% | +0.4 | +0.2 |
| Above 10-month average | 9.5% | -0.4 | -43% | 23% | -0.1 | -9.4 |
| 12-month momentum vs T-bills | 9.5% | -0.5 | -45% | 23% | -1.6 | -4.3 |
| Above 200-day average (daily) | 10.3%* | +0.9 | -34% | 27% | -2.0 | -7.2 |
| 50/200-day "golden cross" | 8.5%* | -0.9 | -62% | 21% | +0.1 | -7.1 |

*Daily rules compare with daily buy and hold of 9.4%.

## What this means

- **"Skip September" is the best-looking rule, but it is hindsight.** September looks worst because we are looking at this exact history. When the rule only uses past data to pick the month to avoid, the edge falls to +0.1% a year. Statistical strength t = 1.5 (2 or more needed), and 0.4 since 2007.
- **Trend rules are insurance, not profit.** They sat out most of 1929-32, 2000-02 and 2008, so the worst fall shrinks from -84% to about -35 to -45%. You pay for that in whipsaws, where you sell after a dip and buy back higher, and they lose to buy and hold in about 3 years out of 4. Since 2007, sharp V-shaped recoveries (2020, 2023, 2025) have made them lag.
- **Earlier project tests** of other date rules were all rejected: turn-of-month (Q38), the day before holidays (Q46), the day before Fed meetings (Q08), stocks' best calendar months (Q03), trend switching into gold (Q09/Q10), and trend plus rising unemployment (Q105). Sell in May / Nov-Jun was rejected twice.

## For a UK ISA holder with VWRP

Switching inside an ISA is tax-free, so a trend rule is possible. It only makes sense if a smaller crash matters more to you than the long-run return, and even then, holding a fixed slice of cash all year gives a similar trade-off without the timing risk. The recommendation stays: hold VWRP all year.

Trials: 8 rules added to the research count (N +8).

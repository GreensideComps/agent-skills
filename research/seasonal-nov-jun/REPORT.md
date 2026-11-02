# Buy the S&P 500 in November, sell in spring: does it work?

Run 2 Nov 2026. Script: `backtest.py`, full table: `results.txt` / `results.csv`.

## Verdict

**No. It does not beat simply holding the market.** Over almost 100 years of US data it earned about 1 to 1.5 points a year less than buy and hold, and it lost to buy and hold in roughly 6 or 7 years out of every 10. The winter months really are stronger than the summer months, but the summer months still beat cash on average, so stepping out costs you money.

## Set-up

- Market: US total market incl. dividends (Ken French / CRSP, close to the S&P 500), monthly, Jul 1926 to Sep 2026. Extended back to 1871 with Shiller's S&P composite (rougher: monthly average prices, 10-year Treasury yield as cash stand-in).
- Strategy: buy at the start of November, sell at the end of April, May or June (three versions), hold 1-month T-bills otherwise.
- Cost: 0.10% per trade (two trades a year), stress test at 0.25%.
- Benchmark: buy and hold the same market.
- "Win" = strategy beat buy and hold over a full November-to-October year.

## Main result, 1926-2022 (0.10% cost)

| Version | CAGR | Buy & hold CAGR | Max drawdown | B&H max drawdown | Years won |
|---|---|---|---|---|---|
| Nov-Apr | 8.4% | 9.9% | -57% | -84% | 33% |
| Nov-May | 8.4% | 9.9% | -71% | -84% | 37% |
| Nov-Jun | 8.9% | 9.9% | -71% | -84% | 44% |

$1 grew to about $3,800 with Nov-Jun versus $9,400 with buy and hold. At 0.25% cost the gap widens by about 0.3 points a year.

Other windows (Nov-Jun, 0.10% cost): 1871-2026 7.9% vs 9.3% (won 39% of years); 1993-2022 8.1% vs 9.7% (34%); 2007-2022 5.9% vs 8.7% (27%).

## By decade (Nov-Jun CAGR vs buy and hold)

1930s -1.4 vs -0.3 · 1940s 6.2 vs 9.5 · 1950s 16.0 vs 18.3 · 1960s 6.0 vs 8.3 · **1970s 9.1 vs 6.1** · **1980s 17.6 vs 16.9** · 1990s 17.4 vs 18.0 · **2000s 2.4 vs -0.4** · 2010s 9.3 vs 13.6 · 2020s (to Sep 2026) 11.1 vs 15.0.

It won only in three decades, all ones with big bear markets or high inflation.

## Why it fails

- Winter months averaged +1.23%/month and summer +0.64% (1926-2022), a real but modest gap (t = 1.9).
- But summer still beat cash (+0.27%/month), so sitting out gives up return.
- The lower drawdown is just from holding cash half the year. Risk-adjusted (Sharpe) it is a tie: 0.45 vs 0.43 since 1926, and worse since 2007 (0.44 vs 0.54).
- The effect has weakened since it became famous: since 2007 the winter-summer gap is not statistically meaningful (t = 0.8).

## 2023-2026

Project memory says 2023 onward is partly seen holdout, so it is reported separately and not used for the verdict. It agrees anyway: Nov-Jun 19.6% vs 21.6% a year, and the strategy lost both full November-to-October years.

## For a UK ISA holder using VWRP

Inside an ISA there is no tax on switching, so the only costs are spreads, plus holding cash for about four months each year. VWRP is global, not just the S&P 500, and an earlier project test (Q64, 30 Oct) found the same pattern in developed ex-US and emerging markets: 0 of 3 passed. Stay invested in VWRP all year. If you want less drawdown, holding a fixed share in cash all year gives the same risk trade-off without timing.

This is the second time the project has rejected this effect (first Q64, 30 Oct).

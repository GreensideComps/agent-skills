# Screen backtest (M8, test 1): does the screen-1.0 score predict 12-month returns?

Pre-registration: [`screen_backtest_prereg.md`](screen_backtest_prereg.md), committed before this ran.

**Verdict: FAIL** against the pre-registered condition (mean IC > 0 with t >= 2, and the ranked basket beats all scored companies in >= 60% of years).

- Mean IC +0.077, t = 1.92 over 14 years
- Ranked basket beat all scored companies in 79% of years
- Companies sampled 600, with at least one scored year 541, errors 9

| Year (Apr to Apr) | Scored | Ranked | IC | Ranked basket | All scored | Ranked minus all | Top minus bottom quintile | SPY |
|---|---|---|---|---|---|---|---|---|
| 2012 | 32 | 22 | -0.269 | +26.8% | +25.0% | +1.8% | +1.1% | +16.7% |
| 2013 | 61 | 44 | -0.080 | +22.3% | +25.2% | -2.9% | -8.8% | +20.3% |
| 2014 | 59 | 45 | +0.049 | +8.8% | +6.0% | +2.8% | +0.1% | +12.9% |
| 2015 | 61 | 49 | +0.120 | -0.0% | -0.6% | +0.6% | +3.9% | +1.1% |
| 2016 | 69 | 47 | +0.111 | +19.9% | +18.1% | +1.7% | +6.5% | +17.8% |
| 2017 | 68 | 55 | +0.316 | +15.0% | +13.1% | +1.9% | +22.1% | +13.2% |
| 2018 | 78 | 57 | +0.174 | +13.9% | +10.2% | +3.7% | +11.5% | +13.3% |
| 2019 | 85 | 57 | -0.005 | -15.1% | -17.1% | +2.0% | -3.6% | +0.8% |
| 2020 | 81 | 58 | +0.125 | +97.9% | +94.9% | +3.0% | +2.8% | +46.0% |
| 2021 | 85 | 53 | +0.118 | -6.1% | +5.4% | -11.4% | -15.9% | +0.0% |
| 2022 | 93 | 64 | +0.147 | +9.8% | +5.5% | +4.3% | -1.3% | +2.7% |
| 2023 | 77 | 53 | +0.109 | +27.5% | +25.5% | +2.0% | +12.5% | +22.4% |
| 2024 | 92 | 55 | +0.260 | -1.4% | -1.9% | +0.5% | +30.0% | +11.9% |
| 2025 | 96 | 61 | -0.094 | +42.4% | +44.7% | -2.3% | -4.0% | +31.1% |

Biases (stated in advance): survivorship (only companies listed today), small early cross-sections, no costs, unofficial prices. Read the verdict as evidence about ranking, not as a return forecast.

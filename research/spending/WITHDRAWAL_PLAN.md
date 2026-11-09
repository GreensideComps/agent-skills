# Spending money from the ISA: tested rule (9 Nov 2026)

Script: research/spending/withdrawal_rules.py (repo branch claude/project-thread-j3yti5). Numbers: withdrawal_results.json.
Planning study, not an edge trial (N unchanged). Data cut at 2022-12 (holdout untouched), free data only.
- World test: VWRP proxy (90% developed + 10% emerging, Ken French), in GBP, after 0.19% fee, 1991-2022. Proxy matched real VWRL/VWRP at corr 0.98 (Q228). 6.7%/yr after inflation over 1991-2022.
- Long-run stress test: Shiller S&P 500 total return 1872-2022 (151 years, includes 1929 and the 1966-82 inflation years). US only, so it flatters; used to check a rule survives the worst stretches.
- Inflation: US CPI (no UK CPI in the free data). All money figures below are after inflation, per 100 at the start.

## Rules tested (money taken once a year, in January)
| Rule | 20-yr world windows: avg take / yr | Lowest year | Pot after 20 yrs (median / worst) | 151-yr US, 30-yr windows: ran out | ended below start |
|---|---|---|---|---|---|
| Fixed 4% of start, raised with inflation ("4% rule") | 4.0 | 4.0 | 133 / **49** | **3%** | 18% |
| Fixed 5% + inflation | 5.0 | 5.0 | 94 / **2** | **19%** | 39% |
| 4% of current value each year | 4.2 | 2.0 | 121 / 103 | 0% | 8% |
| 3.5% of 3-year average value (endowment rule) | **3.8** | 1.9 | **137 / 115** | 0% | 2% |
| 4% of 3-year average value | 4.1 | 2.2 | 123 / 104 | 0% | 8% |
| Guardrails 4.5% (cut 10% / raise 10% at ±20% drift) | 4.2 | 2.4 | 117 / 94 | 0% | 13% |
| Take only gains above the real start +10% | 5.2 | **0** (nothing in ~12 of 20 years) | 121 / 95 | 0% | 15% (US) |

What the numbers say:
- A fixed amount (the classic 4% rule) feels safe but is the one that can empty the pot: started at a bad time, 4% ran out in 3% of 30-year US runs and 5% in 19%.
- "Take only the gains" sounds prudent but pays nothing most years, so it is not spending money you can plan around.
- Taking a percentage of the pot can never run it to zero. Averaging the last 3 years' values (what university endowments do) smooths it: the biggest one-year cut was about 20% (world) and 27% (US), against about 30-42% for a plain percentage.
- 3.5% of the 3-year average is the best balance of "grow" and "spend": over every 20-year world window from 1991 the pot still grew after inflation (worst +15%, median +37%) while paying about 3.8% a year. Across 151 years of US data it stayed above its starting real value in 98% of 30-year runs.

## The rule (advice; the owner places real orders)
Every January (first week):
1. Value the ISA. Spending for the year = 3.5% x the average of the last three January values (until there are three, use the values available).
2. Raise the cash in this order: (a) any conviction name above 5% of the ISA is trimmed back to 5% and that cash counts first; (b) the rest is sold from VWRP. Never sell VWRP below the core weight to protect a conviction name.
3. Withdraw it in one go, or keep it as ISA cash and withdraw monthly (1/12 each month). T212's ISA is flexible, so money taken out can be put back in the same tax year without using new allowance.
4. In a crash year the rule pays less automatically (the 3-year average falls slowly). Do not sell extra in a crash.
New money keeps going into VWRP only.

Worked example: an ISA worth 10,000 pays about 350 in year one (about 29 a month). If the ISA grows to 12,000 the next year, the 3-year average is 11,000 and the payout about 385.

## Caveats
- Past returns, not a promise. US data flatters; world data covers only 32 years and starts near a good decade.
- US CPI used for inflation. UK inflation was similar on average over 1991-2022 but not year by year.
- The 5% trim on conviction names is risk control, not an edge: earlier tests (Q221 profit lock, Q231-Q233) found selling winners usually cost return. It keeps one stock from becoming the whole plan.
- Single-stock risk in the satellite (AMZN, PLTR, SPCX) is not in the backtest; the backtest is the VWRP core.

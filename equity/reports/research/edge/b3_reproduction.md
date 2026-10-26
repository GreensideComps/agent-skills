# B3: Stage 2 reproduction through the new backtester

**Standing limitations (not solved by anything in this report):**

1. **Survivorship bias (material, unbounded).** Companies that stopped trading before the 2026 price download have no
   free prices, so they are missing from the universe entirely, even in the years they traded. The bias is of unknown
   size and is usually assumed to flatter results. The -30% and -100% missing-price rules apply only to companies
   that are in the data and later lose a price; **they do not address companies missing from the universe, and are
   not evidence that survivorship bias is bounded.** Accepted for exploration only (D13).
   *(Wording updated 2026-10-16 at the owner's request; results unchanged.)*
2. **Missing prices are indistinguishable.** Delistings, acquisitions and ticker changes all get the same
   conservative mark-down.
3. **The 2023-2026 holdout is partly seen**, so a holdout pass is weaker than a clean out-of-sample test.
4. **One ticker per company, today's SIC codes, unofficial free prices (Yahoo).**
5. **Benchmark:** actual VWRP only from 2019-08 (first full monthly return; first price 25 July 2019); VWRL (its distributing twin) before that.

Run 2026-10-15T15:02:26+00:00. Specification frozen before the run: `docs/edge/B3_STAGE2_SPEC.md` (commit 223e826). Data cut at 2022-12-31 on read; no holdout price, signal or outcome was read.

## Result: reproduction **FAILS** the 1e-6 tolerance: 3 of 15 trials pass both comparisons (cause and detail under Investigation below)

### A. Original Stage 2 code on cut data vs the published result (top quintile, large caps, net, a year)

| Trial | Published | Rerun | Difference | All 6 fields within 1e-6 |
|---|---:|---:|---:|---|
| S1a | -1.156795% | -1.156795% | -1.73e-18 | yes |
| S1b | -0.835093% | -0.835093% | -1.04e-17 | yes |
| S2a | -0.921373% | -0.921373% | -1.04e-17 | yes |
| S2b | -1.119965% | -1.119965% | -5.20e-18 | yes |
| S3a | -2.676980% | -2.676980% | +1.39e-17 | yes |
| S3b | -1.152385% | -1.152385% | -1.73e-18 | yes |
| S4 | -5.203437% | -5.203437% | +0.00e+00 | yes |
| S5a | +0.668551% | +0.668551% | +0.00e+00 | yes |
| S5b | -1.744061% | -1.744061% | +1.04e-17 | yes |
| S6a | -0.919217% | -0.919217% | +1.73e-18 | yes |
| S6b | -1.552602% | -1.552602% | +1.73e-18 | yes |
| S6c | -3.901997% | -3.901997% | -6.94e-18 | yes |
| S7a | -0.919180% | -0.919180% | -6.94e-18 | yes |
| S7b | -0.953338% | -0.953338% | -5.20e-18 | yes |
| S9 | -2.521098% | -2.521098% | -1.39e-17 | yes |

### B. New engine vs original code, same assumptions

| Trial | Months | Stage 2 net, a year | Engine net, a year | Difference | Largest monthly difference | Months over 1e-6 | Largest difference in all other months | Holdings differ in | Pass |
|---|---:|---:|---:|---:|---:|---|---:|---|---|
| S1a | 95 | -1.156795% | -1.157493% | -6.97e-06 | 4.48e-04 | 2022-07, 2022-08, 2022-10, 2022-11 | 4.0e-16 | none | NO |
| S1b | 95 | -0.835093% | -0.835665% | -5.72e-06 | 5.07e-04 | 2022-07, 2022-08, 2022-10, 2022-11 | 2.9e-16 | none | NO |
| S2a | 95 | -0.921373% | -0.922141% | -7.68e-06 | 6.06e-04 | 2022-07, 2022-08, 2022-10, 2022-11 | 4.6e-16 | none | NO |
| S2b | 95 | -1.119965% | -1.120630% | -6.65e-06 | 4.56e-04 | 2022-07, 2022-08, 2022-10, 2022-11 | 4.0e-16 | none | NO |
| S3a | 95 | -2.676980% | -2.678983% | -2.00e-05 | 8.47e-03 | 2022-07, 2022-08, 2022-10, 2022-11 | 4.6e-16 | 2022-07, 2022-08, 2022-10, 2022-11 | NO |
| S3b | 95 | -1.152385% | -1.172900% | -2.05e-04 | 6.79e-03 | 2022-07, 2022-08, 2022-10, 2022-11 | 3.9e-16 | 2022-07 | NO |
| S4 | 93 | -5.203437% | -5.203437% | +0.00e+00 | 3.40e-16 | none | 3.4e-16 | none | yes |
| S5a | 95 | +0.668551% | +0.674225% | +5.67e-05 | 8.24e-03 | 2022-07, 2022-08, 2022-10, 2022-11 | 4.3e-16 | 2022-07, 2022-08, 2022-10, 2022-11 | NO |
| S5b | 95 | -1.744061% | -1.744704% | -6.43e-06 | 3.57e-04 | 2022-07, 2022-08, 2022-10, 2022-11 | 3.9e-16 | none | NO |
| S6a | 95 | -0.919217% | -0.911632% | +7.59e-05 | 7.09e-03 | 2022-07, 2022-08, 2022-10, 2022-11 | 3.5e-16 | 2022-07, 2022-08, 2022-10, 2022-11 | NO |
| S6b | 95 | -1.552602% | -1.548433% | +4.17e-05 | 6.51e-03 | 2022-07, 2022-08, 2022-10, 2022-11 | 3.4e-16 | 2022-07, 2022-08, 2022-10, 2022-11 | NO |
| S6c | 95 | -3.901997% | -3.884466% | +1.75e-04 | 6.92e-03 | 2022-07, 2022-08, 2022-10, 2022-11 | 4.0e-16 | 2022-10, 2022-11 | NO |
| S7a | 95 | -0.919180% | -0.919180% | -3.33e-16 | 3.33e-16 | none | 3.3e-16 | none | yes |
| S7b | 95 | -0.953338% | -0.953923% | -5.84e-06 | 3.48e-04 | 2022-07, 2022-08, 2022-10, 2022-11 | 4.0e-16 | none | NO |
| S9 | 95 | -2.521098% | -2.521098% | -9.02e-17 | 3.61e-16 | none | 3.6e-16 | none | yes |

Universe company-months with an adjusted close at or below zero at the decision or the next month-end (Stage 2 computed a return from them; the engine refuses a price <= 0): NFE (CIK 1749723) 2022-07; NFE (CIK 1749723) 2022-08; NFE (CIK 1749723) 2022-10; NFE (CIK 1749723) 2022-11.

### C. Separate comparison: next-day execution (not a reproduction)

Same scores and top-quintile rule. Trades at the next NYSE day's close (B1), no look-ahead universe, a held name losing its price exits at -30%, costs on weight changes (0.30% a unit). Decisions 2015-01 to 2022-10: the 2022-11 decision's next-day period would end in January 2023, which is holdout.

| Trial | Months | Stage 2 net, a year (same months) | Next-day net, a year | Difference | Weight turnover a month | Missing-price exits | Skipped entries |
|---|---:|---:|---:|---:|---:|---:|---:|
| S1a | 94 | -1.26% | -1.42% | -0.16% | 15.8% | 0 | 9 |
| S1b | 94 | -0.91% | -1.25% | -0.33% | 16.0% | 0 | 9 |
| S2a | 94 | -1.00% | -0.86% | +0.14% | 11.5% | 0 | 0 |
| S2b | 94 | -0.77% | -0.79% | -0.02% | 15.2% | 0 | 0 |
| S3a | 94 | -2.31% | -2.57% | -0.26% | 13.6% | 0 | 9 |
| S3b | 94 | -1.22% | -1.36% | -0.14% | 30.3% | 0 | 7 |
| S4 | 92 | -5.10% | -5.82% | -0.72% | 86.6% | 0 | 0 |
| S5a | 94 | +0.60% | +0.55% | -0.05% | 13.1% | 0 | 4 |
| S5b | 94 | -1.93% | -1.93% | -0.00% | 17.5% | 0 | 0 |
| S6a | 94 | -0.98% | -1.24% | -0.27% | 28.2% | 0 | 4 |
| S6b | 94 | -1.70% | -2.12% | -0.42% | 47.7% | 0 | 4 |
| S6c | 94 | -3.94% | -3.63% | +0.31% | 32.1% | 0 | 2 |
| S7a | 94 | -0.82% | -0.79% | +0.03% | 20.9% | 0 | 13 |
| S7b | 94 | -0.79% | -0.76% | +0.03% | 19.5% | 0 | 13 |
| S9 | 94 | -2.46% | -2.72% | -0.26% | 16.7% | 0 | 12 |

## Data files and hashes

| File | sha256 |
|---|---|
| monthly_metrics.csv.gz | `ae5429b661bd060d040109138d35cb4ea22356d4a549056c8616c3a2a7e87561` |
| prices_monthly.csv.gz | `505115711f7ef59c8df417671f8afecf77dd2240e13a2a3bdff453721b3d801a` |
| sec_companies.csv.gz | `acf5e3f746c355aa2c0aa2b76c0c3f55413daf5e927524672537d0389d214a90` |
| insider_trades.csv.gz | `82e99ff117d2ec0c2a33aeb0dd9f412b897aa3ced936e4e1e07e19bcdef8c676` |
| F-F_Research_Data_Factors.csv | `d7d7fe37b150b5b15c9c069b3ba101dfe1af568c6d7b5db6e73cd0a6c0c9e5e5` |
| exec_prices_to_2022.csv.gz | `dd6608f62ae2676fd4fd5b3b256105d5f52eb720ba3a10a2965cf504e17d47dc` |

## Investigation and verdict

- **Comparison A passes for all 15 trials.** Stage 2's own code, rerun now on data cut at 2022-12-31, matches
  the published result. All six summary fields agree within 1e-6, and the month counts are equal. So the
  published Stage 2 numbers did not depend on any holdout row. The Ken French factor file was re-downloaded
  after Stage 2 ran, but this made no measurable difference to S6c.
- **Comparison B (engine vs Stage 2 code) misses the 1e-6 tolerance for 12 of 15 trials, in 4 months only:**
  2022-07, 2022-08, 2022-10 and 2022-11.
  - Cause: New Fortress Energy (NFE) has a negative dividend-adjusted close in the research dataset in those
    months. This is a data defect recorded in Phase A.
  - Stage 2's harness computed a return from two negative prices and kept NFE in the universe and, for some
    trials, in the top quintile.
  - The new engine refuses any price at or below zero, by design (`edge_rules.holding_return`), so NFE cannot
    be bought there.
  - In every other month and every trial, engine and Stage 2 agree to within 1e-15.
  - Where holdings differ at all, the only difference is NFE in those months. In the other failing trials, NFE
    was in the universe but not in the top quintile.
  - S4, S7a and S9 pass outright because NFE has no score for them in those months.
- **Not changed to obtain a pass.** Making them agree would mean one of two things:
  - letting the engine trade at negative prices, which removes a safety rule;
  - excluding NFE from the Stage 2 reproduction, which changes the frozen specification.

  Either is a methodology decision for the owner.
- **Effect:** at most 0.021 percentage points a year on any trial's annualised top-quintile result.
- **Two harness corrections made during the investigation.** Both bring the inputs to the frozen
  specification; neither is a parameter change.
  1. The engine's month-end prices were first taken from the merged metrics-and-prices frame. That frame
     lacks one month (CIK 1635327, 2021-06) for which `prices_monthly` has a price and Stage 2 has a return.
     They are now taken from `prices_monthly` directly, as Stage 2's `ret_next` is.
  2. S4 has months with fewer than 30 scored large caps, which Stage 2 skipped. The engine raised an error
     there. It now holds nothing in such a month, and the month is left out of the comparison, as Stage 2
     left it out of its series.
- **Comparison C (next-day execution) is descriptive and was registered beforehand.**
  - Trading at the next day's close, with no look-ahead universe and costs on weight changes, moves the
    top-quintile result by between −0.72 and +0.31 points a year.
  - Every trial that was negative stays negative. S5a stays the only positive one (+0.55% a year, net).
  - No missing-price exit occurred. 0 to 13 entries a trial were skipped for lack of an execution price.

## Limitations (beyond the standing list above)

- **Survivorship bias.** Companies that stopped trading before 2026 have no free price, so they are never in
  the universe. Every Stage 2 and engine number shares this bias. B3 tests the arithmetic, not the data.
- **Look-ahead in the original specification.** Stage 2's universe requires a known next-month return. The
  reproduction keeps this deliberately, and comparison C removes it.
- **Execution at the decision close** (Stage 2) is not achievable in practice; comparison C shows the next-day
  alternative.
- **FX.** B3 is in USD, as Stage 2 was, so no FX is used. For later GBP work, FRED is unreachable and all FX
  comes from Yahoo GBPUSD=X.
- **Benchmark.** The comparison leg is the equal-weighted large-cap universe, as in Stage 2, not VWRP.
- **Data defects** (negative adjusted prices; share-count scaling) remain in the research dataset. The engine
  guards against the first; the Phase A quality rule handles the second for new trials, but is off here
  because Stage 2 did not use it.
- **Holdout and scope.** No 2023 or later price, signal or outcome was read. No new signal was registered or
  run. No confirmation test, demo allocation or account change was made.

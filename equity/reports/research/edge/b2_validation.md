# B2 validation: portfolio backtester on synthetic data

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

Run 2026-10-15T13:00:30+00:00. Synthetic data only: no research dataset, price file or holdout value is read. No signal is explored and no trial is run.

## Result: **PASS**, 29 of 29 tests pass

| Plan item (PHASE_B_PLAN.md §3) | Tests | Passed |
|---|---:|---:|
| 1. Planted signal recovered; random scores earn nothing | 1 | 1 |
| 2. Hand-computed 5-company portfolio (NAV, holdings, turnover, costs) | 1 | 1 |
| 3. Buffers, sector cap, weighting | 3 | 3 |
| 4. Costs by band, scaled exactly by the multiplier | 3 | 3 |
| 5. Exclusions: quality flag, price under $1, other bands | 2 | 2 |
| 6. Timing: no look-ahead, execution after the decision, 2023 refused, robustness convention | 4 | 4 |
| 7. Missing prices for new entries and holdings | 9 | 9 |
| 8. Currency conversion | 1 | 1 |
| 9. Benchmark metrics and VWRP/VWRL labels | 2 | 2 |
| 10. Registration, result records and DSR pooling | 2 | 2 |
| Reports open with the standing limitations | 1 | 1 |

Every test: `research/tests/test_edge_backtest.py`. Failing tests, if any: none.

## What was validated

- **Portfolio engine** (`research/edge_backtest.py`):
  - A planted signal (return = 0.02 × last month's score + noise) earns the expected excess over the
    equal-weighted pool, within 25%, with t > 5.
  - Random scores over 8 seeds average under 0.3%/month.
  - A 4-month, 5-company portfolio matches an independent hand calculation to 1e-12: NAV, holdings,
    turnover and costs.
- **Timing:**
  - Changing every score and price after month k leaves holdings and NAV through month k identical.
  - Every trade date is strictly after its decision.
  - A same-day trade raises `LookAhead`. Any 2023 row or execution date raises `HoldoutViolation`.
  - The next-month-close convention trades at the following month-end.
- **Missing prices**, as listed in `PHASE_B_PLAN.md` §7.2:
  - A new entry with `missing_exec`, `invalid_price` or no row is skipped and logged. `stale_month_end` blocks
    a purchase but still values a holding.
  - A holding that loses its price exits at the last valid price less 30%. The cash earns 0% until the next
    rebalance, and NAV accounts for every position.
  - Results order 0% ≥ −30% ≥ −100%. Even the 0% bound stops at the last price, and a positive assumption
    is refused.
- **Costs:**
  - Per band, 0.30% large, 0.45% mid and 0.75% small per unit of weight traded (FX 0.15% + spread).
  - The 2x and 3x multipliers scale them exactly.
- **FX:**
  - A constant rate leaves returns unchanged.
  - A known GBP/USD path converts exactly.
- **Constraints:**
  - Rank buffer (hold to 2N).
  - Sector cap never exceeded; skipped names are logged.
  - Equal, score and inverse-volatility weights sum to 1.
  - Quality-flagged rows, prices under $1 and other bands are never bought.
- **Benchmark:**
  - Tracking error, information ratio, share of months ahead and relative drawdown match a hand calculation.
  - The label switches to "actual VWRP" at the period starting 2019-08-01 (VWRP's first full month; see
    `PHASE_B_PLAN.md` §7.4).
  - A 2023 benchmark value is refused.
- **Governance:**
  - An unregistered trial, or one already reported, is refused.
  - Results record their statistic.
  - The DSR pools only portfolio results and uses the registry's trial count.
- **Mutation check:** to confirm the tests can fail, three deliberate bugs were injected one at a time, then
  reverted:
  - ignoring the missing-price markdown made 5 tests fail;
  - ignoring the cost multiplier made 9 fail;
  - letting stale-price names be bought made 1 fail.

## Not validated here (and why)

- **Real-data behaviour.** B2 is synthetic by instruction; the first real run is B3, which needs the owner's
  approval and a registered trial.
- **The Ken French proxy segment before 2012-06.** It is not built; `benchmark_returns` labels those periods
  "none". Trials start in 2015 (the VWRL segment), so the proxy is needed only for an explicit pre-2012
  robustness run.
- **Stage 2 reproduction through the new engine** (PHASE_B_PLAN.md §4, B3 gate). It uses real data, so it
  waits for approval.
- **Survivorship bias.** Software cannot test this away; see the standing limitations above.

# Edge-discovery Phase B: concentrated-portfolio backtester (plan)

Status: revised 2026-10-14 after the owner's review of PR #18. Not authorised yet; nothing here has been run.

**Goal:** answer one question for any registered signal, on exploration data only (outcomes to 2022-12): *would
a concentrated portfolio of 15 to 30 US stocks, rebalanced quarterly and held in GBP, have beaten VWRP after
costs?* The specification is `EVALUATION_SPEC.md` §4. This document says how the backtester is built and how it
is shown to be correct before any real trial runs on it.

The rules that could leak information or flatter results are already code, tested in Phase A
(`research/edge_rules.py`, `research/tests/test_edge_rules.py`):

- timing;
- missing prices;
- invalid prices;
- the deflated Sharpe.

The backtester must use them, not reimplement them.

## 1. What is reused

| Need | Existing code |
|---|---|
| Data, cut and flagged | `edge_split.cut_exploration`, `with_quality`, `complete_months`, `cut_series`, `forward_return` (invalid prices treated as missing) |
| Decision inputs and trade timing | `edge_rules.decision_frame`, `execution_time`, `exploration_execution`, `assert_executable` |
| Holding returns with missing or invalid prices | `edge_rules.holding_return` |
| Signal scores | `stage2.build_features` and `TRIALS`; new hypotheses add score functions |
| Sector groups | `stage2.sic_group` (today's SIC: stated bias) |
| GBP conversion | `dataset.usd_to_gbp_monthly`. Its FX comes from FRED, with Yahoo as the fallback; FRED was unreachable from this container on 2026-10-14. |
| Benchmarks | `dataset._tr_daily_gbp` for VWRP.L and VWRL.L; the Ken French proxy as in `dataset.build` |
| Factor alpha | `stage2.factor_alpha` |
| Deflated Sharpe | `edge_registry.deflated_sharpe` (stat-aware; §2.6) |
| Registration | `edge_registry.require` before running; a `result` event with `stat` after |

New code: `research/edge_backtest.py` and `research/tests/test_edge_backtest.py`. Nothing existing changes.

## 2. Design

### 2.1 Execution timing

**Trading at the decision close is not achievable.**

- At month-end t the signal needs that day's close (prices, market cap, size band, the $1 filter) and filings
  dated t. Some of those filings are accepted after the close.
- An order filled at the close of t would have to be placed before that close was known.
- Monthly academic backtests usually ignore this. Here it is a look-ahead of a few hours, so it is not used.

| | Default: `next_day_close` | Robustness: `next_month_close` |
|---|---|---|
| Information set | Filings dated ≤ t; prices up to the close of t's last trading day | Same |
| Execution price | Close of the first trading day after t | Close of the next month-end (t + 1 month) |
| Achievable? | Yes. Everything is public before the next day's close; a market-on-close order is placed during that day. | Yes, but one month late, so it shows how fast the edge decays |
| Data needed | First-trading-day closes for each month (Yahoo daily, the same free source as the monthly file). These go in a new research file built by new code; the production price build is untouched. | Existing monthly prices |

- **Exploration boundary:** `exploration_execution` refuses a trade executing after 2022-12-31. The last holding
  period is valued at the 2022-12 month-end close.
- **If daily closes cannot be built,** the owner chooses: `next_month_close` becomes the default, or the build
  waits.

### 2.2 Alignment at every rebalance k (decision t_k, execution e_k)

1. **Inputs:** `decision_frame(panel, t_k)` gives rows dated ≤ t_k, with no `ret_*` or `exec_*` columns. It
   raises if a filing is dated after its row's month.
2. **Scores and eligibility** are computed from those inputs only. Eligibility means: band, `quality_ok`, price
   ≥ $1, a score.
3. **Target weights** w_k come from ranks, buffers, the sector cap and the weighting rule.
4. **Drifted weights** w_k⁻ are the previous holdings grown from e_{k−1} to e_k by their holding returns, then
   renormalised.
5. **Turnover** is Σ|w_k − w_k⁻| / 2. The cost is Σ |w_k,i − w_k,i⁻| × (0.15% FX + the spread for band_i at
   t_k), deducted at e_k.
6. **Returns between execution points** e_k → e_{k+1} come from `holding_return` on prices at execution dates.
   Monthly accounting values every holding at each month's execution-date close.
7. **Benchmarks** are measured on the same execution dates: VWRP/VWRL daily closes, and the equal-weighted
   universe from the same prices. Factor regressions use the monthly series.

### 2.3 Selection, weights, costs, currency

**Selection:**

- Target N names, with N between 15 and 30.
- Holdings ranked N or better are kept.
- Holdings ranked worse than N but no worse than 2N are kept while there is room (the exit buffer).
- Holdings ranked worse than 2N are sold.
- Empty slots are filled from the top of the ranking.
- Sector cap: k names per `sic_group` (default k = max(3, N/5)).

**Weights:** equal (default), score-proportional, or inverse 12-month volatility known at t_k. Positions are long
only, with no leverage. If fewer than N names are eligible, the portfolio holds fewer, and the shortfall is
reported.

**Costs:** the band spreads above, at 1x, 2x and 3x.

**Currency:** USD returns are converted to GBP monthly. Factor alpha uses USD excess returns.

### 2.4 Missing prices, delistings, acquisitions, ticker changes

The free data cannot tell these apart. Each one appears as a held company whose price stops, or turns ≤ 0.
`holding_return` handles them all the same way:

- the position closes at its **last valid price**;
- that price is then marked down by `missing_return`:
  - the default is **−30%**;
  - the stress is **−100%**;
  - 0% is reported only as a labelled optimistic bound.

**A missing price can never look better than its last valid price.** A positive `missing_return` is refused.
Proceeds sit in cash at 0% until the next rebalance.

| Case | What happens | Bias |
|---|---|---|
| Bankruptcy or delisting for cause | −30% (default) or −100% (stress) from the last price | −30% is close to typical delisting losses for performance delistings; −100% bounds it |
| Cash acquisition | Treated the same | Against the strategy: targets are usually bought at a premium |
| Ticker change, or a gap in the data | Treated the same; the company may be bought again at the next rebalance if priced | Against the strategy |
| A price ≤ 0 (adjustment error) | Treated as missing (tested) | Against the strategy |

**Reported per run:**

- the number and weight of missing-price exits;
- results at −30%, −100% and 0%.

A result whose conclusion changes between 0% and −100% is marked fragile.

**Limitation: stress tests do not remove survivorship bias.** Companies that stopped trading before 2026 are
absent from the data altogether: 318 of 323 large companies that stopped filing in 2023 to March 2026, and all
that stopped by 2022. The backtester never holds them, so these rules apply only to the rare in-sample
disappearances. Every result states this survivorship bias first.

### 2.5 Benchmark: what "VWRP" means in each period

| Period (monthly returns) | Series | Fee | Currency | Coverage vs FTSE All-World |
|---|---|---|---|---|
| From 2019-09 | **Actual VWRP** (VWRP.L, accumulating; launched 2019-07-25) | In the price (fund OCF) | GBP | Same index |
| 2012-06 to 2019-08 | **VWRL-based**: VWRL.L (same fund, distributing share class), Yahoo adjusted close with dividends reinvested | In the price | GBP | Same index |
| Before 2012-06 | **Proxy**: Ken French developed-markets market return − 0.2%/yr | Haircut | USD → GBP, month-end FX | Developed only (no emerging markets, about 10% of the index); includes small caps |

**Measured on exploration data** (to 2022-12), monthly in GBP:

| Pair | Months | Mean difference | Tracking error | Correlation |
|---|---:|---:|---:|---:|
| VWRP vs VWRL | 40 (2019-09 to 2022-12) | −0.02%/yr | 0.37%/yr | 0.9996 |
| VWRL vs proxy | 127 (2012-06 to 2022-12) | −0.93%/yr | 2.82%/yr | 0.970 |

The proxy is therefore not a substitute for the fund.

**Rules:**

- Comparisons are labelled by series and period.
- **"vs actual VWRP" is reported only from 2019-09.**
- 2015-01 to 2019-08 is "vs VWRL (VWRP's distributing twin)".
- No proxy period falls inside the 2015-2022 large-cap window, so the proxy is not used for it.
- `dataset.build()["WORLD"]` (VWRL from 2012-06, proxy before) is used only where these labels are kept.

### 2.6 Deflated Sharpe

- **N** = `edge_registry.n_trials()`, currently 96. That counts every registered look, IC-only diagnostics
  included (owner decision D4).
- Correlated variants count separately, which overstates the effective N and makes the test stricter.
- **The variance of Sharpe ratios comes only from results of the same statistic** (`stat`). Each portfolio trial
  records `stat: "portfolio_excess_vs_vwrp"`. Stage 2's 15 Sharpes are a different statistic (top quintile minus
  universe) and are never pooled with it.
- **The variance is floored at 1/T.** With fewer than two comparable results (true at the start of Phase B), the
  floor is used.
- Missing or non-finite Sharpes count in N but not in the variance.
- **Limitation:** with few comparable trials the variance is the null floor, not an estimate. Counting correlated
  variants as independent makes the DSR conservative. It answers "is this better than the best of N unskilled
  tries", not "is it real".

## 3. Validation tests (all must pass before any real trial)

1. **Planted signal.** On synthetic data, a predictive score earns the planted excess return over the universe; a
   random score earns none on average.
2. **Hand-computed portfolio.** Five companies over three quarters: holdings, drifted weights, turnover, costs and
   returns all match a hand calculation.
3. **Buffers and sector cap.** Ranks N+1 to 2N are kept; ranks worse than 2N are sold; the cap is never exceeded;
   skipped names are reported.
4. **Costs (D5).** Band rates are applied by band at t_k, and 2x and 3x scale exactly.
5. **Exclusions (D5).** A `quality_ok == False` company-month is never bought.
6. **Timing.**
   - Holdings at t_k do not change when anything after t_k changes (prices, returns, execution prices).
   - Trades execute strictly after the information time.
   - No exploration trade executes after 2022-12-31.
7. **Missing prices.** `holding_return` cases flow through the portfolio: an exit is marked down, −100% removes
   the weight, and cash earns 0%.
8. **Currency.** A constant FX rate gives GBP = USD; a known FX path matches a hand calculation.
9. **Benchmarks.** IR, tracking error and relative drawdown match a hand calculation. Series labels change at
   2019-09 and 2012-06. A 2023 benchmark value is refused.
10. **Registration and DSR.** An unregistered or already-reported trial is refused. Each result records `stat`.
    The DSR uses N = `n_trials` and pools only the same `stat`.
11. **Reproduction.** Set the backtester to Stage 2's harness:
    - top quintile, monthly rebalancing, equal weights;
    - no buffers or cap, a flat 0.30% cost, USD, execution at the decision close (allowed only in this test).

    It then reproduces `xsection.evaluate`'s top-quintile net return for one Stage 2 signal, to 1e-6 a month.
    That number is already published, so this run is registered as a diagnostic that does not count.

## 4. Implementation sequence and gates

| Step | Work | Gate to pass before the next step |
|---|---|---|
| B0 | Owner authorises Phase B (after merging PR #18) | Owner's word |
| B1 | Build first-trading-day closes for the priced universe and benchmarks, to 2022-12 only, as a new research file with a manifest entry | Integrity checks: one row per company-month, prices > 0 or flagged, dates are the first trading day after each month-end; no row after 2023-01-03 |
| B2 | `edge_backtest.py` on synthetic data only | Validation tests 1-10 pass |
| B3 | Reproduction run (test 11), registered as a non-counting diagnostic | Agreement to 1e-6 |
| B4 | Validation report to the owner: tests, reproduction, limitations | Owner records `backtester_validated` |
| B5 | Owner chooses the first exploration trials. Each is registered with its portfolio rules fixed before it runs. Suggested: H1 (FCF per share acceleration, after the TTM checks in PHASE_A_AUDIT §10.4) and S2a gross profitability as a 12-month hold. | Each trial: `require` passes; results recorded with `stat` |
| B6 | Candidates reaching E2 are listed for the single confirmation batch: exploration t ≥ 3, positive at 2x costs, alpha beyond FF5 + momentum, robust to −100% missing prices and to `next_month_close` | Owner review; **no confirmation run is authorised** |

## 5. Out of scope

- Confirmation runs.
- Paid data.
- Any change to the signal log, Stage 2, the price builder, trading code or accounts.
- A model combining signals.

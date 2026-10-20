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
disappearances. Every report opens with `edge_rules.STANDING_LIMITATIONS`, and
`edge_rules.require_disclosure` refuses one that does not (PHASE_A_AUDIT §11.10).

### 2.5 Benchmark: what "VWRP" means in each period

| Period (monthly returns) | Series | Fee | Currency | Coverage vs FTSE All-World |
|---|---|---|---|---|
| From 2019-08 | **Actual VWRP** (VWRP.L, accumulating; first price 2019-07-25, first month-end 2019-07-31) | In the price (fund OCF) | GBP | Same index |
| 2012-06 to 2019-07 | **VWRL-based**: VWRL.L (same fund, distributing share class), Yahoo adjusted close with dividends reinvested | In the price | GBP | Same index |
| Before 2012-06 | **Proxy**: Ken French developed-markets market return − 0.2%/yr | Haircut | USD → GBP, month-end FX | Developed only (no emerging markets, about 10% of the index); includes small caps |

**Measured on exploration data** (to 2022-12), monthly in GBP:

| Pair | Months | Mean difference | Tracking error | Correlation |
|---|---:|---:|---:|---:|
| VWRP vs VWRL | 40 (2019-09 to 2022-12; measured before the start-date correction, August 2019 omitted) | −0.02%/yr | 0.37%/yr | 0.9996 |
| VWRL vs proxy | 127 (2012-06 to 2022-12) | −0.93%/yr | 2.82%/yr | 0.970 |

The proxy is therefore not a substitute for the fund.

**Rules:**

- Comparisons are labelled by series and period.
- **"vs actual VWRP" is reported only from 2019-08** (first full monthly return; corrected from 2019-09 on 2026-10-15, see §7.4).
- 2015-01 to 2019-07 is "vs VWRL (VWRP's distributing twin)".
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
   2019-08 (first execution-date period 2019-08-01) and 2012-06. A 2023 benchmark value is refused.
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

## 6. B1 result (2026-10-15)

Built by `research/edge_exec_prices.py` into `/mnt/project-files/research-data/edge/` (manifest with SHA-256
hashes; `edge_exec_prices.load` refuses a file that no longer matches it). Report:
`equity/reports/research/edge/exec_prices_integrity.md`. No integrity check failed.

- **Cutoff:** every request ended at 2022-12-31; 0 dates after it in any file. Decisions 2009-12 to 2022-11.
- **Execution dates:** all 482,357 rows execute on the first NYSE trading day after the month-end.
- **Coverage:** 99.8% of the research dataset's USD company-months have a usable row; 5 of 4,374 tickers
  returned nothing (BLFS, SLP, WBD, LIVG, GBTG).
- **Agreement:** month-end returns from the daily data match the research dataset's monthly returns in 100.00% of
  447,969 cases (within 0.1 points).
- **Row status:** 482,028 usable; 314 with a price ≤ 0 (4 large-cap), 11 with no trade on the execution day, 4
  with a stale month-end close. The backtester treats all non-usable rows through `edge_rules.holding_return`.
- **FX:** FRED did not respond, so all 3,430 days come from Yahoo GBPUSD=X (source recorded per day).
- **Benchmarks:** VWRP from 2019-07-25 and VWRL from 2012-05-22, in GBP.

**Found, not fixed (owner's call before B2):** 3 large-band company-months that pass the approved quality rule
show impossible overnight moves (ATLX 2015-01 and 2015-04 +100%; ATXG 2022-08 −95%). Both are tiny companies
whose price or share-count history is mis-scaled, so they land in the large band. Large-cap overnight moves are
otherwise ordinary (median 1.0%, 99th percentile 7.0%). Changing the exclusion rule is a methodology change, so
this is flagged for the owner, not applied. Options: a registered extra quality rule (exclude a company-month
whose decision-to-execution move exceeds 50%), or leave the rule and rely on the backtester's tests.

## 7. B1 audit (owner review, 2026-10-15 12:41Z)

The owner accepted the B1 data build conditionally (not approval to run signal trials), subject to five points.
Script: `research/edge_exec_audit.py` (read-only, data to 2022-12-31). Report:
`equity/reports/research/edge/exec_prices_audit.md`, with `exec_prices_audit_moves.csv` (every move over 50%)
and `exec_prices_audit_coverage_by_month.csv`.

### 7.1 Overnight moves (decision close to execution close)

1,341 of 482,028 usable rows move more than 50% overnight. Each is classified in this order:

- `split_like`: within 2% of a split ratio.
- `extreme`: more than 10x either way.
- `reversal`: the next month-end is back within 20% of the decision close.
- `penny`: decision close under $1, which is outside the universe anyway.
- `plausible`: anything else.

The first three are probable data errors; `plausible` moves are treated as genuine.

| Group | Rows | Probable data errors | Plausible (kept) | Penny |
|---|---:|---:|---:|---:|
| All rows | 1,341 | 557 | 199 | 585 |
| Eligible universe (banded, quality ok) | 27 | 12 | 14 | 1 |
| of which large band | 3 | 3 (ATLX 2015-01, 2015-04; ATXG 2022-08) | 0 | 0 |

**Decision:**

- Genuine moves are preserved, and nothing is excluded from the main run.
- One sensitivity analysis is registered before any run: `B1-SENS-DATA-ERRORS` in `research/edge/trials.jsonl` (diagnostic, not counted in the DSR).
- That sensitivity reruns a future exploration backtest with the 12 eligible probable-error company-months barred from new purchases.
- A conclusion that holds only with the exclusion is treated as not holding.
- The sensitivity has not been run.

**Count reconciliation:**

- The build-time integrity report said 1,299 rows. Rerunning the same check on the stored, hash-verified file gives 1,341.
- 322 usable rows move by exactly 50% (prices on a tick grid). In-memory floats and floats read back from the CSV differ in the last bit, so about 42 of these flip across the `> 0.5` threshold.
- The data files are unchanged (hashes verified). The integrity report was regenerated from the stored files and now says 1,341.

### 7.2 Non-usable execution rows: what the backtester does

These behaviours are tested in `research/tests/test_edge_backtest.py` (section 7).

| Case | New entry | Existing holding |
|---|---|---|
| `missing_exec` (no trade on the execution day) | Not bought; logged `skipped_entry`; the next buyable name fills the slot | Exits at the last valid price × (1 − 30%); proceeds held as cash at 0% until the next rebalance; logged `exit` |
| `invalid_price` (price ≤ 0) | As above | As above |
| absent (no row at all) | As above | As above |
| `stale_month_end` (decision close not on the month-end) | Not bought (the decision price is stale) | Kept and valued on the execution close, which is valid |

**Guarantees, each tested:**

- No missing-price case drops a position silently: NAV equals the exit value plus the other holdings.
- No missing-price case creates a favourable return: the closing price is capped at the last valid price, and a positive `missing_return` is refused.
- Ordering holds: 0% ≥ −30% ≥ −100%.
- All of these follow `edge_rules.holding_return`, the documented exit policy.
- **Effect on the investable universe:** a company-month without a usable execution row cannot be bought at that rebalance, but it stays in the ranking. Ranks are not recomputed, so the next-ranked buyable name takes the slot.

### 7.3 Coverage by month and eligibility group

| Group | Company-months | Usable | Coverage |
|---|---:|---:|---:|
| Large, quality ok | 55,991 | 55,941 | 99.91% |
| Mid, quality ok | 83,030 | 83,005 | 99.97% |
| Small, quality ok | 100,858 | 100,757 | 99.90% |

- Eligible universe by month: minimum 99.79% (2022-09), median 99.93%; 0 of 143 months below 99%.
- Large band by month: minimum 99.58% (2012-04).

### 7.4 Benchmark dates

| | VWRP |
|---|---|
| First price | 2019-07-25 |
| First month-end close | 2019-07-31 |
| First full monthly return | **2019-08** |
| First execution-date period | starts 2019-08-01 |

- The earlier statement "actual VWRP from 2019-09" was one month late. It is corrected in §2.5, `EVALUATION_SPEC.md`, `PHASE_A_AUDIT.md` and `edge_rules.STANDING_LIMITATIONS`.
- VWRL-based returns cover 2012-06 to 2019-07.
- The 40-month VWRP-vs-VWRL tracking figure in §2.5 was measured from 2019-09 and is left as measured.

### 7.5 FX and provenance

- The manifest now records a provenance entry for every file.
- **FRED was not used.** It failed at build and failed again on retry (2026-10-15 12:52Z: remote end closed the connection).
- All 3,430 FX days come from Yahoo GBPUSD=X (source column per day).
- The SPY trading calendar is now stored as `nyse_calendar_to_2022.csv.gz` with its own hash.
- **Hashes are preserved and verified:**
  - exec prices: `dd6608f6…47dc`
  - FX: `fd9f8e7d…0d65`
  - benchmarks: `0ec17f86…fc6`
- **The strict 2022-12-31 cutoff is unchanged.** Full hashes are in `exec_prices_integrity.md`.

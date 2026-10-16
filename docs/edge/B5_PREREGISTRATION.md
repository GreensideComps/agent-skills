# B5 pre-registration: H1 and S2a exploration trials (frozen, not run)

Written 2026-10-16, before any H1 or S2a portfolio computation, on the owner's instruction of 2026-10-16 10:12Z.
Nothing in this document has been run. No return, NAV or score ranking for either trial has been computed or seen.

**Status of this document:** proposed for owner review. The definitions below are registered in
`research/edge/trials.jsonl` (ids in §6) so they cannot be changed silently. If the owner amends anything before
the trials run, the amendment is registered as a superseding entry and the superseded ids still count in the trial
total (conservative). After the trials run, nothing here can change; a variant is a new, counted trial.

**Scope (unchanged restrictions):**

- Exploration only. Every input is cut at 2022-12-31 on read (`edge_split.cut_exploration`, `cut_series`). No 2023
  or later row is read. No confirmation test. No holdout data.
- `backtester_validated` applies for exploratory research only (D12).
- Survivorship bias is accepted for exploration only (D13; `SURVIVORSHIP_FEASIBILITY.md`).
- No demo allocation. No change to the real ISA, holdings or trading configuration. The monthly signal log is
  unchanged.
- The trials do not run until the blockers in §8 are cleared and the owner approves running them.

## 1. Common portfolio rules (both trials)

| Element | Rule |
|---|---|
| Data | `monthly_metrics`, `prices_monthly`, `sec_companies` (hashes in `B3_STAGE2_SPEC.md` §6); B1 execution prices, FX and benchmarks (hashes in `PHASE_B_PLAN.md` §6). Hashes are re-checked at run time; any change stops the run. |
| Point in time | Fundamentals as filed on or before the decision month-end (`edge_integrity`: 0 later filings). Lags are exact months (`stage2.lag`). SIC is today's (a stated limitation). |
| Universe | Large band (market cap ≥ $10bn = mcap share count × `close_raw`, as `xsection`); `close_raw` ≥ $1; Phase A quality rule (`edge_split.with_quality` on cut data, D5); financials (SIC 6000-6799) excluded; score present. No next-month return is required (no look-ahead). |
| Freshness | The decision month-end is at most 183 days after `ttm_end`. Otherwise the score is missing. |
| Ranking | Score descending; ties by CIK ascending (`edge_backtest.eligible`). |
| Portfolio | 20 names, equal weight, long only, no leverage. Rank buffer 2.0 (a holding ranked up to 40 is kept while there is room). Sector cap 4 names per SIC group (`Config.cap()` default for N = 20). |
| Execution | Next NYSE trading day's close after the decision (`next_day_close`). A new name without a valid execution price is skipped and the next name takes the slot. |
| Missing prices | A holding that loses its price exits at its last valid price less 30% (`edge_rules.holding_return`); cash earns 0% until the next rebalance. |
| Costs | One way per unit of weight traded: FX 0.15% + spread 0.15% (large) = 0.30%, at 1x. |
| Currency | USD returns converted to GBP with the B1 GBPUSD series (rate on or before the date, within 7 days). |
| Tranches | Each trial runs as staggered tranches (§2, §3) so the result does not depend on an arbitrary start month. The combined monthly return is the equal-weighted mean of the tranches' GBP returns. Rebalancing capital between tranches is assumed free (small and slightly optimistic; stated in the report). |
| Evaluation window | Monthly periods between consecutive execution dates, from the execution after the 2015-01-31 decision to the execution after the 2022-11-30 decision (94 periods, the same decisions as Stage 2). Tranches may start in 2014 so that all are live from the first evaluated period; 2014 is exploration data. |
| Engine | `edge_backtest.run_trial` with `Config(n=20, weighting="equal", buffer=2.0, sector_cap=None, bands=("large",), min_price=1.0, cost_mult=1.0, missing_return=-0.30, convention="next_day_close", selection="top_n")` and the trial's `rebalance_every`. |

## 2. H1: accelerating free cash flow per share

**Hypothesis (programme doc, H1):** investors anchor on past growth, so they underreact when per-share cash
generation speeds up. Companies whose per-share free cash flow growth has accelerated should outperform.

**Origin and prior looks (disclosed):** the in-house precedent is the 14 Oct sub-score audit (FCF per share
t = 2.9), which pooled cohorts including the holdout (`PHASE_A_AUDIT.md`, rows M8 and M8-AUDIT). Those looks are
already counted (D4). A future holdout test of H1 would be weaker for it (D3).

**Score, for company i at decision month t** (all inputs at or before t):

1. Share count `Sh_t` = `shares_out` if positive, else `shares_diluted` (the count used for market cap).
2. Free cash flow `FCF_t` = `ttm_ocf − ttm_capex` (missing capex treated as 0, as Stage 2's S1a).
3. Split factor between t−12 and t: `k_t = close_raw_t / adjclose_t`, `s_t = k_{t−12} / k_t`. If
   |ln `s_t`| ≤ ln 1.25, `s_t` = 1 (no split; this absorbs dividend drift). Adjustments after t cancel in the
   ratio, so only events between t−12 and t, known at t, enter.
4. Split-neutral share growth `q_t = Sh_t / (Sh_{t−12} × s_t)`. If |ln `q_t`| > ln 3, the score is missing
   (a merger, a spin-off or a share-count error, not per-share growth).
5. Per-share FCF change, scaled by assets per share:
   `G_t = (FCF_t / Sh_t − FCF_{t−12} / (Sh_{t−12} × s_t)) / (total_assets_t / Sh_t)`
   which simplifies to `(FCF_t − FCF_{t−12} × q_t) / total_assets_t`. `total_assets_t` > 0 is required.
   Scaling by assets (not price) keeps valuation and price momentum out of the score.
6. **Score `H1_t = G_t − G_{t−12}`** (this year's per-share change minus last year's). Higher is better. Needs
   rows at t, t−12 and t−24 with `ttm_end_t > ttm_end_{t−12} > ttm_end_{t−24}`, each meeting the 183-day freshness
   rule at its own month.

**Ranking:** raw cross-section of eligible large caps (not sector-neutral: the mechanism is company-specific; the
sector cap limits concentration).

**Rebalance:** quarterly (`rebalance_every = 3`), TTM data changes quarterly. **Three tranches** starting at the
2014-11-30, 2014-12-31 and 2015-01-31 decisions.

## 3. S2a: gross profitability, held for 12 months

**Hypothesis:** profitable firms (gross profit relative to assets) earn higher returns, and the effect is slow:
the Stage 2 diagnostic found the IC strengthening with horizon (12-month t 1.8, a lead only). Stage 2 tested it
with monthly rebalancing (failed); this trial tests the 12-month holding the diagnostic pointed to.

**Score:** Stage 2's S2a, unchanged: gross profit = `ttm_gross_profit`, else `ttm_revenue −
ttm_cost_of_revenue`; divided by `total_assets` (> 0); converted to a percentile rank within the SIC group
(`stage2.GROUPS`) among the month's eligible large-band names, financials excluded. Higher is better.
The 183-day freshness rule applies (Stage 2 had none; this is a new trial, not a reproduction).

**Rebalance:** every 12 months (`rebalance_every = 12`). **Twelve tranches** starting at each decision month from
2014-02-28 to 2015-01-31.

**Disclosed prior look:** the 12-month horizon was chosen after seeing Stage 2 diagnostics on 2015-2022 data. That
is a prior look on this same window; it is counted (Stage 2 and the diagnostic horizons are in the 96).

## 4. Benchmarks and metrics (both trials)

**Primary benchmark:** VWRP in GBP, labelled by segment: "VWRL-based" to 2019-07, "actual VWRP" from 2019-08
(`edge_backtest.benchmark_returns`). Price on or before each date, within 5 days.

**Primary statistic (`portfolio_excess_vs_vwrp`):** the monthly combined net GBP return minus the benchmark return.

**Reported for every trial, whatever the outcome:**

- annualised net excess, its Newey-West t (lags: 3 for H1, 12 for S2a, because overlapping 12-month tranches
  make monthly returns autocorrelated), and the non-overlapping check for S2a (every 12th month);
- CAGR, volatility, Sharpe, maximum drawdown (strategy and benchmark);
- tracking error, information ratio, share of months ahead, relative drawdown, worst rolling 12-month excess;
- excess over the equal-weighted eligible large universe (same execution, zero cost, as Stage 2's universe leg);
- FF5 + momentum alpha of the USD strategy return less the risk-free rate (`stage2.factor_alpha`, same NW lags),
  with betas;
- turnover a year, largest weight, average top-5 weight, missing-price exits, skipped entries;
- excess by sub-period third, and with the largest single contributor removed;
- deflated Sharpe ratio (`edge_registry.deflated_sharpe`, N = registry trial count at the time of the result);
- results at 2x and 3x costs and under each robustness check in §6;
- the standing limitations (`edge_rules.STANDING_LIMITATIONS`).

## 5. Exploratory decision thresholds (set in advance)

A positive return alone is not a pass. **A trial is an "E2 candidate" only if every condition holds:**

| # | Condition | Threshold |
|---|---|---|
| P1 | Net excess vs VWRP/VWRL at 1x costs | Newey-West t ≥ 3.0 (Harvey, Liu and Zhu exploration bar; `EVALUATION_SPEC.md` §5). For S2a the non-overlapping t must also be ≥ 2.0. |
| P2 | Deflated Sharpe, N = all counted trials (98 after this registration) | DSR ≥ 0.80. With 94 months this needs roughly t ≥ 3.6; it is the binding multiple-testing condition. |
| P3 | Alpha beyond known factors | FF5 + momentum alpha > 0 with t ≥ 2.0 |
| P4 | Costs | Net excess > 0 at 2x costs |
| P5 | Selection adds value | Net excess over the equal-weighted eligible universe > 0 |
| P6 | Missing prices | Net excess > 0 with held names that lose their price marked at −100% |
| P7 | Execution timing | Net excess > 0 under `next_month_close` |
| P8 | Data errors | Net excess > 0 with the 12 suspected data-error rows (`PHASE_B_PLAN.md` §7.1) excluded |
| P9 | Quality rule | Net excess > 0 under the point-in-time (expanding-median) quality rule |
| P10 | Stability | Net excess > 0 in at least 2 of the 3 sub-period thirds |
| P11 | Concentration | Net excess > 0 with the single largest contributing company removed |

**Outcomes:**

- **E2 candidate:** all of P1-P11. This allows only a drafted confirmation pre-registration for the owner's review.
  It authorises no confirmation run and no demo allocation.
- **Lead, not a pass:** t between 2.0 and 3.0 with P3-P11 holding. Recorded; no follow-up variant without a new,
  counted registration and owner approval.
- **Fail:** anything else.

**Multiple-testing treatment:**

- Both trials count in N (`counts_for_dsr: true`), taking the total from 96 to 98, with all inherited trials and
  prior looks (D4).
- The robustness runs (P4, P6-P9) are registered diagnostics (`counts_for_dsr: false`). They can only veto a
  pass; they never replace the primary result. P5, P10 and P11 come from the primary run.
- The t ≥ 3.0 bar and DSR with the full N are both required. Either trial passing does not lower the bar for the
  other.
- Both results are reported whatever they show. A failed trial is not rerun or tuned. Any change of definition,
  window, N, rebalance or universe is a new counted trial that needs owner approval.
- Only bug fixes found by the hand-check or tests may change code before the run, and none may change a definition
  here. Any ambiguity found is written up and resolved with the owner before the run.

**Power (stated in advance):** with 94 months and tracking error around 5-8% a year, t ≥ 3 needs an annual
excess of roughly 5-9%. Smaller real edges will not be detected; a fail is "not detected", not "no effect".

## 6. Registered ids

| Id | Kind | Counts in N |
|---|---|---|
| `B5-H1-FCFPS-ACCEL` | trial | yes |
| `B5-S2A-GP-12M` | trial | yes |
| `B5-H1-ROB-2XCOST`, `-MISS100`, `-NEXTMONTH`, `-DATAERR`, `-PITQ` | diagnostic (robustness) | no |
| `B5-S2A-ROB-2XCOST`, `-MISS100`, `-NEXTMONTH`, `-DATAERR`, `-PITQ` | diagnostic (robustness) | no |
| `B5-HANDCHECK` | diagnostic (implementation check, placebo score) | no |

3x costs is reported alongside the 2x run (same run family), not as a separate gate.

## 7. Exclusions (summary)

Financials; price under $1; outside the large band; Phase A quality flag; stale TTM (> 183 days); missing lags;
share-count change over 3x after split adjustment (H1); non-positive total assets. No company is excluded by name.
NFE-type negative adjusted prices are refused by the engine (D10), never traded.

## 8. Remaining blockers before either trial runs

1. **Owner approval** of this document and of running B5 (D11).
2. **Code, with synthetic tests first:** the H1 score (split factor, share-growth guard, freshness), the S2a
   within-group rank on the engine's eligible set, tranche combination, the FF5 + momentum portfolio regression,
   the leave-one-company-out and sub-period summaries. Tests run before any real data is touched.
3. **TTM checks 1-3** (`PHASE_A_AUDIT.md` §10.4: store the basis, fiscal-year identity, jump review). They use
   2015-2022 fundamentals only, no returns. Check 4 (an independent second source) stays open; without it neither
   trial can be called more than an exploration result built on unverified XBRL.
4. **The real-data hand-check** (`B5_HANDCHECK_PLAN.md`) passes in full.
5. **PR #19** is reviewed and merged by the owner, so the trials run from merged code. The repo has no CI; tests
   run locally before every push.

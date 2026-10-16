# B5 pre-registration, addendum 1

Written 2026-10-16, after the owner's review at 13:03Z and **before any H1 or S2a score, ranking, return, NAV,
Sharpe ratio or verdict has been computed**. It amends `B5_PREREGISTRATION.md` version 2, which stays unchanged and
hash-frozen (sha256 `51acdd22…0d18`). This file's own sha256 is recorded in the registry as `B5-V2-ADDENDUM-1`;
`research/tests/test_edge_rules.py` fails if either file is edited. Neither trial may run until the owner approves
version 2 together with this addendum.

Nothing below was chosen by looking at a result. The input audit that informed §1 and §3 reads SEC fact rows only
(`research/edge_b5_input_audit.py`, report `equity/reports/research/edge/b5_input_audit.md`).

What does **not** change: the trial ids, N = 100, the DSR formula, the gates P1-P11 and their thresholds, the
portfolio rules, the tranches, the benchmark and the costs.

## 1. S2a: revenue-concept rule (amends v2 §3)

**Where the defect enters.** S2a uses the `GrossProfit` tag when its own TTM period end is at most 183 days old.
Otherwise it falls back to revenue minus cost of revenue. Revenue is the best-ranked listed concept for each period
(`equity.panel.known`); `Revenues` ranks first. For some companies `Revenues` holds a partial line item, which makes
the fallback gross profit wrong. The `GrossProfit` path and H1 never use revenue.

**Trace of the named cases (large-band, quality-ok rows, 2015-2022; all non-financial):**

| Company | Eligible rows | S2a input path | Rows with a conflicting revenue concept |
|---|---:|---|---|
| General Mills | 96 | fallback in all 96 (its `GrossProfit` facts are never fresh) | 19, 2021-06 to 2022-12 (`Revenues` ≈ $2.4bn against ≈ $18bn of sales) |
| Eaton | 96 | fallback in all 96 (no `GrossProfit` tag) | 37, 2015-01 to 2018-01 (`Revenues` zero, negative or tiny) |
| Procter & Gamble | 96 | fallback in all 96 (no `GrossProfit` tag) | 10, 2015-01 to 2015-12 (`Revenues` ≈ $28bn partial line) |
| Flutter (CIK 1635327) | 39 | `GrossProfit` tag 9, no score 30 | 0, but see §3: the CIK belonged to The Stars Group |

Under version 2 as frozen, all 66 conflicting General Mills, Eaton and P&G rows would have entered S2a scores
with a wrong gross profit.

**Rule (deterministic, input-only).** For every period the selected TTM revenue combined, take the largest value
that any listed revenue concept reports for exactly that period, as filed on or before the month-end. If that value
is more than 1.10 times the selected value, or the selected value is not positive, the revenue **conflicts** and the
fallback is **unavailable** for that row (no S2a score unless the `GrossProfit` tag is fresh). The rule never picks
a different concept; it only refuses an inconsistent one.

- Code: `edge_b5_inputs.revenue_check`, applied in `edge_b5.s2a_profitability` (a missing flag counts as a
  conflict).
- Effect on the whole universe: 439 of 10,084 fallback rows (44 companies) become unavailable; the ratio
  distribution and every affected company are listed in the input audit.
- Why 1.10: differences between listed concepts of up to about 10% are usually the same sales measured with or
  without items such as excise taxes (528 fallback rows lie between 1.00 and 1.10). Partial line items sit far
  higher (General Mills 8.9, P&G 2.8). The threshold was set on this input distribution, not on any outcome.
- A negative fallback gross profit with no concept conflict (cruise lines in 2020, for example) is kept: it is real.

## 2. H1: common period end (v2 §2.1 unchanged; made explicit)

- Operating cash flow and capex are each the latest TTM as known at the month-end (`edge_b5_inputs.ttm_input`,
  which reproduces `equity.panel.ttm` exactly) with their own period end.
- **If the two ends differ, FCF and therefore H1 are unavailable for that row.** No alignment to an older common
  end is attempted (`edge_b5_inputs.fcf_inputs`, `align=False`).
- Counts (input audit): the ends differ in 1,546 of 40,217 large-band rows (3.8%; 593 non-financial). An alignment
  step would have recovered only 132 rows that are also fresh; it is not adopted, because v2 requires both inputs
  "as known at t".
- The earlier 650 of 39,273 (v2 §1.1) was measured on the dataset's carried-forward values; the trial uses the
  recomputed per-input values, so 1,546 is the operative figure.
- S2a: a `GrossProfit` value whose own end is more than 183 days old is never used. Such a row uses revenue minus
  cost of revenue only if both share one fresh end and pass §1; otherwise it has no score (input audit: 2,587 stale
  rows, 1,855 fall back, 732 have no score).

## 3. Foreign annual forms (new, both trials)

**Finding.** CIK 1635327 is named Flutter Entertainment in the SEC company file, but for 2018-2020 its filings are
The Stars Group's 40-Fs (former names: Stars Group Inc., Amaya Inc.). The price attached to it comes from ticker FLUT
(Flutter), while the share count is The Stars Group's. So its market cap, its large-band label and any score pair one
company's accounts with another company's price. The revenue jump flagged in TTM check 3 (+55% in 2018) is real:
The Stars Group bought Sky Betting & Gaming in July 2018 (public record, not re-read from the filing), and its
total assets in the SEC data doubled at the same time ($5.4bn to $11.3bn). That case is
therefore resolved as **real revenue, wrong price**.

**Rule.** A company-month whose latest balance sheet known at the month-end came from a 20-F or 40-F (or an
amendment) is **unavailable to both trials**: its share-count units (ordinary shares or ADS) and, as here, its
identity cannot be reconciled with the price on free data.

- Code: `edge_b5_inputs.foreign_form`, applied in `edge_b5.h1_velocity` and `edge_b5.s2a_profitability` (unknown
  counts as foreign).
- Effect: 339 rows, 13 companies. Some are genuine large companies that filed 20-Fs for a time (NXP, Teva, CNH,
  Atlassian, Shopify, CRH, James Hardie); the rest are small companies whose market cap is probably inflated by an
  ADS ratio. The rule costs about 1% of rows and is conservative; the alternative (excluding CIK 1635327 alone) is
  narrower but leaves the ADS-unit risk in place.

## 4. Deflated Sharpe ratio: exact specification (v2 §5 restated, no change)

- `sr`: mean ÷ sample standard deviation (ddof = 1) of the T monthly net excess returns over VWRP/VWRL, where T is
  the number of months with both a portfolio and a benchmark return (`metrics()["excess_months"]`).
- `γ3`: pandas `skew()`, the adjusted Fisher-Pearson G1. `γ4`: pandas `kurt()` + 3, i.e. the bias-adjusted excess
  kurtosis G2 plus 3.
- `N`: every registration with `counts_for_dsr` (100 now), whether or not it has a result.
- `V`: max(sample variance, ddof = 1, of the comparable Sharpes; 1/T). **Comparable** = results of counted trials
  whose statistic is `portfolio_excess_vs_vwrp` and whose `sr_monthly` is finite. Inherited Stage 2 results
  (another statistic), non-finite values and robustness runs (not counted) never enter V. With fewer than two
  comparable results V = 1/T.
- Edge cases: N ≤ 1 gives SR0 = 0; the denominator term is floored at 1e-12; a missing DSR fails P2.
- Independent check: `research/tests/test_edge_dsr_independent.py` re-derives every step with its own normal
  functions and estimators and matches the implementation to 1e-9, reproduces the v2 table (SR0 0.2610; DSR 0.80 at
  sr 0.3509, 0.3596, 0.3693 and at 0.4609 with V = 2/94; 0.68 at t = 3) and checks the 0.80 gate.

## 5. Evidence definitions (v2 §4 and §7 made exact)

- **Net excess** (P4-P11): the arithmetic mean of the monthly net excess returns of that run; "> 0" means this
  mean is above zero. P5 uses the primary's monthly return minus the equal-weighted eligible universe's (same
  execution, zero cost).
- **Thirds** (P10): the T excess months in date order, split into three consecutive blocks by `numpy.array_split`
  (sizes differ by at most one, earlier blocks larger); each block's mean.
- **Largest contributor** (P11): each company's contribution in a tranche is the sum over its holding periods of
  (gain in USD ÷ NAV at the start of the period), a period ending at the next rebalance, a missing-price exit or the
  last valuation (`edge_backtest.Result.contrib`). The company with the largest total across all tranches of the
  primary run (ties: lower CIK) is removed from every month's eligible set and the trial rerun; its net excess must
  stay > 0.
- **FF5 + momentum alpha** (P3): OLS of the combined monthly USD return less RF on Mkt-RF, SMB, HML, RMW, CMA
  (Ken French `F-F_Research_Data_5_Factors_2x3`) and Mom (`F-F_Momentum_Factor`), months matched by calendar month,
  factors cut at 2022-12; Newey-West (Bartlett) standard error with no small-sample correction at the trial's lag
  (H1 3, S2a 12); fewer than 24 months fails. Matches statsmodels' HAC to 1e-8 in the tests.
- **Robustness drivers** (P4-P9; `edge_b5_stats.robustness_variants`), each one change from the primary: P4 cost x2;
  P5 equal-weighted eligible universe at zero cost; P6 missing return −100%; P7 next-month-close execution; P8 the
  12 registered data-error company-months barred from new purchases (held names kept); P9 quality flag with the
  point-in-time share-count median.

## 6. Independent-source check (TTM check 4) blocks E2 (supersedes v2 §8, first bullet)

- Check 4 is **open** (`research/edge/status.json`, `ttm_check4_independent_source.complete = false`). Only the
  owner records it complete.
- While it is open, **no result may carry the E2 label.** A result that passes every gate is labelled "gates passed;
  E2 label withheld (TTM check 4 open)" (`edge_b5.verdict`).
- While it is open, **no confirmation pre-registration can be registered**: `edge_registry.append` refuses a batch
  event.
- Passing the exploratory gates is **not** evidence that survivorship bias is bounded, and **not** evidence of an
  investable edge.

## 7. Missing-price paths: what has and has not been exercised

- The engine's two missing-price paths (a held name losing its price exits at the last valid price less 30%; a new
  name without a usable execution price is skipped and the next name takes the slot) are exercised through
  `edge_backtest.run` by the B2 synthetic tests (`test_7_*`, for missing, invalid and absent prices) and by a test
  under the frozen B5 configuration (`test_missing_price_exit_and_skip_under_the_frozen_b5_portfolio_rules`).
- **The real-data placebo hand-check did not exercise either path**: it recorded 0 missing-price exits in all 15
  tranches, and no missing-price skip occurred at its fixed check dates. On real data these paths are tested only
  synthetically.

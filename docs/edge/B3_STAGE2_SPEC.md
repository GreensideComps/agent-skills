# B3: frozen Stage 2 specification and assumption comparison

Written and committed on 2026-10-15, before any B3 computation. The owner approved B3 at 14:28Z, limited to
reproducing the existing Stage 2 results through the new backtesting engine.

This document fixes three things in advance:

1. what "the Stage 2 result" is;
2. how the new engine is set up to reproduce it;
3. what is compared afterwards.

Nothing here may be changed after results are seen. A failed reproduction is investigated, not tuned (owner
requirement 4).

## 1. What is reproduced

| Item | Value |
|---|---|
| Published result | `equity/reports/research/stage2_signals.json` and `.md` (commit c1d9429, 2026-10-14 16:43Z) |
| Published result sha256 | `3fa6ebf5a6e3cad1676f79b30c686506ed93f236f4b0b8ba632eef76c52916f4` |
| Pre-registration | `research/prereg/stage2.md` (sha256 `a70cf184…1c9a43`) |
| Code | `research/stage2.py` (sha256 `44919151…436bc`; since c1d9429 only a refactor that moves feature-building into `build_features`, with the same calls in the same order) and `research/xsection.py` (sha256 `a4f265ce…f16`, unchanged since Stage 1) |
| Trials | All 15 run trials: S1a, S1b, S2a, S2b, S3a, S3b, S4, S5a, S5b, S6a, S6b, S6c, S7a, S7b, S9 |
| Band | Large (market cap ≥ $10bn), the band Stage 2's verdicts use |
| Window | Decisions 2015-01-31 to 2022-11-30; returns to 2022-12-31 |
| Quantity | The **top-quintile result**: each month, the equal-weighted next-month return of the top quintile, minus the equal-weighted next-month return of the universe, less the cost term (below); summarised as an annualised mean (× 12) |

## 2. The original Stage 2 assumptions, exactly

| Element | Stage 2 rule (`xsection.evaluate`) |
|---|---|
| Data files | Listed under "Data files and hashes" below |
| Universe | Every company-month with `close_raw` ≥ $1 and a size band, **and a known next-month return** (`ret_next` not missing), within the large band, with a score. A month with fewer than 30 such names is skipped. |
| Market cap | Cover-page shares outstanding (diluted if missing) × `close_raw`. No data-quality (share-count) exclusion; that rule came later, in Phase A. |
| Ranking | `pd.qcut(score.rank(method="first"), 10)`. Ties are broken by row order, which is CIK ascending after `stage2.prepare`. |
| Portfolio | Top quintile = deciles 8 and 9 (top 20% by score) |
| Weighting | Equal weight |
| Rebalancing | Monthly, in full; no buffer, no sector cap |
| Execution | **At the decision month-end close.** The return is the month-end-to-month-end dividend-adjusted close (`adjclose`, research dataset), not a next-day price. |
| Benchmark | The equal-weighted universe above (same month, same filter), at no cost. Not VWRP. |
| Transaction cost | `net = q5_minus_univ − 2 × 0.0030 × name_turnover`. `name_turnover` is the number of new names in the top quintile divided by its size (1.0 in the first month). The cost is charged on the excess, not compounded into a NAV. |
| Missing prices | None needed: a name without a next-month return is never in the universe, because the filter above uses the next month's price. **This uses information from after the decision.** It is a known feature of the Stage 2 harness, recorded here and not changed. |
| Currency | USD; no FX |

## 3. How the new engine is set up to reproduce it

**Comparison of assumptions.** The engine's native assumptions differ from Stage 2 in four places:

| Element | Stage 2 | Engine native (B2) | Equivalent setting used for the reproduction |
|---|---|---|---|
| Execution | decision close | next trading day's close (`next_day_close`) | New convention `decision_close`: trade at the month-end `adjclose` of the decision month. Allowed only for this reproduction, and refused by `run_trial`. |
| Universe | requires a known next-month return | no look-ahead; a held name that loses its price exits at −30% | The panel passed in is Stage 2's investable set, so the same look-ahead applies. No missing-price case can arise. |
| Selection | top 20% by `qcut` of ranks | top N by score, with buffer and sector cap | New selection `stage2_top_quintile`: Stage 2's `qcut` rule on the eligible frame in the same row order. Buffer and cap are off. |
| Cost | `2 × 0.003 × name_turnover`, off the excess | Σ \|Δweight\| × band rate, off NAV | Engine run at **zero cost**. Stage 2's cost formula is then applied to the engine's own holdings, because the two formulas are not the same quantity. |

**Everything else matches:**

- equal weight;
- monthly rebalance;
- large band;
- $1 minimum price;
- no quality filter;
- USD (FX rate fixed at 1).

**Comparisons, each at the owner's 1e-6 tolerance:**

1. **Original code on cut data vs published.**
   - Stage 2's own `xsection.evaluate`, run now on data cut at 2022-12-31, against the published JSON.
   - Fields: `months`, `avg_names`, `mean_ic`, `q5_minus_univ_ann_gross`, `q5_minus_univ_ann_net`, `q5_turnover_monthly`.
   - Tolerance: 1e-6 absolute; `months` must be equal.
2. **Engine vs original code, monthly.** For every trial and month:
   - top-quintile gross return;
   - universe return;
   - `q5_minus_univ`;
   - name turnover;
   - `q5_net`.

   Tolerance: 1e-6 absolute, month by month, plus the annualised mean. Holdings must be identical sets.
3. **Pass.** All 15 trials pass both comparisons.

**If either comparison fails:** stop, investigate and report the cause. No parameter is changed to obtain a pass.

## 4. Separate comparison: next-day execution

Reported separately and labelled. It is not a reproduction, and it is not a new signal: same 15 Stage 2 scores,
same top-quintile rule, same equal weight and monthly rebalance. Three things change:

- **Execution:** at the first NYSE trading day's close after the month-end (B1 file, `next_day_close`).
- **Universe:**
  - no look-ahead; `ret_next` is not required;
  - a name with no usable execution price can't be bought;
  - a held name that loses its price exits at its last valid price less 30% (`edge_rules.holding_return`).
- **Cost:** the engine's native Σ \|Δweight\| × 0.30% (large band: FX 0.15% + spread 0.15%). The same rate per
  unit traded as Stage 2, but on weight changes, including drift.

The benchmark leg is the equal-weighted universe under the same execution, at zero cost, as in Stage 2.

Reported per trial: annualised top-quintile minus universe, net, next-day vs Stage 2, and the difference. No pass
or fail rule applies; it shows how much the execution assumption matters.

## 5. Data cut

- Every input is cut to dates on or before 2022-12-31 immediately after reading, before any feature, return or
  score is computed:
  - prices by `month`;
  - metrics by `month`;
  - insider trades by `filed`;
  - Ken French factors by month.
- The original `xsection.load` then runs on the cut copies.
- No 2023 or later row is ever held in a frame used for computation.
- The reproduction code is checked by the data-access guard test.

## 6. Data files and hashes (recorded before the run)

| File | sha256 |
|---|---|
| `/mnt/project-files/research-data/monthly_metrics.csv.gz` | `ae5429b661bd060d040109138d35cb4ea22356d4a549056c8616c3a2a7e87561` |
| `/mnt/project-files/research-data/prices_monthly.csv.gz` | `505115711f7ef59c8df417671f8afecf77dd2240e13a2a3bdff453721b3d801a` |
| `/mnt/project-files/research-data/sec_companies.csv.gz` | `acf5e3f746c355aa2c0aa2b76c0c3f55413daf5e927524672537d0389d214a90` |
| `/mnt/project-files/research-data/insider_trades.csv.gz` | `82e99ff117d2ec0c2a33aeb0dd9f412b897aa3ced936e4e1e07e19bcdef8c676` |
| `research/data/french/F-F_Research_Data_Factors.csv` (S6c only) | `d7d7fe37b150b5b15c9c069b3ba101dfe1af568c6d7b5db6e73cd0a6c0c9e5e5` |
| B1 `exec_prices_to_2022.csv.gz` (section 4 only) | `dd6608f62ae2676fd4fd5b3b256105d5f52eb720ba3a10a2965cf504e17d47dc` |

**File dates against the Stage 2 run (c1d9429 at 16:43Z on 2026-10-14):**

- monthly_metrics: 15:55Z, before the run.
- prices_monthly: 16:23Z, before the run.
- insider_trades: 16:34Z, before the run.
- The Ken French factor file was re-downloaded at 19:20Z, after Stage 2 ran. If S6c alone disagrees, a revision of
  the factor history is the first thing to check. The file is not changed to force agreement.

## 7. Registration

Registered before running, as non-counting diagnostics (`counts_for_dsr: false`):

- `B3-REPRO-STAGE2`: sections 3 and 5.
- `B3-NEXTDAY-STAGE2`: section 4.

No new signal is registered or run. No confirmation test. No holdout data.

# B5 pre-registration: H1 and S2a exploration trials (version 2, frozen, not run)

- **Version 1** was written and registered on 2026-10-16 before 11:53Z: `B5-H1-FCFPS-ACCEL`, `B5-S2A-GP-12M`.
- **Version 2** answers the owner's review of 2026-10-16 11:53Z. It was written before any H1 or S2a score,
  ranking, return or NAV was computed.

**What version 2 changes:**

- the exact H1 formula;
- per-input freshness for both trials (a finding of the TTM checks);
- capex is required for H1;
- tranche combination;
- the exact DSR;
- the survivorship wording;
- costs;
- trial controls.

**Registration:** version 2 is registered as `B5-H1-FCFPS-ACCEL-V2` and `B5-S2A-GP-12M-V2`. They supersede
version 1, which will never run. The version-1 ids stay counted in N, which is conservative: N becomes 100.

**Integrity:** the sha256 of this file is recorded in the registry entries. After a trial runs, nothing here
changes; a variant is a new, counted trial.

**Scope (unchanged):**

- Exploration only; every input is cut at 2022-12-31 on read.
- No confirmation test. No holdout data. No demo allocation.
- No change to the real ISA, holdings or trading configuration.
- `backtester_validated` covers exploration only (D12). Survivorship bias is accepted for exploration only (D13).
- **Neither trial runs without the owner's separate approval.**

## 1. Common portfolio rules (both trials)

| Element | Rule |
|---|---|
| Data | `monthly_metrics`, `prices_monthly`, `sec_companies`, `sec_facts_panel` (for each TTM input's own period end, §1.1); B1 execution prices, FX and benchmarks. Hashes are checked at run time; any change stops the run. |
| Point in time | Each row holds what was filed on or before its month-end. A value for t−12 or t−24 is that month's row, **as filed then** (`stage2.lag`), never a later restatement. SIC is today's (a stated limitation). |
| Universe | Large band (market cap ≥ $10bn = the market-cap share count × `close_raw`); `close_raw` ≥ $1; Phase A quality rule (D5); financials (SIC 6000-6799) excluded; score present. No next-month return is required. |
| Ranking | Score descending; ties by CIK ascending. |
| Portfolio | 20 names, equal weight, long only, no leverage. Buffer 2.0: a holding ranked up to 40 is kept while there is room. Sector cap 4 names per SIC group. |
| Execution | The next NYSE trading day's close after the decision. A new name without a valid execution price is skipped and the next name takes the slot. |
| Missing prices | A holding that loses its price exits at its last valid price less 30%; the cash earns 0% until the next rebalance. |
| Costs | §6. |
| Currency | USD to GBP with the B1 GBPUSD series (on or before the date, within 7 days). |
| Tranches | Staggered tranches (§2, §3) start in 2014. At the evaluation start (the execution after the 2015-01-31 decision), each tranche gets equal capital. The combined NAV is the mean of the tranche NAVs, each rebased to 1 at that date, and capital is **not** rebalanced between tranches, so no trading cost is hidden (`edge_b5.combine_tranches`). |
| Evaluation window | 94 monthly periods, between the executions after the 2015-01-31 and 2022-11-30 decisions. |
| Engine | `edge_backtest.run_trial` with `Config(n=20, weighting="equal", buffer=2.0, sector_cap=4, bands=("large",), min_price=1.0, cost_mult=1.0, missing_return=-0.30, convention="next_day_close", selection="top_n")`. |

### 1.1 Per-input freshness (new in version 2)

The TTM checks found a problem with freshness (`ttm_checks.md`):

- **The dataset's single `ttm_end` is revenue's period end.** Other TTM inputs can come from older periods.
- **The builder carries a value forward.** Once filed, a value can stay in place after its period is more than 18
  months old.

Among large-cap rows in 2015-2022:

- operating cash flow and capex have different period ends in 650 of 39,273 rows (1.7%);
- gross profit is more than 183 days old in 1,214 of 16,358 rows (7.4%).

So version 2 requires **each input's own period end**, recomputed from the SEC facts with `equity.panel.ttm`
(the recomputation reproduces every dataset value exactly):

- the period end must be on or before the decision month-end, and at most 183 days before it;
- inputs used together must share one period end.

## 2. H1: accelerating free cash flow per share

**Hypothesis (programme doc):** investors anchor on past growth, so they underreact when per-share cash
generation speeds up.

**Disclosed prior looks:**

- `M8-AUDIT-fcf_per_share`, the origin of H1: t = 2.9, pooled over cohorts including the holdout.
- `M8-T1`.

Both are counted in N (D4). A later holdout test of H1 is weaker for it (D3).

### 2.1 Definition, for company i at decision month-end t

All money values are **USD**, as reported in XBRL. A company that reports in another currency has no money values
and gets no score. TTM means trailing twelve months (`equity.panel.ttm`): the latest fiscal year, plus the
current year-to-date, minus the prior year's same year-to-date.

| Symbol | Definition |
|---|---|
| `OCF_t`, `CAPEX_t` | TTM operating cash flow and TTM capital expenditure (payments for property, plant and equipment, reported as positive amounts), each as known at t |
| `e_t` | Their common TTM period end. Both must exist and share one period end, and t − 183 days ≤ `e_t` ≤ t. Otherwise there is no score. **Capex is required**; version 1 treated missing capex as 0. |
| `FCF_t` | `OCF_t − CAPEX_t` (USD) |
| `Sh_t` | The market-cap share count: cover-page shares outstanding if positive, else the latest weighted-average diluted count |
| `TA_t` | Total assets, latest balance sheet known at t; must be > 0 |
| `k_t` | `close_raw_t / adjclose_t` (unadjusted over split-and-dividend-adjusted close) |
| `s_t` | `k_(t−12) / k_t`, set to exactly 1 when \|ln `s_t`\| ≤ ln 1.25. A 2-for-1 split between t−12 and t gives 2. Adjustments after t multiply both k's and cancel, so only events in (t−12, t] enter. The snap absorbs dividend drift in `adjclose`. |
| `q_t` | `Sh_t / (Sh_(t−12) × s_t)`: split-neutral growth in the share count over the year. No score if \|ln `q_t`\| > ln 3 (a merger, spin-off or share-count error, not per-share growth). |

**Velocity (one year's change in per-share FCF):**

`G_t = (FCF_t − q_t × FCF_(t−12)) / TA_t`

This equals `(FCF_t/Sh_t − FCF_(t−12)/(Sh_(t−12) s_t)) / (TA_t/Sh_t)`: the change in split-neutral FCF per share
over the year, divided by assets per share today.

It requires, in addition:

- a t−12 row with `FCF_(t−12)` meeting the same rules at its own month-end;
- 350 ≤ `e_t − e_(t−12)` ≤ 380 days, so the two TTM periods are a year apart.

**Score:** `H1_t = G_t − G_(t−12)`. Here `G_(t−12)` is computed at t−12 by the same formula, with its own
`q_(t−12)`, `TA_(t−12)` and the share-change guard, from rows as filed at t−12 and t−24. It requires
350 ≤ `e_(t−12) − e_(t−24)` ≤ 380 days. Higher is better. Financials have no score.

### 2.2 Why this measures acceleration

Write `F` for split-neutral FCF per share, and hold assets per share at `A`. Then:

- `G_t = (F_t − F_(t−12)) / A`, the first difference of per-share FCF over the latest year;
- `G_(t−12) = (F_(t−12) − F_(t−24)) / A`, the same over the year before;
- `H1_t = (F_t − 2F_(t−12) + F_(t−24)) / A`, the discrete second difference.

So H1 is positive when per-share FCF grew by more in the latest year than in the year before (acceleration), zero
under constant growth in amount, and negative under deceleration.

- Scaling by assets per share keeps price (valuation, momentum) out of the score and puts companies of different
  size on one scale.
- When assets change, each year's change is scaled by that year's assets: H1 measures acceleration in
  asset-scaled per-share FCF. This is stated rather than hidden.

**Tested on synthetic data** (`tests/test_edge_b5.py`, 17 tests):

- constant growth scores 0; acceleration scores positive; deceleration scores negative;
- an exact hand calculation;
- a 2-for-1 split leaves the score unchanged;
- dividend drift is not read as a split;
- buybacks: per-share FCF uses split-neutral shares;
- a share change over 3x gives no score; stale, mismatched or year-gapped periods give no score; missing capex
  gives no score;
- later rows never change an earlier score;
- financials get no score, and row order is preserved.

A mutation check (five deliberate bugs, one at a time) made the tests fail every time.

**Ranking and rebalance:**

- Raw cross-section, not sector-neutral; the cap limits concentration.
- Quarterly rebalance. Three tranches, starting at the 2014-11-30, 2014-12-31 and 2015-01-31 decisions.

## 3. S2a: gross profitability, held for 12 months

**Hypothesis:** profitable firms earn higher returns, slowly. The Stage 2 diagnostic's IC strengthened with
horizon (12-month t 1.8, a lead only). Stage 2 rebalanced monthly; this trial tests the 12-month holding.

**Disclosed prior looks:** `S2-S2a`, `DIAG-S2a-h3`, `DIAG-S2a-h6`, `DIAG-S2a-h12`, `QX-S2a` and `QX-PIT-S2a`, all
counted. The programme doc's 2023-26 factor table is a recorded holdout exposure (it affects a future
confirmation, not exploration N).

**Score:**

- Gross profitability = gross profit / total assets (> 0).
- Gross profit is TTM `GrossProfit` when its own period end is at most 183 days old. Otherwise it is TTM revenue
  minus TTM cost of revenue, when both share one period end at most 183 days old. Otherwise there is no score.
- The score is the percentile rank within SIC group among the month's eligible large-band names, financials
  excluded (`edge_b5.s2a_profitability`, `s2a_score`).

**Rebalance:** every 12 months. Twelve tranches, starting at each decision month from 2014-02-28 to 2015-01-31.

**Known data issue (TTM check 3):** for some companies the top-ranked revenue concept is a partial line item
(General Mills, Eaton). This affects S2a's fallback. It cannot be sized without an independent source (§8).

## 4. Benchmarks and statistics (both trials)

- **Primary benchmark:** VWRP in GBP, labelled by segment: VWRL-based to 2019-07, actual VWRP from 2019-08.
- **Primary statistic (`portfolio_excess_vs_vwrp`):** each month, the combined net GBP return minus the benchmark
  return. T is the number of such months (94 if every benchmark value exists). The code now uses this count for
  the DSR, not the count of NAV months (a fix in this version).
- **t-statistic (P1):** mean excess over its Newey-West standard error:
  - Bartlett weights;
  - 3 lags for H1;
  - 12 lags for S2a, because overlapping 12-month tranches make monthly excess autocorrelated.

  For S2a, also every 12th month alone (non-overlapping).
- **Reported for each trial, whatever the outcome:**
  - CAGR, volatility, Sharpe, drawdown;
  - tracking error, information ratio, share of months ahead, relative drawdown, worst rolling 12 months;
  - excess over the equal-weighted eligible universe (same execution, zero cost);
  - FF5 + momentum alpha of the USD return less the risk-free rate (same Newey-West lags);
  - turnover, concentration, missing-price exits, skipped entries;
  - sub-period thirds; the result without the largest contributor;
  - DSR (§5); every robustness result;
  - the standing limitations.

## 5. Deflated Sharpe ratio (exact)

`edge_registry.deflated_sharpe`, Bailey and López de Prado (2014).

**Inputs:**

- `sr`: the monthly Sharpe of excess returns, mean / standard deviation (sample, ddof = 1), over T months.
- `γ3`: skewness (pandas `skew`).
- `γ4`: raw kurtosis (pandas `kurt` + 3).
- `N`: `edge_registry.n_trials()` at the time of evaluation.
- `V`: max(sample variance of the comparable Sharpes, 1/T). The comparable Sharpes are counted trials whose
  results measure `portfolio_excess_vs_vwrp`. 1/T is the variance of a Sharpe estimate under the null; with fewer
  than two comparable results, `V` = 1/T.

**Formula:**

`SR0 = √V × ((1 − γ) Φ⁻¹(1 − 1/N) + γ Φ⁻¹(1 − 1/(N e)))`, with γ = 0.5772 (Euler-Mascheroni).

`DSR = Φ( (sr − SR0) √(T − 1) / √(1 − γ3 sr + (γ4 − 1)/4 sr²) )`

**Timing (frozen):** both trials' results are recorded first. Then both DSRs are computed from the same registry
state, so neither trial's DSR depends on which ran first. With two comparable results,
`V = max(var(sr_H1, sr_S2a), 1/T)`.

**Correlated trials:**

- Every counted registration adds 1 to N, however correlated; there is no effective-N reduction. This overstates
  N and raises `SR0`, so the test is stricter.
- Robustness runs never count and never enter `V`.
- Inherited trials count in N, but their Sharpes measure a different statistic (Stage 2's top quintile minus the
  universe), so they do not enter `V`.

**N = 100, reconciled against the registry (`edge_registry.n_trials` = 100 after the version-2 registration):**

| Registry ids | Kind | Counted |
|---|---|---:|
| `S2-S1a` … `S2-S9` (Stage 2) | inherited | 15 |
| `M8-T1`, `M8-AUDIT-*` (5 sub-scores) | inherited | 6 |
| `DIAG-*` (15 signals × 3, 6 and 12 months) | diagnostic | 45 |
| `QX-*` (15 quality-rule) and `QX-PIT-*` (15 point-in-time) | diagnostic | 30 |
| `B5-H1-FCFPS-ACCEL`, `B5-S2A-GP-12M` (version 1, superseded, never run) | trial | 2 |
| `B5-H1-FCFPS-ACCEL-V2`, `B5-S2A-GP-12M-V2` | trial | 2 |
| **Total** | | **100** |

**Not counted:**

- 24 diagnostics: B1/B3 checks, the version-1 and version-2 robustness runs, the hand-check;
- 4 inherited holdout exposures and 1 exposure: they bear on the holdout's cleanliness (D3), not on exploration
  N.

**What the 0.80 threshold means, exactly.** N = 100, T = 94 and V = 1/94 give `SR0` = 0.2610 (monthly). The
monthly Sharpe at which DSR = 0.80:

| Return shape | Monthly sr needed | Annualised | Same as an iid t (sr √T) of |
|---|---:|---:|---:|
| Normal (γ3 = 0, γ4 = 3) | 0.3509 | 1.22 | 3.40 |
| Mild negative skew (−0.5, 4) | 0.3596 | 1.25 | 3.49 |
| Strong negative skew, fat tails (−1, 6) | 0.3693 | 1.28 | 3.58 |
| Two comparable results with V = 2/94 | 0.4609 | 1.60 | 4.47 |

- At t = 3.0 exactly (normal), DSR = 0.68, which fails P2.
- Version 1's "roughly t ≥ 3.6" was loose; the table replaces it.
- **The gate is the DSR computed from the trial's own sr, skew, kurtosis, T, N and V.** The t-equivalents only
  illustrate it. P1 uses a Newey-West t, which can differ from sr √T when returns are autocorrelated.

## 6. Costs (reconciled)

**The rate:** one way, per unit of portfolio weight traded = FX fee 0.15% + spread by band.

- Large: 0.15% spread, so **0.30% in total, FX included**.
- Mid: 0.45%. Small or unknown: 0.75%.
- No stamp duty on US shares.

**Where it applies (`edge_backtest.run`), at each rebalance:**

- cost = Σ over names of |target weight − drifted weight| × rate, taken from NAV before the new positions;
- buys and sells each pay the one-way rate, so replacing one 5% holding costs 2 × 5% × 0.30% = 0.03% of NAV;
- building the first portfolio from cash costs 0.30%;
- drift is measured from execution prices, so drift-only rebalancing is charged;
- the reported turnover is Σ\|Δw\| / 2.

**Band rule:**

- the name's band at the decision;
- if unknown at that decision (no price or share count that month), the band it was held in;
- otherwise the small-cap rate.

The hand-check found that the engine charged the small-cap rate when a held name's band was unknown. That is now
fixed, with a regression test.

**Missing-price exits** pay no separate cost: the −30% mark-down stands in for the exit; the cash is charged when
reinvested.

**Benchmarks:**

- VWRP is held buy-and-hold with no trading cost (its fund costs are in its price).
- The equal-weighted universe is at zero cost, as in Stage 2.
- No cost between tranches (§1).

**Robustness runs:**

| Run | Cost treatment |
|---|---|
| 2x | Every rate exactly doubled (0.60% large) |
| 3x | Every rate tripled; reported alongside 2x, not a gate |
| −100% missing price, next-month-close, data-error, point-in-time quality | 1x, same formula |

This is the same rate per unit traded as Stage 2's 0.30% (its `2 × 0.003 × name turnover`), applied to weight
changes including drift.

## 7. Exploratory decision rules (frozen; code: `edge_b5.verdict`, `edge_b5.GATES`)

A positive return alone is not a pass. **"E2 candidate" requires every condition:**

| # | Condition |
|---|---|
| P1 | Newey-West t of net excess vs VWRP/VWRL ≥ 3.0 at 1x costs; for S2a also the non-overlapping t ≥ 2.0 |
| P2 | DSR ≥ 0.80, computed exactly as §5 with the full N |
| P3 | FF5 + momentum alpha > 0 with t ≥ 2.0 |
| P4 | Net excess > 0 at 2x costs |
| P5 | Net excess over the equal-weighted eligible universe > 0 |
| P6 | Net excess > 0 with missing prices at −100% |
| P7 | Net excess > 0 under next-month-close execution |
| P8 | Net excess > 0 with the 12 suspected data-error company-months barred from purchase (`B1-SENS-DATA-ERRORS` rule) |
| P9 | Net excess > 0 under the point-in-time (expanding-median) quality rule |
| P10 | Net excess > 0 in at least 2 of 3 sub-period thirds |
| P11 | Net excess > 0 without the single largest contributing company |

**Outcomes:**

- **E2 candidate:** all conditions hold. It allows only a draft confirmation pre-registration for review.
- **Lead, not a pass:** 2.0 ≤ t < 3.0 with P3-P11 holding. Recorded; nothing follows without a new, counted,
  approved trial.
- **Fail:** anything else. A missing input counts as a fail.

**Controls:**

1. **Frozen and registered before execution.** Both trial specifications, every robustness run and the hand-check
   are registered. The registry records this file's sha256; `edge_registry.require` refuses an unregistered trial
   or a second result.
2. **Robustness can only veto.** P4 and P6-P9 are separate registered diagnostics (`counts_for_dsr: false`).
   `edge_b5.verdict` uses them only as extra conditions and never in place of the primary. A test checks that
   strong robustness cannot turn a t of 2.9 into a pass, and that one failed robustness check fails the trial.
3. **Prior looks are handled one way.** Every relevant prior look on 2015-2022 data counts in N, whatever its
   source (§5 table, §2 and §3 disclosures). Holdout exposures are recorded separately and weaken any future
   confirmation (D3).
4. **No reruns or tuning.** Both results are reported. Before a run, only bug fixes may change code, and none may
   change a definition here.

**Power:** with 94 months and tracking error of 5-8% a year, t ≥ 3.4 needs an annual excess of roughly 6-9%.
Smaller real edges will not be detected.

## 8. Survivorship and accounting limits on interpretation

**Survivorship (D13):**

- Companies that delisted before the 2026 price download are **missing from the universe entirely**.
- The −30% and −100% missing-price rules (P6) apply only to companies in the data that later lose a price. They
  **do not address companies missing from the universe, and are not evidence that survivorship bias is
  bounded.**
- This is a material limitation. Every report states it (`edge_rules.STANDING_LIMITATIONS`, enforced by
  `require_disclosure`).

**Independent-source check (TTM check 4) is open.** Checks 1-3 test the TTM arithmetic and data handling against
the same SEC filings. They cannot catch a wrong concept choice or a filing error; check 3 shows concept errors
exist. So:

- **It does not block an exploration result being reported**, including the label "E2 candidate".
- **It blocks E2 from leading anywhere.** An E2 label from these trials is provisional. No confirmation
  pre-registration may be submitted until check 4 is done for that trial's inputs (operating cash flow, capex and
  total assets for H1; gross profit, revenue, cost of revenue and total assets for S2a), or the owner explicitly
  accepts the gap for that step.

## 9. Registered ids (version 2)

| Id | Kind | Counts |
|---|---|---|
| `B5-H1-FCFPS-ACCEL-V2`, `B5-S2A-GP-12M-V2` | trial | yes |
| `B5-H1-V2-ROB-{2XCOST, MISS100, NEXTMONTH, DATAERR, PITQ}` | diagnostic | no |
| `B5-S2A-V2-ROB-{2XCOST, MISS100, NEXTMONTH, DATAERR, PITQ}` | diagnostic | no |
| `B5-HANDCHECK` | diagnostic (placebo implementation check, done) | no |

Version-1 ids remain registered, superseded and never to be run.

## 10. Remaining blockers before either trial runs

1. **The owner's approval** of version 2 and of running B5.
2. **The run script:**
   - TTM period ends per input from the SEC facts (§1.1);
   - FF5 + momentum alpha on the combined USD NAV;
   - the leave-one-company-out and sub-period summaries;
   - the robustness drivers.

   Each is tested on synthetic data before real use. The pieces already built and tested: the H1 and S2a scores,
   tranche combination, the placebo score, the Newey-West t and the verdict.
3. **TTM check 4** (independent source) is open; it limits interpretation as stated in §8 but does not block
   running.
4. **PR #19** is reviewed and merged by the owner (no CI; tests run locally).

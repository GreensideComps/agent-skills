# Edge-discovery programme: statistical and portfolio evaluation rules

Status: written 2026-10-14 (Phase A). The owner decided the items marked **(owner)** on 2026-10-14 (`DECISIONS.md`).
Applies to every new trial in the programme. Stage 2, its pass rules and the monthly signal log are unchanged.
Items marked **(to build)** do not exist in code yet.

Each section names the existing code it reuses, so a rule here and its implementation can be checked together.

## 1. Universe

- US SEC filers with a filing in the last 15 months, a USD price of at least $1, and a point-in-time market cap
  (cover-page shares x unadjusted close). Bands: large ≥ $10bn, mid $2-10bn, small $0.3-2bn
  (`xsection.SIZE_BANDS`). **Large caps decide; mid and small are exploratory only** until survivorship-free prices
  exist.
- **Data-quality exclusion (owner, D5: retained):** company-months flagged by `edge_split.quality_flags` are
  excluded: an adjusted close ≤ 0, or a share count over 10x or under 1/10 of the company's median. The second flag
  catches XBRL scaling errors (for example 1.9e14 shares) that put small companies in the large band; it also
  drops some genuine IPO and issuance months.
  - **Computed on period-cut data only** (`edge_split.with_quality(cut_exploration(...))`). The median is taken
    over the rows given, so on the full dataset it would use 2023-26 share counts: 626 banded exploration rows
    would flip.
  - Within exploration the median still uses later 2015-22 rows. This is a mild look-ahead in which rows are
    excluded, not in any return.
  - **Scope:** features are computed on every row, and the flag then removes company-months from the eligible
    universe, as a universe filter would.
  - **Effect measured:** 253 of 43,220 large-cap company-months in 2015-22 are flagged. Applying the exclusion
    moves no Stage 2 large-cap IC by more than 0.003, and no conclusion changes
    (`equity/reports/research/edge/stage2_quality_sensitivity.md`).
  - Stage 2 itself and the signal log do not apply it.
- Every result states: survivor bias on prices (no delisted company is priced); one ticker per company (the first in
  today's SEC list); SIC is today's, not point in time.

## 2. Timing

- Decisions at month-ends. Features use only data filed on or before the decision date
  (`equity/monthly.py`; checked by `edge_integrity`: 0 rows use a later filing).
- Outcomes are total returns from the decision close (`adjclose`), over 1, 3, 6 and 12 months
  (`edge_split.forward_return`; all h months must exist).
- Exploration code starts from `edge_split.cut_exploration` (rows and `ret_next` cut at 2022-12, before features
  or flags) and `edge_split.exploration_view` (forward returns). Factor, FX and benchmark series go through
  `edge_split.cut_series`. Boundaries: `SPLIT_POLICY.md`.
- A test (`test_new_research_code_reads_data_only_through_the_guard`) fails if a new module in `research/` reads
  the dataset directly instead of through these.
- Price rows labelled after the data's fetch date are an unfinished month. The builder labels them with the
  month-end, so a row dated 2026-10-31 that was fetched on 2026-10-14 holds the 14 October price.
  `edge_split.complete_months` drops them before any return is computed.

## 3. Signal-level tests (does a score rank returns?)

For each band and horizon h in {1, 3, 6, 12} months:

| Statistic | Definition | Code |
|---|---|---|
| IC | Spearman correlation of score and h-month return, each month, months with ≥ 30 names | `stage2_diagnostics.run` |
| IC t | Mean IC / Newey-West standard error with **max(3, h) lags**: monthly decisions with h-month outcomes overlap by h−1 months | `stage2_diagnostics.ic_stats` |
| Non-overlapping t | The same on every h-th decision only; reported beside the NW t. If they disagree, the smaller one is used | `ic_stats` |
| MDE | 2 x NW standard error: the mean IC that would have reached t = 2 with the noise observed. A null result with an MDE above 0.02 is "not detected", not "ineffective" | `ic_stats` |
| Spread | Top-minus-bottom decile return, per month of holding, NW t | `stage2_diagnostics.run` |
| Factor alpha | Fama-French 5 factors + momentum regression of the decile spread and of the top-quintile-minus-universe return, NW t on alpha (3 lags at 1 month, h lags otherwise) | `stage2.factor_alpha` (verified by a planted-alpha test in Phase A) |
| Robustness | Sub-period thirds; market up and down months; sector groups; mid and small bands | `stage2.run`, `stage2.by_group_ic` |

A signal "adds alpha beyond known factors" only if its factor alpha has the same sign as its spread, with t ≥ 2.
A signal that only loads on HML, RMW, CMA or Mom is a factor, not an edge.

## 4. Strategy-level tests (would a portfolio have beaten VWRP?) (to build: Phase B)

The existing xsection harness tests an equal-weighted top quintile of about 100 large caps, rebalanced monthly. That
is a weak model of the concentrated portfolio the owner would hold. Phase B builds a minimal backtester with:

- **Rules, each variant a registered trial:** 15 to 30 names; equal, score or inverse-volatility weights; quarterly
  rebalance; an entry buffer (enter in the top N) and an exit buffer (exit below the top 2N); a sector cap;
  long-only, no leverage (ISA).
- **Costs (owner, D5: retained; validated by the backtester's tests):** one way, per trade: 0.15% FX plus spread by band at decision time: large 0.15%, mid 0.30%,
  small 0.60%. No stamp duty on US shares. Reported at 1x, 2x and 3x. The large-cap figure matches Stage 2's 0.30%
  all-in; the mid and small spreads are assumptions with no fill data behind them yet.
- **Currency:** stock returns are converted to GBP monthly (`research/dataset.usd_to_gbp_monthly`), because the
  ISA and VWRP are in GBP.
- **Benchmarks:**
  1. VWRP in GBP: `research/dataset.build()["WORLD"]`, which is VWRL.L from its splice date and a Ken French
     developed-market proxy (less a 0.2% fee) before it. Before the splice the proxy excludes emerging markets
     (about 10% of FTSE All-World), which is stated with every result.
  2. The equal-weighted large-cap universe (does selection beat the pool it picks from?).
  3. Factor-matched: the strategy's FF5 + momentum alpha (USD, excess of the risk-free rate).
- **Metrics:** CAGR; volatility; maximum drawdown; Sharpe; information ratio and tracking error vs VWRP; worst
  rolling 12-month return relative to VWRP; share of months ahead; FF5 + momentum alpha and t; turnover a year;
  largest weight and top-5 weight; results by sub-period third; deflated Sharpe (§5).

## 5. Multiple testing

- **Trial count:** `edge_registry.n_trials()`: every registered trial with `counts_for_dsr`, reported or not.
  - 81 after the Phase A verification: Stage 2's 15 trials, the 6 M8 looks, 45 diagnostic horizons and 15
    quality-sensitivity looks.
  - **(owner, D4):** inherited trials and relevant prior looks count.
- **Registration is enforced, not just expected:** research code calls `edge_registry.require(trial_id)` before
  computing. It refuses an unregistered trial, and a trial that already has a result (a rerun is a new trial).
- **Deflated Sharpe** (Bailey and López de Prado 2014), as `stage2.deflated_sharpe` (formula checked by hand in
  Phase A): N = the trial count above; the cross-trial variance of Sharpe ratios is the variance of
  `edge_registry.sharpe_list()` (monthly Sharpe ratios of the same statistic), floored at 1/T, the variance of a
  Sharpe estimate under the null with T months. The floor stops a handful of similar trials from making the
  benchmark too easy.
- **Exploration bar:** t ≥ 3 (Harvey, Liu and Zhu 2016) for E2, because exploration is a search.
- **Confirmation bar:** pre-registered per batch; at least: same sign, t ≥ 2 on the holdout, effect ≥ 50% of the
  exploration effect, DSR ≥ 0.9 with the full trial count, positive at 2x costs, positive factor alpha. If more
  than one batch ever uses the holdout, the t bar rises by Holm across all holdout tests (`SPLIT_POLICY.md` §6).

## 6. Evidence tiers (owner: approve with the programme)

| Tier | Requires | Allows |
|---|---|---|
| E1 | A written mechanism and a registry entry | Research only |
| E2 | Exploration t ≥ 3 (IC or strategy alpha), positive after costs, alpha beyond FF5 + momentum | Pre-registration for confirmation |
| E3 (conditional) | Passes the single confirmation batch (§5). Because the holdout is partly seen (`SPLIT_POLICY.md` §3), a pass is conditional (D3) | Prospective logging only; demo allocation is considered only after 12 months of prospective evidence |
| E4 | 12 to 24 months of prospective results inside the backtest's 90% band | Larger demo allocation; ISA readiness review (owner) |

## 7. Reporting

Every result file states: the registry ids it reports, the code commit, the dataset manifest (file SHA-256s from
`edge_integrity.py`), the window by outcome month, the universe and exclusions, and the biases in §1. A result
without a registry id is not evidence.

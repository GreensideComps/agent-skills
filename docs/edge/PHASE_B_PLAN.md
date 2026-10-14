# Edge-discovery Phase B: concentrated-portfolio backtester (plan)

Status: proposed 2026-10-14, awaiting the owner's review. Nothing here has been built or run.

**Goal:** answer one question for any registered signal: *would a concentrated portfolio of 15 to 30 US stocks,
rebalanced quarterly and paid for in GBP, have beaten VWRP after costs?* The answer must hold on exploration data
alone (outcomes to 2022-12). The specification is `EVALUATION_SPEC.md` §4. This document says how the backtester
is built and how it is shown to be correct before any real trial runs on it.

## 1. What is reused

| Need | Existing code |
|---|---|
| Data, cut and flagged | `edge_split.cut_exploration`, `with_quality`, `complete_months`, `cut_series` |
| Signal scores | `stage2.build_features` and the `TRIALS` functions; new hypotheses add their own score functions |
| Sector groups | `stage2.sic_group` (today's SIC; stated as a bias) |
| GBP conversion | `dataset.usd_to_gbp_monthly` |
| VWRP in GBP | `dataset.build()["WORLD"]` (VWRL.L, spliced onto a Ken French developed-market proxy less 0.2%) |
| Factor alpha | `stage2.factor_alpha` (FF5 + momentum, NW standard errors; tested in Phase A) |
| Deflated Sharpe | `stage2.deflated_sharpe` with N = `edge_registry.n_trials()` and the registry's Sharpe list |
| Registration | `edge_registry.require` before running; a `result` event after |

New code is one module, `research/edge_backtest.py`, plus `research/tests/test_edge_backtest.py`. Nothing existing
changes.

## 2. Design

**Calendar.**

- Decisions are made at quarter-end month-ends (March, June, September, December) from data filed by then.
- Trades execute at the decision close. A robustness option executes one month later.
- Returns accrue monthly, and weights drift between rebalances.

**Eligible universe at each decision.** A company is eligible when all of these hold:

- it is in the large band (mid and small bands are options, labelled exploratory);
- `quality_ok` is true;
- it has a price of at least $1;
- it has a score.

**Selection.**

- Rank by score. The target is N names, with N between 15 and 30.
- Holdings ranked N or better stay.
- Holdings ranked worse than N but no worse than 2N stay while there is room (the exit buffer).
- Holdings ranked worse than 2N are sold.
- Empty slots are filled from the top of the ranking.
- Sector cap: at most k names (default k = max(3, N/5)) per `sic_group`. A name that would breach it is skipped
  for the next one.

**Weights:**

- equal weight (default);
- score-proportional;
- inverse volatility, from the trailing 12 monthly returns known at the decision.

Positions are long only, with no leverage and no cash target. If fewer than N names are eligible, the portfolio
holds fewer, and the shortfall is reported.

**Missing prices.** A holding with no next-month price (delisting, ticker change) is sold at its last price. The
count is reported. A stress option applies −30% and −100% to those exits. This bounds the survivorship and
delisting problem; it does not fix it.

**Costs:**

- Each trade costs, one way: 0.15% FX plus a spread set by the company's band at the decision (large 0.15%,
  mid 0.30%, small 0.60%).
- Turnover is measured from the drifted weights to the target.
- Results are reported at 1x, 2x and 3x costs. No stamp duty applies to US shares.

**Currency.** Portfolio returns are computed in USD, then converted to GBP monthly. Factor alpha uses USD excess
returns over the risk-free rate, so it matches the factors.

**Benchmarks:**

1. VWRP in GBP.
2. The equal-weighted eligible universe, rebalanced on the same dates, with the same costs, in GBP.
3. FF5 + momentum alpha.

All three are cut at 2022-12 with `cut_series`.

**Outputs per run:**

- CAGR, volatility, maximum drawdown and Sharpe;
- IR and tracking error vs VWRP;
- the worst rolling 12-month return relative to VWRP;
- the share of months ahead;
- factor alpha and its t;
- turnover a year;
- the largest weight and the top-5 weight;
- sub-period thirds;
- DSR;
- the number of names held;
- missing-price exits.

Each run writes a `result` event citing:

- the code commit;
- the dataset manifest;
- the window by outcome month;
- the universe and exclusions;
- the biases.

## 3. Validation before any real trial

The backtester counts as validated (`backtester_validated` in the holdout gate) when every test below passes and
the owner has reviewed the validation report.

1. **Planted signal.** On synthetic data, a score that predicts next-quarter returns by a known amount produces the
   expected excess return over the universe. A random score produces none on average over seeds.
2. **Hand-computed portfolio.** A five-company, three-quarter example matches a hand calculation of:
   - holdings;
   - drifted weights;
   - turnover;
   - costs;
   - returns.
3. **Buffers.** A name ranked between N+1 and 2N is kept; a name ranked worse than 2N is sold; an empty slot is
   filled from the top.
4. **Sector cap.** The cap is never exceeded, and skipped names are reported.
5. **Costs.** Band-specific rates are applied by band at the decision, and 2x and 3x scale exactly. This validates
   D5.
6. **Exclusions.** A flagged company-month is never held. Flags come from cut data (D5).
7. **Currency.** With a constant FX rate, GBP equals USD. A known FX path matches a hand calculation.
8. **Benchmark statistics.** IR, tracking error and relative drawdown match a hand calculation on short series.
9. **No look-ahead.**
   - Changing any return after a decision does not change that decision's holdings.
   - A frame or benchmark series holding a 2023 value is refused (`HoldoutViolation`).
10. **Registration.** An unregistered trial id, or one with a result already, is refused before any computation.
11. **Reproduction.** With N set to the top quintile, monthly rebalancing, equal weights, no buffers, no sector cap
    and a flat 0.30% cost in USD, the backtester reproduces `xsection.evaluate`'s top-quintile net return for one
    Stage 2 signal. That number is already published, so this is a check, not a new look; it is registered as a
    diagnostic with `counts_for_dsr: false`. Pass: monthly returns agree within 1e-6.

## 4. After validation (each step registered first; nothing confirmed)

1. **Owner review of the validation report.** The owner reviews it, and `backtester_validated` is recorded.
2. **Exploration trials,** chosen by the owner from the programme's hypotheses. Each trial is registered with its
   portfolio rules fixed before it runs. Suggested first:
   - H1, FCF per share acceleration. Its TTM inputs need the §10.4 checks first.
   - Gross profitability S2a as a 12-month-hold strategy, the one rising pattern in the diagnostics.

   Both are close to what the holdout's prior looks saw (`SPLIT_POLICY.md` §3), so a later holdout pass would be
   the weakest kind of conditional E3.
3. **Batch assembly.** Candidates reaching E2 (exploration t ≥ 3, positive after 2x costs, alpha beyond FF5 +
   momentum) are frozen into the single confirmation batch (D2). That batch is pre-registered in a commit, and
   the holdout is not opened until the owner reviews it.

## 5. Out of scope for Phase B

- Confirmation runs.
- New data purchases.
- Any change to the signal log, Stage 2, trading code or accounts.
- A ranking model that combines signals; that is a later, separately registered question.

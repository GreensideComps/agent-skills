# B4 validation report: the portfolio backtester (for owner review)

2026-10-15. This step covers Phase B, steps B1 to B3. The owner's decisions behind it are D7 to D11 in
`DECISIONS.md`. No new signal was registered or run. No confirmation test was run, and no holdout data was
read. Nothing in the demo strategy, the real ISA, the holdings or the trading configuration was changed.

## 1. Summary: two different claims

| Claim | Status | What it means |
|---|---|---|
| **A. Reproduction.** The engine computes what Stage 2 computed, given Stage 2's assumptions. | **Established** (accepted by the owner, D10) | The arithmetic of selection, equal weighting, monthly rebalancing, returns and costs is correct and matches an independent implementation. The only exception is NFE, explained in §3. |
| **B. Validation for investable research.** Results from the engine's realistic settings can be trusted as evidence about an investable strategy. | **Not established.** Conditional at best; see the blockers in §5. | Correct arithmetic does not make the inputs realistic. The main limits are the data and the assumptions, not the code. Several of the engine's investable settings have only been tested on synthetic data. |

**Recommendation:** treat the engine as validated for *exploration research under the stated limitations*. Do
not treat it as validated for judging whether anything is investable.

- If you agree, recording `backtester_validated` would let B5 exploration trials be registered and run.
- `edge_split.holdout_gate` also requires `backtester_validated`, so the same flag would satisfy that gate's
  engine condition later. No confirmation run is authorised either way.
- I have not recorded the flag. That is your decision (D11).

## 2. Evidence

| Step | What was checked | Result | Record |
|---|---|---|---|
| B1 data | Execution prices: first trading day after each month-end, to 2022-12 only. Benchmarks and FX. Integrity checks. | No check failed. 99.8% coverage. Strict cutoff at 2022-12-31. All three data files are hash-locked. | `exec_prices_integrity.md`; PHASE_B_PLAN §6 |
| B1 audit | Overnight moves; non-OK price rows; coverage by group; benchmark dates; provenance | 27 eligible rows moved more than 50% overnight; 12 look like data errors. Every group is above 99.5% coverage. VWRP's first full return is 2019-08. FRED is unused; all FX comes from Yahoo. | `exec_prices_audit.md`; PHASE_B_PLAN §7 |
| B2 synthetic | 29 tests covering the 10 plan items: engine, timing, missing prices, costs, FX, constraints, benchmarks, registry and DSR. A mutation check confirmed the tests catch injected bugs. | 29/29 pass, plus 3 later tests for the B3 modes (32 in that file) | `b2_validation.md` |
| B3 (A) | Stage 2's original code, on data cut at 2022-12-31, against the published results | 15/15 match to 1e-6 (differences below 1e-16) | `b3_reproduction.md` |
| B3 (B) | The new engine against Stage 2's code, with assumptions frozen beforehand | Every month matches to within 1e-15 except four NFE months (§3). Largest annual difference: 0.021 percentage points. | `b3_reproduction.md`; `B3_STAGE2_SPEC.md` |
| B3 (C) | Next-day execution comparison (descriptive, kept separate) | Moves annual results by −0.72 to +0.31 percentage points; no sign changes | `b3_reproduction.md` §C |
| Tests | Research, equity and trading suites | 105, 117 and 139 pass (the repo has no CI; run locally) | — |

## 3. The one reproduction discrepancy (accepted, D10)

- **Where:** NFE (New Fortress Energy) has negative dividend-adjusted closes in 2022-07, 2022-08, 2022-10 and
  2022-11.
- **Stage 2:** computed returns from these negative prices.
- **Engine:** refuses any price at or below zero, by design.
- **Effect:** 12 of 15 trials fall outside 1e-6 in those four months only. The largest annual difference is
  0.021 percentage points.
- **Resolution:** the safeguard stays. No rerun with NFE excluded replaces the frozen reproduction.

## 4. What the engine can and cannot be trusted for

**Trusted (tested on synthetic data, and also on real data where marked):**

- Selection, weighting, rebalancing, turnover and costs. Real data: Stage 2 mode in B3.
- Point-in-time discipline:
  - decision inputs come only from rows dated at or before the decision;
  - trades execute strictly after the decision;
  - any 2023 date is refused.
- Missing-price handling never helps the strategy:
  - a missing price exits at the last valid price less 30%;
  - −100% is available as a stress test;
  - a positive markdown is refused.
- Costs per size band and their multipliers.
- GBP conversion.
- Benchmark labels (VWRP from 2019-08, VWRL before that).
- Tracking error, information ratio and relative drawdown.
- Registry enforcement and DSR pooling.

**Tested only on synthetic data so far:** the programme's actual portfolio settings. These have never been run
on real data:

- 15 to 30 names, rebalanced quarterly;
- a rank buffer and a sector cap;
- the GBP NAV against VWRP;
- next-day execution with the B1 file.

The first real use of these settings would be a B5 trial.

## 5. Remaining blockers and limitations for investable research

| # | Issue | Severity | Fixable on free data? | Effect |
|---|---|---|---|---|
| 1 | **Survivorship bias.** Companies that stopped trading have no free prices: 318 of 323 large companies that stopped filing in 2023-26 are unpriced. | High | No (paid data needed; not approved) | Every backtest is biased upward by an unknown amount. The missing-price stresses only partly bound it. An E3 claim needs this addressed or explicitly accepted. |
| 2 | **Historical data defects**: negative adjusted prices (e.g. NFE) and share-count scaling errors (e.g. ATLX, ATXG in the large band). | Medium | Partly | The engine refuses non-positive prices, and the Phase A quality rule handles share counts. A data-error sensitivity (`B1-SENS-DATA-ERRORS`) is registered but has not been run. |
| 3 | **Stage 2 look-ahead.** Its universe required a known next-month return. | Low for new work | Yes; already removed in the engine | Stage 2's published numbers carry this optimism. New trials do not. |
| 4 | **Investable configuration unproven on real data** (§4) | Medium | Yes, through B5 | The first B5 trials should be checked by hand on a sample of months before their results are relied on. |
| 5 | **Benchmark history.** Actual VWRP returns start 2019-08; 2015 to 2019-07 uses VWRL; the pre-2012 proxy is not built. | Low | Yes | Most of the exploration window is measured against VWRL, the same fund in a different share class (tracking error about 0.37% a year). |
| 6 | **FX.** FRED is unreachable, so all 3,430 FX days come from Yahoo GBPUSD=X. | Low | Partly | One unofficial source with no cross-check. |
| 7 | **Cost assumptions are estimates**: FX fee 0.15% plus spreads of 0.15/0.30/0.60% by band. They are not checked against Trading 212 fills. | Medium | Partly (demo fills) | Strategies with high turnover are most exposed. Results are reported at 2x and 3x costs. |
| 8 | **Holdout partly seen** (Phase A: 11 exposures recorded) | Medium, for confirmation | No | A future holdout pass counts only as a conditional E3 (D3). |
| 9 | **Statistical power.** 95 months of large caps; the minimum detectable information coefficient is about 0.01 to 0.04. | Medium | No | Small real edges may not be detectable on this window. |
| 10 | **Process gaps.** PR #19 is open and unmerged; the repo has no CI. | Low | Yes | You review and merge; tests are run locally before every push. |

None of these is a coding defect. Items 1, 2 and 7 mean that a good backtest result from this engine is evidence
for further study, not proof of an investable edge.

## 6. Decisions for the owner

1. **Should `backtester_validated` be recorded, on the scope in §1?** My recommendation: yes, for exploration
   research only, with the §5 limitations attached.
2. **B5 requires your separate approval**, per D11. If you approve it, the plan's suggested first trials are:
   - H1, free cash flow per share acceleration;
   - S2a, gross profitability, held for 12 months.

   Each would be registered with fixed portfolio rules before it runs.

No other work has started.

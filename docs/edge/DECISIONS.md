# Edge-discovery programme: owner decisions

The owner's decisions on the Phase A review, given in the project thread "Edge-discovery Phase A audit" on
2026-10-14 at 20:50 UTC. Each one changes what counts as evidence, so code that depends on it names it here.

| # | Decision | Where it is enforced or applied |
|---|---|---|
| D1 | **The split is approved provisionally.** Exploration covers outcomes to 2022-12; confirmation covers outcomes from 2023-01 to 2026-09, counted by the month an outcome is realised. | `edge_split` boundaries; `edge_split.OWNER_SPLIT_APPROVAL`, which `holdout_gate` requires; `SPLIT_POLICY.md` |
| D2 | **There is one confirmation batch only.** | `edge_split.MAX_CONFIRMATION_BATCHES = 1` (`holdout_gate` refuses a second batch); `edge_registry.MAX_BATCHES = 1` (`validate` rejects a second `batch` event) |
| D3 | **A holdout pass earns conditional E3.** It allows no demo allocation until 12 months of prospective evidence support it. | `EVALUATION_SPEC.md` §6 |
| D4 | **Inherited trials and relevant prior looks count** in the multiple-testing adjustment. | `edge_registry.n_trials` (96 after the PR #18 review) |
| D5 | **The data-quality exclusions and band-specific cost assumptions stay,** provided they are validated as correctly implemented and consistently applied. | Exclusions: `edge_split.quality_flags`, computed on period-cut data (`with_quality`); the sensitivity is in `equity/reports/research/edge/stage2_quality_sensitivity.md`. Costs: validated by the Phase B backtester's tests. |
| D6 | **The stale ETF research loop is paused** until it is reviewed and explicitly retargeted. | The scheduled task "T212 demo: research loop" is disabled. The scheduler showed it disabled at 2026-10-14 20:50:18 UTC. |

The owner also set these conditions:

- **Before PR #18 merges:**
  - investigate the 2026-10-31 price rows;
  - review the exclusions, the point-in-time boundaries, the holdout guard and the registry;
  - check that the exclusions are used consistently;
  - document the quarterly TTM limitation;
  - rerun the tests;
  - record these decisions.

  All of this is reported in `PHASE_A_AUDIT.md` §10. The PR waits for the owner's review and is not merged by
  Claude.
- **No holdout outcome** is run or inspected during this work.
- **Confirmation does not begin** until two conditions hold:
  - the portfolio backtester is validated (`holdout_gate` requires `backtester_validated`);
  - a complete, pre-registered batch of eligible candidates is ready.
- **Every new research trial is registered before its results are computed.** `edge_registry.require` refuses an
  unregistered or repeated look.
- **Untouched by this work:** the monthly signal log, the real ISA, the trading configuration and the account
  holdings.

## 2026-10-15 08:17 UTC: merge approval and Phase B scope

| # | Decision |
|---|---|
| D7 | **PR #18 merged** (merge commit 9527e6e). The approval covers Phase A governance, integrity checks and research controls **only**. It does not establish that any signal has an edge, and it authorises no confirmation run, demo allocation, or change to the real ISA, holdings or trading configuration. |
| D8 | **Phase B is authorised for step B1 only:** permitted point-in-time execution-price data and an FX fallback, with integrity checks and a strict cutoff at 2022-12. No signal exploration until the data pipeline is validated and the owner has seen the B1 report. |
| D9 | **The gates stay:** synthetic backtester validation, Stage 2 reproduction, an owner-reviewed validation report, and registration of each exploration trial before it runs. No confirmation run is authorised. |

## 2026-10-15 18:24 UTC: B3 accepted; B4 report requested

| # | Decision |
|---|---|
| D10 | **B3 is accepted as reproduced.** The NFE discrepancy is documented and the negative-price safeguard is retained (details below). |
| D11 | **Next step: prepare the B4 validation report for review.** It must distinguish reproduction success from validation of the engine for investable research, and list the remaining blockers. Nothing beyond the report is authorised (details below). |

**D10 in full:**

1. **The original Stage 2 reproduction is accepted.** All 15 published results were reproduced by the original code on the frozen exploration-period dataset.
2. **The new-engine discrepancy is accepted as explained.** It comes from NFE's invalid negative adjusted prices; the largest annual-result difference reported is 0.021 percentage points.
3. **The safeguard stays and the frozen reproduction stands.**
   - Negative-price trading is not permitted to force agreement.
   - No rerun with NFE excluded is to replace the frozen reproduction.
4. **Next-day execution results stay separate from the reproduction.**
   - S5a's +0.55% annual net result is exploratory only.
   - It is not an approved investment signal.
5. **The stated limitations are preserved:**
   - survivorship bias;
   - historical data defects;
   - the original Stage 2 look-ahead assumptions.

Report: `equity/reports/research/edge/b3_reproduction.md`. Spec: `B3_STAGE2_SPEC.md`.

**D11 in full.** The owner's separate approval is required before any of the following:

- starting B5;
- registering or running a new signal experiment;
- running a confirmation test;
- allocating to the demo strategy;
- changing the real ISA, holdings or trading configuration.

`backtester_validated` is recorded only by the owner.

## 2026-10-16 10:12 UTC: backtester validated for exploration only; pre-B5 preparation

| # | Decision |
|---|---|
| D12 | **`backtester_validated` is recorded, limited strictly to exploratory research under the limitations in `B4_VALIDATION_REPORT.md` §5.** Machine-readable record: `research/edge/status.json`. |
| D13 | **Survivorship-free prices are not feasible on free data** (`SURVIVORSHIP_FEASIBILITY.md`). The limitation is accepted for exploratory research only, on the conditions in that note's §4. |
| D14 | **Before B5:** prepare the real-data hand-check plan, frozen and registered H1 and S2a specifications, and exploratory thresholds with the multiple-testing treatment set in advance. Return them for review. **Stop before running H1 or S2a.** |

**D12 scope in full.** The status does **not**:

- establish that any strategy is investable;
- fully validate the strategy's real-data portfolio settings (that needs the B5 hand-check);
- prove an edge;
- authorise confirmation testing;
- authorise demo allocation.

The holdout restrictions are unchanged. `edge_split.holdout_gate` still needs a batch, a pre-registration commit and
the owner's approval of that batch; the flag alone opens nothing.

**D14 in full.** The two trials stay exploratory. The holdout restrictions stay. No confirmation test, no demo
allocation. The real ISA, holdings and trading configuration remain unchanged. Documents:
`B5_PREREGISTRATION.md`, `B5_HANDCHECK_PLAN.md`, `SURVIVORSHIP_FEASIBILITY.md`.

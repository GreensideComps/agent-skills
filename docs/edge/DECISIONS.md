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

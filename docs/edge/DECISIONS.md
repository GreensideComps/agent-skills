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

## 2026-10-16 11:53 UTC: pre-B5 review

| # | Decision |
|---|---|
| D15 | **Approved:** the fixed placebo-score hand-check, the preparatory engineering and the synthetic tests. **Not approved:** running H1 or S2a. No H1 or S2a return, NAV or ranking may be computed. B5 execution needs separate approval. No confirmation test, demo allocation or real ISA, holdings or trading-configuration change. |

**D15 requirements before returning for trial approval:**

1. the exact H1 definition, frozen before any result;
2. the exact DSR calculation, with N reconciled to the registry;
3. every report states that the −100% stress does not address companies missing from the universe;
4. TTM checks 1-3 done, and the effect of the open independent-source check stated;
5. costs reconciled across the main run and the robustness runs;
6. trial controls confirmed.

Response: `B5_PREREGISTRATION.md` version 2, `research/edge_b5.py`, `equity/reports/research/edge/ttm_checks.md`,
`equity/reports/research/edge/b5_handcheck.md`.

## 2026-10-16 13:34 UTC: round 3 reviewed; trial run still not authorised

| # | Decision |
|---|---|
| D16 | **H1 period alignment approved in principle:** operating cash flow and capex must share one fresh TTM period end, otherwise H1 is unavailable. No alignment. (Already implemented: `edge_b5_inputs.fcf_inputs`, `align=False`.) |
| D17 | **S2a staleness approved in principle:** gross profit older than 183 days is never used; the revenue fallback only when its inputs pass the frozen validity rules (`B5_PREREGISTRATION_ADDENDUM_2.md` §1, draft). |
| D18 | **Not yet approved:** the revenue-tag rule (document and freeze without inspecting performance), the blanket 20-F/40-F exclusion (investigate an identity rule, else compare it with the CIK-specific option on input evidence), and the run script (not to be written until the data rules are resolved and the addendum frozen). N = 100, the registered DSR definition and the open check 4 are kept. No E2 label, confirmation batch, holdout access, demo allocation or live-account change. PR #19 not merged. |

## 2026-10-16 14:17 UTC: round 4 reviewed; addendum 2 to be frozen

| # | Decision |
|---|---|
| D19 | **D16 and D17 approved in principle. Identity rule C preferred** over A or B, subject to final specification and tests (`B5_PREREGISTRATION_ADDENDUM_2.md` §3). **T2 may filter the primary trials only where it is known at the decision date**; anything detectable only from later filings stays a retrospective diagnostic; the same principle for revenue, gross profit, OCF and capex (§2: T2 is point in time, so it filters all four). Addendum 2 frozen and registered (`B5-V2-ADDENDUM-2`, not counted, N = 100). The run script is written for review; **its execution, the trial run and the merge are not authorised.** Check 4 stays open; no E2 label, confirmation, holdout access, demo or live-account change. |

## 2026-10-19 07:04 and 07:33 UTC: final audit; point-in-time quality rule

| # | Decision |
|---|---|
| D20 | **Option B: the point-in-time share-outlier rule (`edge_split.share_outliers_pit`) becomes the B5 primary quality rule** for portfolio eligibility, the S2a rank population and the P5 universe. The Phase A full-window rule (D5, `edge_split.share_outliers`) becomes the P9 reverse veto only: it can fail a trial, never rescue a failed gate or replace the primary result. **N = 100 is kept provisionally** through a formal addendum, subject to the justification in `B5_PREREGISTRATION_ADDENDUM_3.md` §5. **D5 is not withdrawn**: it still governs Phase A and Stage 2, and its rule is unchanged in code. Version 2's definitions and registry entries are not edited; the addendum amends them. Status 07:33Z: Addendum 3 and code drafted **for review only**. Not authorised: registering Addendum 3, the ROB-WINQ ids or the manifest; the run; the merge. Check 4 stays open. |
| D21 | **(07:44 UTC) Addendum 3's direction approved in principle; the N = 100 route is not.** Version 2 §7 allows only bug fixes before a run and forbids definition changes, and Addendum 3 changes primary eligibility, so the stricter route applies: **new counted version-3 trial ids** (`B5-H1-FCFPS-ACCEL-V3`, `B5-S2A-GP-12M-V3`) and **N = 102**, under the existing counting rules. Version-2 (and version-1) records stay registered and unchanged, counted, and can never run. D20's provisional N = 100 is superseded by this decision; D20 itself is not rewritten. Prepared for review only: no registration of Addendum 3, the version-3 ids, ROB-WINQ or the manifest; no run, merge, holdout access, confirmation, demo or live-account change. |
| D22 | **(07:53 UTC, confirmed on the decision card 08:22 UTC) Version-3 registration, step 1 only.** Approved on condition that the 13-event transition is atomic and preserves every existing entry. The reviewed code appended one event at a time, so registration was made all or nothing first (commit 53c323b, event list unchanged), dry-run on a copy, then run once on the real registry: 13 events appended (`B5-V3-ADDENDUM-3` uncounted; `B5-H1-FCFPS-ACCEL-V3` and `B5-S2A-GP-12M-V3` counted; 10 uncounted `-V3-ROB-*` ids), 224 earlier lines byte-identical (pre-registration sha256 0da0638e…85fd), N 100 → 102, registry valid. The run manifest is not registered; the run is not authorised. Each of those needs a separate approval. |

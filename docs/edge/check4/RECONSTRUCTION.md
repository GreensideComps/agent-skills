# Check 4 step 0: reconstructed run-2 holdings (for owner review)

Status: **RECONSTRUCTED, NOT ORIGINALLY RECORDED.** Run 2 (D31, commit `a4a07d7`) recorded statistics but no
holdings. Every holding and frame row here comes from replaying run 2's selection with its frozen code and inputs,
and every row carries `source = reconstructed`. Owner approval: O6, message
`cmsg_01U4KMvkBYNknqm4HRVie8uvWBGcbQVLRwVrW8HKHTK5JK` (2026-10-20 07:19Z), for the Check 4 sampling frame and the
later holding-effect test only. **Source extraction has not started** and Check 4 is not complete.

## What was run

`research/check4/reconstruct_holdings.py --frozen <clean checkout of a4a07d7> --out docs/edge/check4`

1. It refuses unless the checkout is exactly `a4a07d7d6a3242d2fd06dd5fb133262f28172b9f` with no local changes, the
   manifest is the registered MANIFEST-3 (sha256 `f3f4fd71…`), and all 26 manifest files (10 inputs, 16 code files)
   have their recorded sha256. All matched.
2. It builds the primary panels with the frozen functions (`attach_fundamentals`, `score_panels`, `config`), as
   `edge_b5_run.load_inputs` does, without the run gate and without the FX, benchmark, factor and data-error inputs,
   which only valuation needs.
3. It replays `edge_backtest.run`'s selection loop with the frozen selection functions (`decision_frame`,
   `price_table`, `eligible`, `select`) for every tranche of each primary run. An exit between rebalances is
   decided by whether an execution price is valid, not by its value, so no return is needed.

**Not computed:** returns, NAV, costs, contributions or any statistic. **Not changed:** the run-2 report, registry,
verdicts, authorisation history, lock archives, gates, B5 status and every B5 file (all on PR #19's branch,
untouched; this branch is based on master).

## Outputs (sha256, identical in two separate runs)

| File | sha256 | Rows |
|---|---|---|
| `holdings_H1.csv` | `d811b33b292975a765b31a540eebee44e9e1e7474c08614e134cad038f23ad01` | 1,940 (97 decisions × 20) |
| `holdings_S2A.csv` | `284e96bd0cc2ed444fe112a2692a77e3bf59567517e74bf8f44f5065f9907c7e` | 2,120 (106 decisions × 20) |
| `frame_H1.csv` | `1bb6b80488f9084a8492077c6206338419a1fd02fe690696f7b2e35a6dc8134f` | 25,176 (95 months; 1,900 held) |
| `frame_S2A.csv` | `ab186a5d786a83b3a7faba5fa6eab608d886c4623153125b387b58b740b20dc2` | 23,678 (95 months; 1,900 held) |
| `events_H1.csv` | `ec56d90cfff41dda42404d1df9a6813e5c0b78727abe6f464656280e23721819` | 213 sector-cap skips |
| `events_S2A.csv` | `53c01e6a704b088de87450a584139a3db4754593eb2978e2faafde8203f51922` | 6 sector-cap skips |
| `reconstruction_summary.json` | `47c3abb170da1710…` (full hash in the file listing) | provenance, counts, environment |

Columns: holdings give trial, tranche start, decision month, trade date, CIK and rank. The frame gives, for every
eligible company at each decision month from 2015-01 to 2022-11: rank, number eligible, score, score decile (10 =
best), `held` (chosen by the tranche that rebalances that month), `held_any_tranche` (in any tranche's portfolio
after that month's rebalance) and the rebalancing tranche. Exactly one tranche rebalances in each frame month for
both trials; the script stops otherwise.

Counts: H1 holds 248 distinct companies across 97 decisions; S2a holds 93 across 106. Every decision holds 20 names.
No holding exited on a missing price and no entry was skipped for a missing execution price.

## Reproducibility evidence

| Evidence | Kind | Result |
|---|---|---|
| Frozen commit, clean tree, MANIFEST-3 hash, 26 file hashes | verified | all match |
| Two full runs, byte-compared | verified | all 7 files identical |
| Replay equals the frozen engine's `holdings`, exits, skips and short events on synthetic worlds (12 seeds × 2 schedules, 5 tranches; caps, buffers, exits and skipped entries all occur) | test | 24 pass |
| `price_missing` equals the frozen `holding_return` status (300 random series) | test | pass |
| Run 2's recorded top contributors (H1: CIK 2488; S2a: CIK 97476) are among the reconstructed holdings | consistency with recorded results | both held |
| Run 2 recorded identical P6 and P8 results (to 16 digits) in both trials. That is what happens when no holding exits on a missing price (P6 changes only the exit mark-down) and no data-error company-month is newly bought (P8 only bars those buys). The reconstruction has zero exits and buys none of the 12 data-error company-months | consistency with recorded results | consistent |

Mutation check of the equivalence test: removing exits or ignoring the execution-price check makes it fail. Keeping
a held name's original entry date instead of resetting it at each rebalance does not, because a held name's earlier
prices were already checked; the two are equivalent.

## Limitations and uncertainty

- **No recorded holdings exist to compare against.** Fidelity rests on identical code and inputs (verified), the
  replay matching the engine on synthetic data (tested), and the two consistency checks against recorded results.
  These are necessary conditions, not proof that the real-data selection equals run 2's.
- **Library versions:** run 2 did not record its Python, pandas or numpy versions. This run used Python 3.13.16,
  pandas 3.0.5 and numpy 2.5.3. Ranking sorts by (score, CIK), so ties cannot reorder, but a version difference in
  input parsing could not be ruled out [assumption: same container image].
- **Missing inputs are left out, never filled.** Company-months that pass every other eligibility rule but have no
  score (an input unavailable at the decision date): H1 8,924 against 25,176 scored; S2a 10,422 against 23,678
  scored. They are outside the frame, so Check 4 sampled from the frame cannot measure coverage misses among them.
  This is a material gap for the coverage-miss rule (procedure §8.5). Classified in `MISSING_SCORES.md`.
- **Decile definition** is a proposal, not a recorded rule: see "Decile rule (proposed)" below.
- **Not reproduced:** the P9 veto panel, robustness variants and every valuation step. Only primary selections are
  needed for Check 4.
- Survivorship bias in the universe is untouched and stays material and unbounded.

## Decile rule (proposed; owner approval needed before any draw)

**Not a historical fact.** The frozen B5 engine selects the top 20 by rank (`selection="top_n"`) and never computes
deciles. The Check 4 procedure (PR #21 §4) stratifies by "score decile" without defining it. The rule below is this
reconstruction's proposal. It was fixed on 20 Oct before any Check 4 sample or extraction and will not change after
seeing extraction results.

**Formula.** For one trial and decision month, take the engine's own ranked list (`edge_backtest.eligible`: the
eligible rows with a score, sorted by score descending, then CIK ascending, rank 1..n). Then

    decile = 10 - floor((rank - 1) * 10 / n)        10 = highest scores, 1 = lowest

**Why it fits the frozen selection.** It uses exactly the population and order that chose the holdings, so decile
10 contains the names the engine looked at first and every held name's decile reflects the engine's own view of it.
It needs no new parameter, is a closed form (no interpolation) and gives decile sizes that differ by at most one.

**Ties.** Two names can never share a rank: the engine breaks score ties by CIK, so a tied name's decile is set by
its CIK, as its selection was. H1 has no tied scores. S2a has many (it ranks within-group percentiles, so the top of
each SIC group scores 1.0): 3,419 tied groups covering 9,227 frame rows; 157 of those groups (421 rows) straddle a
decile boundary, so for those rows the CIK tie-break decides the decile. That mirrors how the engine itself
treated them.

**Missing scores.** Excluded: they are not in the engine's ranked list, so they have no rank or decile and n counts
scored rows only (see `MISSING_SCORES.md`).

**Consistency.** The same function, population and order are used for both trials and every decision month; n is
that month's count (H1 170-397, median 250; S2a 161-358, median 242). Tests check every committed frame row.

**Deterministic example (n = 23):** ranks 1-3 → 10; 4-5 → 9; 6-7 → 8; 8-10 → 7; 11-12 → 6; 13-14 → 5; 15-17 → 4;
18-19 → 3; 20-21 → 2; 22-23 → 1.

**Alternative the owner could choose instead:** Stage 2's precedent in the frozen code
(`edge_backtest.stage2_top_quintile`: `pd.qcut(score.rank(method="first"), 10)`, ties broken by input order). It
places boundaries by quantile interpolation, so it differs from the proposal on 420 H1 and 466 S2a frame rows;
top-decile membership differs for 7 H1 and 13 S2a rows and bottom-decile membership for 83 and 89. Its tie-break
depends on row order, which B5 does not fix, so it is less reproducible here.

Tests: `research/check4/test_decile.py` (11): the example above, sizes, monotonicity, the tie order, and every
committed frame row of both trials.

## Next step (needs the owner's review)

Owner review of this reconstruction. Only after that: the seeded draw (§4.3), then blind extraction. The holding-
effect test will rerun `replay` with a corrected fact for each error found, on the same frozen code.

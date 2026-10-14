# Edge-discovery programme: exploration, confirmation and prospective evidence

Status: **approved provisionally by the owner on 2026-10-14** (decisions D1-D4 in `DECISIONS.md`; §6 below). The
code guard (`research/edge_split.py`) enforces the exploration boundary. Nothing opens the holdout until the
portfolio backtester is validated and the single pre-registered batch is ready.

## 1. The three kinds of evidence

| Period | Outcomes realised | Use | Enforced by |
|---|---|---|---|
| Exploration | 2012-01 to 2022-12 | Free use. Every definition, horizon, universe or cost tried is a trial in the registry. | `edge_split.exploration_view` cuts the data at 2022-12 before any feature is built and drops every forward return that reaches 2023. `assert_exploration_only` raises if a frame leaks. |
| Holdout (confirmation) | 2023-01 to 2026-09 | Read once per pre-registered batch, by code committed before it runs. | `edge_split.holdout_gate` and the registry's `batch` / `holdout_run` events (one run per batch, one batch per trial). |
| Prospective | decisions from 2026-10-31 | The monthly signal log (unchanged), and later a second log for anything confirmed. | `research/signal_log.py` `FIRST_MONTH`; write-once log files. |

**Boundaries are set by when an outcome is realised, not when a decision is made.** A decision at month-end t with
an h-month horizon is exploration only if t + h is no later than 2022-12:

| Horizon | Last exploration decision |
|---|---|
| 1 month | 2022-11 |
| 3 months | 2022-09 |
| 6 months | 2022-06 |
| 12 months | 2021-12 |

Features may use any data up to the decision date (lags reach back before 2012; that is fine). Exploration may
start in 2012, but large caps number only 208 to 279 a month in 2012 to 2014 (Stage 1 report), so results that
lean on those years must say so.

## 2. What the holdout was originally for

STRATEGY_V2 §2.2 (commit 0c9fab3) reserved 2023-01 to 2026-09 "for all signals until the combined model is
frozen", to be "used once". It was meant for **one** out-of-sample test of the **combined** Stage 3 model, after
each signal had passed on its own. Stage 2 respected that (`research/stage2.py`: decisions end 2022-11 and the frame
is cut before evaluation; reproduced exactly on 2026-10-14). No signal passed, so the combined model was never built
and that single use was never spent.

The programme proposes a different use: one confirmation per pre-registered batch. That changes the holdout from a
single final exam into a repeated one. §6 sets out what that costs.

## 3. The holdout is not untouched

Stage 2's signal tests did not read it. Other work did, before and after Stage 2. Full evidence is in
`docs/edge/PHASE_A_AUDIT.md` §3; in short:

- The M8 screen backtest read 12-month returns for the April 2022 to 2025 cohorts (outcomes to 2026-04) for a
  composite of FCF-per-share growth, quality, valuation and dilution.
- The 14 October audit computed post-hoc sub-score ICs pooled over those cohorts. FCF per share came out at t = 2.9.
  That is the in-house precedent for hypothesis H1.
- The programme proposal itself printed 2023 to 2026 Ken French factor means (value, profitability, investment,
  momentum, size) and used them to argue against factor-harvesting strategies.
- ETF and factor research (E001 to E015) used out-of-sample periods to 2026.
- The Stage 1 harness check computed the equal-weighted large-cap return to 2026-08 (as one 2012-2026 number).
- Everyone involved, including the model doing the research, knows roughly how markets behaved in 2023 to 2026.

Each of these is recorded in `research/edge/trials.jsonl` with `touched_holdout: true`.

**Consequence.** The holdout can still reject an idea: an idea that fails on it has failed. It cannot fully confirm
one, because the choice of ideas was made by people and code that had seen part of the outcome. A pass on the
holdout is therefore **conditional confirmation**, and is weakest for hypotheses closest to what was seen
(FCF per share, value, quality, investment, momentum). The only data nobody has seen is prospective data.

## 4. Rules

1. **Register before you run.** Every exploration trial is appended to `research/edge/trials.jsonl` before its
   numbers are computed (`edge_registry.append`). The registry is append-only and hash-chained; an edited line
   breaks `edge_registry.validate`.
2. **Everything counts.** The deflated Sharpe uses `edge_registry.n_trials`: every registered trial marked
   `counts_for_dsr`, reported or not, including Stage 2's 15 trials, the M8 looks and the Phase A diagnostic
   horizons.
3. **Exploration code calls `exploration_view` first**, and never reads `xsection.load()` output for months after
   2022-12 directly.
4. **A confirmation batch** is a git commit containing: the trial ids (each an exploration trial that reached E2),
   their frozen code, the dataset manifest (SHA-256 of every input file, from `edge_integrity.py`), the pass rules,
   and a `batch` event in the registry. The holdout run uses that commit's code, unchanged, and writes one
   `holdout_run` event.
5. **No second chance on the same data.** A trial that fails confirmation cannot be re-tuned and confirmed on the
   holdout again. It may only be re-tested prospectively.
6. **Holdout results are not exploration inputs.** After a batch runs, its holdout numbers may not be used to choose
   or tune later trials. In practice the same people and model see them, so §6 limits how many batches there are.
7. **Prospective data is untouched by this policy.** The monthly signal log keeps running exactly as it is.

## 5. What each kind of evidence can show

| Evidence | Can show | Cannot show |
|---|---|---|
| Exploration | Where to look; that an effect is large enough to be worth confirming | That it is real (it was chosen because it looked good) |
| Holdout | That an idea fails out of sample; conditional support that it survives | Clean proof, for the reasons in §3 |
| Prospective | Clean, unseen evidence | Anything quickly: a typical IC of 0.03 needs about 44 months to reach t = 2 |

## 6. Owner decisions (made 2026-10-14)

1. **Split:** approved provisionally (D1).
2. **Batches:** one confirmation batch only (D2). Enforced by `edge_split.holdout_gate` and
   `edge_registry.validate`.
3. **What a holdout pass earns:** conditional E3. No demo allocation before 12 months of prospective evidence
   (D3).
4. **Trial count:** inherited trials and relevant prior looks count (D4).

The options as they were put to the owner are kept below for the record.

1. **Approve the split** (exploration 2012-2022, holdout 2023-01 to 2026-09, by outcome month).
2. **How many confirmation batches the holdout may serve.** Each extra batch re-uses the same 45 months, and
   whoever designs batch 2 has seen batch 1's holdout result. Options:
   - **One batch only** (recommended, and closest to what STRATEGY_V2 reserved it for): exploration runs until a
     set of E2 candidates is ready, then all are confirmed together, once.
   - **Up to N batches with a holdout-level correction:** the t threshold rises with every holdout test ever run
     (Holm across all confirmed trials).
   - **Split the holdout** into separate periods per batch: each is cleaner, but power falls sharply (about 22
     months each for two batches).
3. **What a holdout pass earns,** given §3: full E3 (demo allocation), or "conditional E3" that needs, for example,
   12 months of consistent prospective evidence before any demo capital.
4. **Whether Stage 2's 15 trials and the M8 looks count** in the programme's deflated Sharpe. Default here: they
   count (21 trials before Phase A's diagnostics, 66 after), which is the stricter choice.

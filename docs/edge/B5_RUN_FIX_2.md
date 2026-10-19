# B5 run fix 2: each run's evaluation starts at its own first trade (bug fix, no definition change)

This fix responds to the owner's decision D27 (2026-10-19 11:51Z) after run 1 (D26) stopped with an error; see
`B5_RUN_1_INCIDENT.md`. Version 2 §7 allows bug fixes to code before a run.

Nothing in the specification changes: no trial, gate, threshold, statistic, input, universe, cost, quality rule or
DSR rule, and N stays 102. This document is a **proposal**. MANIFEST-3 is not registered, the lock stays, and no
run is authorised.

## 1. Defect

- **Rule (specification):** `B5_PREREGISTRATION.md` §1, Tranches, sets the evaluation start at "the execution after
  the 2015-01-31 decision".
- **What the code did:** `edge_b5_run.run_combined` rebased every run's tranches at
  `first_exec_date(data["exec"])`. That is the **next-day-close** execution date of that decision (2015-02-02 in
  the data's calendar).
- **Why P7 failed:** P7 executes at the **next month-end close**. Under that convention the 2015-01-31 decision
  trades at the 2015-02 month-end, so no P7 tranche has a value on 2015-02-02.
- **Result:** `edge_b5.combine_tranches` correctly refused ("every tranche must have a NAV on the evaluation start
  date"), and run 1 stopped.
- **Which runs were affected:** P4, P5, P6, P8, P9 and P11 use next-day close, so their start was already right.
  Only P7 was affected.
- **Why the tests missed it:** they replaced `run_combined` with a stub, so no variant ever went through the real
  combined-portfolio path.

## 2. Fix (one function, `research/edge_b5_run.py`)

- `first_exec_date(ex, convention)` now returns the trade date of the 2015-01-31 decision **under the run's own
  convention**.
- It reads that date from `edge_backtest.price_table`, the same table the backtest trades on.
- `run_combined` passes `cfg.convention` to it.
- If the decision has no trade date under the convention, the function raises an error. It never moves the start
  to another date.
- **Next-day close:** the result is identical to run 1's rule (tested).
- **Next-month close:** the start is the 2015-02 month-end.
- **What is unchanged:**
  - `combine_tranches`, the backtester and every other function;
  - the end of every run (the 2022-11-30 decision);
  - the tranche schedule;
  - the refusal of a tranche with a missing start value, missing dates or a different end.

The manifest pointer moves to `B5_RUN_MANIFEST_3.json` / `B5-V3-RUN-MANIFEST-3`, unregistered (§5).

## 3. Evaluation window under each convention (consequence stated, not changed)

**Primary, P4, P5, P6, P8, P9 and P11**

- 95 valuation dates: 2015-02-02 to 2022-12-01.
- These are the next-day closes after the 2015-01 to 2022-11 decisions.

**P7**

- 94 valuation dates: 2015-02-28 to 2022-11-30.
- The 2015-01 decision trades at the 2015-02 month-end.
- The 2022-11 decision would trade at the 2022-12 month-end. The B1 execution file holds decisions to 2022-11
  only, so it does not carry that close. P7's last trade is therefore the 2022-10 decision's, on 2022-11-30.
- This one-month shift is a property of the registered next-month-close convention on the registered data. Fix 2
  does not create or alter it.
- P7's net excess is measured against the benchmark over P7's own dates (`monthly_excess`), so the two series are
  never misaligned.
- No return is dropped inside either window. The returns of every combined NAV compound exactly to its last value
  (tested).
- **Owner decision needed (§6):** whether P7's 93 monthly returns, against the primary's 94, need any disclosure
  beyond this note.

## 4. No look-ahead, no hidden losses

These points are checked by automated tests on synthetic data only (`research/tests/test_edge_b5_fix2.py`):

- **Start date:** every run starts at its own first trade date, at NAV 1.0, under both conventions. That date falls
  after the 2015-01-31 decision.
- **Window:** every run keeps every trade date from the start through the last decision. None is dropped or added.
- **Tranche combination:** the combined NAV equals an independently computed mean of the rebased tranches at every
  date.
- **Variant windows:** P4, P5, P6, P8 and P9 cover exactly the primary's dates. P7 covers exactly the month-ends
  from 2015-02-28 to 2022-11-30.
- **Losses inside the window:** a 40% crash planted in the 2015-03 prices appears in full in one evaluated period
  under both conventions. Under P7 it falls in the first evaluated period. No other period changes.
- **Losses before the window:** a crash planted in the 2015-01 prices falls before the start under both
  conventions, and neither run's evaluated NAV changes. The pre-start period is excluded the same way in both.
- **Edge cases of `combine_tranches`:** a tranche starting late, an empty tranche, a start date no tranche trades
  on, a missing middle valuation and a tranche ending early are all refused, never filled or trimmed.
- **Full run on synthetic data:**
  - `run_one` runs both trials with every gate (P4 to P9 and P11) through the real `run_combined`, `bt.run_trial`
    and registry gate.
  - `finish` then records all twelve results in one step, on a test registry, with no staged or pending file left.
  - Every verdict has P1 to P11, and none is labelled "E2 candidate" while check 4 is open.
- **Regression:** with run 1's start rule restored, the same end-to-end call stops with run 1's exact error. That is
  how these tests would have caught the defect.

## 5. Manifest

The fix changes one manifest-listed code file, `research/edge_b5_run.py`.

- The registered `B5-V3-RUN-MANIFEST-2` (`B5_RUN_MANIFEST_2.json`, sha256 10190052…9757) therefore no longer matches
  the code.
- That file and its record are kept unchanged and will never be used again, like `B5-V3-RUN-MANIFEST` before it.
- The proposed `B5_RUN_MANIFEST_3.json` lists the same 10 inputs and 16 code files. Only the hash of
  `edge_b5_run.py` and the manifest's note differ from MANIFEST-2.
- The proposed registry event is in `B5_V3_PROPOSED_MANIFEST_3_EVENT.json`, with a placeholder owner message.

## 6. Not done (needs separate owner approval)

- Registering MANIFEST-3.
- Releasing run 1's lock.
- Writing a new authorisation.
- Reading scoring data for a new run, or executing any trial.
- Merging PR #19, accessing the holdout, confirmation testing, or any demo or live-account change.

Survivorship bias remains material and unbounded. TTM check 4 is open and the E2 label is withheld.

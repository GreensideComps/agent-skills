# B5 V3 run 1 (D26): stopped with an error, nothing recorded

Run 1 is the B5 V3 exploratory run authorised under D26 (owner message cmsg_01U4KMvkBYNknqm4HRVie8uvUzn9qQCoyy3U7K3j4iY3kK, 2026-10-19 09:05Z).

- **Preflight:** passed. The one-run lock was created and committed (4215a98).
- **Error:** the run stopped while computing the robustness variants. The traceback is in `B5_RUN_1_FAILURE.txt`:
  - the call was `combine_tranches` inside `run_combined`, at `edge_b5_run.py:305`, the variant loop;
  - the error was `ValueError: every tranche must have a NAV on the evaluation start date`.
- **Probable cause (inferred from the code, not confirmed by running anything):**
  - `run_combined` always rebases tranches at `first_exec_date(data["exec"])`, which is the next-day-close execution date of the 2015-01 decision.
  - Variant P7 (next-month-close execution) has no NAV on that date.
  - The synthetic tests did not exercise P7 through `run_combined`.
- **State after the error** (exit code 1):
  - the registry is unchanged: `research/edge/trials.jsonl`, 239 lines, sha256 b027de18…, N = 102, no B5 results;
  - no `trials.staged` file, no `b5_trials.md.pending` file and no `b5_trials.md` report;
  - the lock is kept.
- **Results:** none were printed, written or recorded, so no result has been seen.
- **Next steps:** none taken. Per D26, there is no lock removal, no rerun and no code change without the owner's decision.

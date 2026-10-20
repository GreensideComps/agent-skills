# B5 run fix 1: atomic result recording (bug fix, no definition change)

Owner review 2026-10-19 08:35Z (item 4) and decision 08:40Z ("Fix first"). Version 2 §7 allows bug fixes to code
before a run; nothing in the specification changes. No trial, gate, threshold, statistic, input, universe, quality
rule or DSR rule changes, and N stays 102.

## Defects (found by code review of `edge_b5_run.finish`)

- **A.** The 12 results (2 primaries, 10 robustness runs) were appended with 12 separate registry writes. An
  external failure between them (process killed, disk error) would leave some results recorded.
- **B.** The shared DSR, the verdicts and the report came after the appends. A failure there (a non-finite Sharpe
  failing the DSR guard, a verdict error, a failed report write) would leave results recorded with no report, and
  a rerun would be refused.

## Fix

`finish` now: checks completeness and that each of the 12 ids is open and unrecorded; stages the 12 result events
in a copy of the registry (`edge_registry.stage`, registry untouched); computes the shared DSR (from the staged
copy, so it sees both primary results and N = 102) and the verdicts; writes the report to `b5_trials.md.pending`;
commits the staged copy over the registry in one rename (`edge_registry.commit`, refused if the registry changed
since staging); and finally renames the pending report.

- Any failure up to and including the commit leaves the registry byte-identical, with no report, pending report or
  staged copy. The one-run lock stays, so a rerun still needs a recorded owner decision.
- Only the final rename follows the commit. If it fails, the results are recorded once and the full report is in
  `b5_trials.md.pending`.
- Residual risk: if the process is killed outright between staging and the commit, the registry is untouched but
  the staged copy (`research/edge/trials.staged`) and possibly the pending report stay on disk and must be removed
  by a recorded owner decision.
- `edge_backtest.result_event` builds the result event that `record` already appended (same fields).

## Manifest

The code change alters three manifest-listed files (`edge_b5_run.py`, `edge_backtest.py`, `edge_registry.py`), so
the registered manifest `B5-V3-RUN-MANIFEST` (`docs/edge/B5_RUN_MANIFEST.json`, sha256 0f02eda1…7072) no longer
matches the code. That file and its registry record are kept unchanged and are never used by the run. The run now
reads `docs/edge/B5_RUN_MANIFEST_2.json` and requires it to be registered as `B5-V3-RUN-MANIFEST-2`, which needs
the owner's separate approval. Inputs and the list of 26 files are unchanged.

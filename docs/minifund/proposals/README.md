# Proposed changes awaiting owner review (not applied)

**Review pack for U0 (23 Oct 12:06Z decision): `U0_REVIEW_EVIDENCE.md`**, with the exact diffs, test commands and
exit codes, and before/after evidence (`U0_BEFORE_AFTER_EVIDENCE.json`). D-B now has a code proposal too:
`DB_prior_etf_families.patch`.

Nothing in this folder is applied. Each patch applies cleanly to master `b8cccb4` (or to the PR #27 head where
stated) and was tested in a scratch copy. The registry file `research/edge/trials.jsonl`, `research/edge_registry.py`
and every pinned artefact stay byte-identical.

## D-A: verdict annotations for the failed B5 V3 trials

### Design change from the audit's item 1.3

The audit suggested appending annotation events to `research/edge/trials.jsonl`. That would need two changes the
owner's guardrails protect against:
- `edge_registry.validate` rejects unknown event types, so the registry code would have to change. The D34 test
  `test_since_run_2_edge_registry_changed_only_in_the_spent_set` allows changes only to the spent-authorisation set.
  It failed in the scratch trial [V].
- The D33/D34 pin `test_historical_evidence_is_byte_identical_to_its_pinned_hash` holds the whole registry file at
  sha256 `de03d38b…`. Any append to that file breaks it.

Both protections were kept, so the proposal is instead **a separate append-only ledger**,
`research/edge/verdict_annotations.jsonl`, validated by a new module `research/edge_verdicts.py`:
- each line is hash-chained (`prev`), like the registry;
- each line names the registry line it annotates by number **and sha256**, plus the evidence report's sha256;
- it refuses annotating anything but a verdict-less `result`, a second annotation per trial, a verdict outside
  `pass/fail/inconclusive`, a missing `cmsg_` owner decision, or evidence whose hash differs;
- it adds no result, so `n_trials` stays 102 and the pooled Sharpe ratios are unchanged.

### Files

| File | What it is |
|---|---|
| `DA_VERDICT_ANNOTATION_EVENTS.json` | The exact two events proposed (H1 and S2a V3: `fail`, gates P1–P3 failed, report sha256 `5dee03ea…`, registry lines 241 and 242 with their line hashes). |
| `DA_verdict_annotations.expected.jsonl` | What the ledger would contain if appended on 2026-10-23. Appending on a later day changes `date` and therefore line 2's `prev`. |
| `DA_research_verdict_ledger.patch` | Adds `research/edge_verdicts.py` and `research/tests/test_edge_verdict_annotation.py` (11 tests). Applies to master. |
| `DA_pm_on_pr27.patch` | For PR #27 only: `pm.trial_verdicts` reads annotations; `from_repo` loads the ledger; 2 tests. Applies to `claude/office-pm` `ba825f2`. |

### Test evidence (scratch copies, offline, credentials stripped, Python 3.13.16, pytest 9.1.1)

| Run | Result |
|---|---|
| research suite, master + `DA_research_verdict_ledger.patch`, **annotations appended** | 471 passed (460 + 11 new) [V] |
| new test file, master + patch, **no ledger** (state before approval) | 11 passed [V] |
| office suite, PR #27 head + `DA_pm_on_pr27.patch` | 66 passed [V] |
| `test_pm.py` with the appended ledger present | 17 passed [V] |
| registry sha256 after appending | `de03d38b…` unchanged; `edge_registry.py` `129c0e2d…` unchanged [V] |

### How it would be applied, after approval

1. Merge `DA_research_verdict_ledger.patch` (code and tests only).
2. Run `edge_verdicts.append(<the two events>)` once. It refuses if anything differs from what is proposed here.
3. Commit the resulting `research/edge/verdict_annotations.jsonl` and run `python3 research/edge_verdicts.py`
   (expects "valid").
4. The pm patch goes onto PR #27 only if the owner reviews #27 further. It does not merge #27.

## D-C: wording for screen-1.0 and its paper book

Today every screen and paper report already prints "Evidence tier E1 … **unvalidated: not a recommendation**", and
`equity/config/evidence.json` records screen-1.0's pre-registered backtest as failed (IC t = 1.92 vs 2.0) [V]. The
audit understated this (corrected in its §4).

`DC_evidence_labels.patch` (equity only, master):
- `evidence.json`: the allowed use of `screen-1.0` and `paper-1.0` says "unvalidated exploratory research, not
  investable evidence (owner decision D-C)";
- `evidence.py`: the banner reads "**unvalidated exploratory research: not investable evidence, not a
  recommendation**";
- one new test. The equity suite gives 119 passed (118 + 1) [V].

This changes text the daily equity pipeline prints, so it takes effect from the first run after a merge.

**PR #27 follow-up (not in this patch):** PR #27 adds `paper-1.1` but no `evidence.json` entry, so its banner shows
E0 with "allowed use: none recorded" (INTERFACES C12). Proposed entry:
`"paper-1.1": {"tier": "E1", "evidence": "paper-1.0 plus a VWRP total-return benchmark book (D-T14 A).",
"allowed_use": "prospective record of screen-1.0 only: unvalidated exploratory research, not investable evidence
and not advice (owner decision D-C, 2026-10-23)"}`.

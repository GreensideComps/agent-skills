# B5 final pre-run audit (round 6)

Owner review 2026-10-19 07:04Z. Written before any H1 or S2a score, ranking, return, NAV, Sharpe ratio or verdict
has been computed. Nothing here registers the manifest, authorises or runs the trials, touches the 2023-26 holdout,
or changes any account. TTM check 4 stays open. The frozen specifications are unchanged (hashes in §3).

## 1. Point-in-time share counts (identity rule C)

**Source fields.** Rule C's `mcap` is `xsection.load` (`research/xsection.py:43-44`): `shares_out` if > 0, else
`shares_diluted`, times `close_raw`. Both share fields, and `total_assets`, come from `monthly_metrics.csv.gz`,
built by `equity.monthly.company_months` (`equity/equity/monthly.py:50-91`) from the SEC fact panel:

| Field | SEC fact | Selection at month-end `mo` |
|---|---|---|
| `shares_out` | `dei:EntityCommonStockSharesOutstanding` (cover page, instant) (`panel.py:30`) | `panel.latest(rows, mo)` (`monthly.py:84`): latest `end`, among rows with `filed <= mo` |
| `shares_diluted` | us-gaap weighted-average diluted shares (duration) | `panel.known(rows, mo)` (`monthly.py:81`): rows with `filed <= mo`, latest period end |
| `total_assets` | us-gaap `Assets` (instant) | `panel.latest(rows, mo)` |

**As-of logic.** `panel.known` (`equity/equity/panel.py:114-124`) drops every row with `filed > as_of` before
anything else, then keeps per period the best-ranked concept's latest filing. The panel stores each distinct value
at its first filing date (`panel.extract_company`), so a restated or amended count is a new row with its own later
`filed` date. A value filed after the month-end therefore cannot be selected for that month, whatever period it
describes. `company_months` recomputes a month only from filings dated on or before it, then carries that row forward.

**Evidence on the real data** (`research/edge_b5_share_pit_audit.py`, report
`equity/reports/research/edge/b5_share_pit_audit.md`). 4,878 company-months from 816 companies: every
large-band row from 2012 with mcap above 25 times total assets (1,878: all rule C exclusions and the 25-100x zone),
plus 3,000 random rows. Each was rebuilt from SEC facts filed on or before its own month-end only and compared
with the stored value.

| Field | Match | Mismatch | Rows where a later filing would differ |
|---|---:|---:|---:|
| `shares_out` | 4,878 | 0 | 756 |
| `shares_diluted` | 4,878 | 0 | 2,523 |
| `total_assets` | 4,878 | 0 | 3,022 |

The last column shows the leak is real in the raw data (later filings exist for those periods) and is not taken.

**Regression tests.**

- `equity/tests/test_monthly.py::test_share_counts_filed_after_the_month_end_never_change_that_month`. An amended
  cover count, a restated diluted count, a late count for a date before the month-end and a late balance sheet, all
  filed afterwards, leave the month unchanged. Each one is used only from the month-end after its own filing.
- `research/tests/test_edge_b5_pit_path.py::test_a_share_count_filed_after_the_decision_month_never_changes_its_mcap_or_rule_c`.
  This test goes through the production path (`company_months`, then the files, then `xsection.load`, then
  `identity_ok`). A late 1000x count leaves the decision month's mcap, band and rule C result unchanged. The test
  can fail: the month after that filing is excluded by rule C.
- `...::test_the_cover_count_falls_back_to_diluted_only_from_facts_known_at_the_month_end`.

No correction was needed.

## 2. T2 and the production path

**Path.** `edge_b5_run.load_inputs` does three things:

- It reads fact rows with `r["filed"] <= "2022-12-31"` (line 183).
- It calls `attach_fundamentals` (new, lines 155-161), which calls `edge_b5_inputs.company_month(rows, month)` for
  each row's own month-end, with no `align` and no `retro_as_of`.
- `company_month` uses `ttm_input` and `panel.known` (filed ≤ month-end), `revenue_check` (T0/T1: `r["filed"] <=
  as_of`) and `restated_check(rows, as_of, sel)`, where `seen = compare_as_of or as_of` and `compare_as_of` is never
  passed (`edge_b5_inputs.py:105-146`).

So revenue, cost of revenue, the `GrossProfit` tag, OCF and capex use only filings available by the decision
month-end. `_restated_retro` (the later-filings diagnostic) is computed only when `retro_as_of` is given, which only
`edge_b5_input_audit.py` does. It is not among the columns the run keeps (`FUND_COLS`) and never affects
eligibility.

**Tests** (`research/tests/test_edge_b5_pit_path.py`, production functions `attach_fundamentals`,
`s2a_profitability`, `h1_velocity`):

- `test_a_filing_after_the_decision_month_never_changes_its_inputs_flags_or_eligibility`. A recast of the prior-year
  half of every input, filed after the decision month, leaves every loader column, the S2a value and FCF unchanged
  for that month. The same filing makes all four T2 flags true and S2a and FCF unavailable from the next month-end.
- `test_the_same_recast_filed_before_the_decision_month_does_change_it`. This is the sensitivity check: the test
  above would fail if dates were misused.
- `test_the_run_never_asks_for_the_retrospective_diagnostic_or_alignment`. A source check: the run contains no
  `retro_as_of`, `compare_as_of`, `align=True` or `_retro`, keeps the 2022-12-31 fact cut, and calls `company_month`
  with the row's month only.
- Existing: `test_t2_is_point_in_time_later_filings_cannot_change_it`, and the real-data truncation check (6,249 rows,
  0 differences).

## 3. Manifest and hashes

The audit found that the run path also imports four repository modules the round 5 manifest did not hash:

- `research/data_sources.py`
- `equity/equity/__init__.py`
- `equity/equity/fundamentals.py` (the concept lists and ranks)
- `equity/equity/industry.py`

The manifest now covers 10 inputs and **16** code files, written by `research/edge_b5_manifest.py`. A new test
(`test_the_manifest_covers_exactly_the_repository_code_the_run_imports`) imports the run path in a clean process and
requires the manifest's code list to equal the set of repository modules imported. `edge_b5_run.py` and
`edge_registry.py` changed (§4), so their hashes changed. The manifest is still **not registered**.

`docs/edge/B5_RUN_MANIFEST.json` sha256 **7efb5f05f174e23abfb727b0b87922724d86e1e1daa79b8f6cf1354e85fe674f**
(round 5: ba58471e…2b70). Every file's actual hash equals its manifest entry:

| Input | sha256 |
|---|---|
| /mnt/project-files/research-data/monthly_metrics.csv.gz | ae5429b661bd060d040109138d35cb4ea22356d4a549056c8616c3a2a7e87561 |
| /mnt/project-files/research-data/prices_monthly.csv.gz | 505115711f7ef59c8df417671f8afecf77dd2240e13a2a3bdff453721b3d801a |
| /mnt/project-files/research-data/sec_companies.csv.gz | acf5e3f746c355aa2c0aa2b76c0c3f55413daf5e927524672537d0389d214a90 |
| /mnt/project-files/research-data/sec_facts_panel.csv.gz | 2a56736fdea7825485233697705b63c0c0d4fbb6c47fcd905b8bfe6183765453 |
| /mnt/project-files/research-data/edge/exec_prices_to_2022.csv.gz | dd6608f62ae2676fd4fd5b3b256105d5f52eb720ba3a10a2965cf504e17d47dc |
| /mnt/project-files/research-data/edge/gbpusd_daily_to_2022.csv.gz | fd9f8e7dc921465732460a507225778ea9d14437dfd5026f4b37f3dd54310d65 |
| /mnt/project-files/research-data/edge/benchmarks_daily_gbp_to_2022.csv.gz | 0ec17f8631a17cc6f7cc3ca7e1f8054437371e2012739926d4ccfffa0b1f6fc6 |
| research/edge/factors/F-F_Research_Data_5_Factors_2x3_to_2022.csv | 0b49e5f01fd42ef82413bfcd1a6fcf0da9c454f30406d608c2b9bf361aa7007c |
| research/edge/factors/F-F_Momentum_Factor_to_2022.csv | 2ea2bc33229be0ee9ec1b61ab07650abb4b5f14715d2eac2d79bb633fb7d8a5c |
| equity/reports/research/edge/exec_prices_audit_moves.csv | 2d3221010ebb4edc2ed9ae04056ca1ed49f6fd6c7d35dc970486eef9479a6edb |

| Code | sha256 |
|---|---|
| research/edge_b5_run.py | 75f4f52b558f2c3a1467f7f2df28965160114795e1ec45fb5db65bafefd39a2e |
| research/edge_b5.py | 74b88f5a2539c02b9a57552e59607ae3eb09c199c12037cedb068ec34bed64a0 |
| research/edge_b5_inputs.py | 7a37fa077237986e5a684e5018d8835ca759d7230069d7db6d1369d969185cf3 |
| research/edge_b5_stats.py | 98ebf0196345f40a70c2995dc147fab480ced05f84fd969fcd2cde90ad4a379d |
| research/edge_backtest.py | 425dc3d0dcdb11d4e4af33e5ef2bd1825c52da2ef3ab726f6a7874cfab769bb2 |
| research/edge_rules.py | 9f6aeb7fe22effdbd93ff0738520c7a88ed2d52e5323451a27e28984e78f41e9 |
| research/edge_registry.py | 7eb4753d80defb9e17eb00e43b64158b832e444eab166cf57547a0f16d4a571b |
| research/edge_split.py | 45bac72280a5ac1aaf373f23af82ad2f6e7abf509049e21a831c6ab9ee83d943 |
| research/xsection.py | a4f265ce6c1308f51b18800c915973240af2f226a13f8c3fb6c06cce76937f16 |
| research/stage2.py | 4491915168676581e9b263cd7e3a92a90fa991d4bd11ba238e9ced11d52436bc |
| research/edge_exec_prices.py | 14a4f1d8b655e8be28c09882227cd1ecefede23921b09949dc536f30f8982802 |
| research/data_sources.py | dcdbdf26db3d07ec847fab238400056391b937e3f0250ccc9e3c8176e9b5b8e4 |
| equity/equity/__init__.py | aa8bf8bca2a55423e3b73a212c9894a5a776cad8ed7f612af65edeeef6823bf0 |
| equity/equity/panel.py | 5586a431ff03b1aa4aecee75eaa7cc84672ae4e03d1d018760de70de356a5d9a |
| equity/equity/fundamentals.py | d8c4bab78dc0b12de3e506fd12fc2df77e6d21a938052f9a0b3bb0a28cdb9aef |
| equity/equity/industry.py | f8122eba16de5f751c606ab4bba5cf787f15772bd811eeaa7bcb1acc30d5a8f0 |

**Registered specifications** (registry entry = actual file hash, all true):

- B5-H1-FCFPS-ACCEL-V2 and B5-S2A-GP-12M-V2: `B5_PREREGISTRATION.md` 51acdd22673b1a6d46ee133a56f797c23aa1e8b833f5712709a070d26dd90d18
- B5-V2-ADDENDUM-1: 0ac282628c49576f2c788a6afbc56c29140c95da3c8176e9450d5163cce87595
- B5-V2-ADDENDUM-2: 50a5a18f83472b01373ea13646cb62b927809ed2a3999551178218bf3187f80e

Other registry facts: N = 100; B5-V2-RUN-MANIFEST is not registered; no result exists for any B5 trial or
robustness id; `status.json` `b5_trial_run.authorised` is false; no lock exists.

## 4. Execution controls

Round 5's controls lived in `preflight`, which only `main` calls. A script could import `load_inputs`, `run_one`
or `bt.run_trial` directly and compute trial outputs without the authorisation or the lock. Running `main` against
copied files could do the same. This round closes both gaps.

| Control | Where enforced | Tests |
|---|---|---|
| Owner authorisation (message id) | `preflight` (lines 92-95). Also `edge_registry.b5_run_open` (`edge_registry.py:146`), which reads the **real** `status.json` and lock only: `authorised is True`, a `cmsg_` id, and a lock naming the same id | `test_refused_without_the_owners_recorded_authorisation` (4 cases), `test_the_gate_needs_the_authorisation_and_a_lock_naming_the_same_message` (4 cases), `test_in_the_real_repo_the_run_is_closed` |
| One-run lock | `preflight` creates it with O_CREAT\|O_EXCL after every other check (line 122). It is never removed and not git-ignored, so it shows in `git status` | `test_preflight_passes_once_and_the_lock_refuses_a_second_start`, and every refusal test asserts no lock |
| Prior-result check | `preflight` refuses any result for the 2 trials or 10 robustness ids (line 120). `edge_registry.require` refuses a repeat per id | `test_refused_when_any_trial_or_robustness_run_already_has_a_result`, and the second `finish` in `test_finish_records_both_results_before_any_dsr` |
| No alternate invocation | `edge_registry.require` now refuses all 12 B5 ids unless `b5_run_open()` holds (line 193). Every `bt.run_trial` and `bt.record` calls `require`. `load_inputs`, `run_one` and `finish` call `b5_run_open()` first. `main()` takes no parameters | `test_no_b5_trial_or_robustness_id_can_run_or_be_recorded_while_closed` (12 ids), `test_a_copied_registry_and_status_cannot_open_the_run`, `test_main_has_no_parameters_so_it_always_uses_the_real_files`, `test_no_option_can_skip_a_gate_choose_a_trial_or_change_a_setting`, `test_the_gate_ids_are_exactly_the_run_scripts_trials_and_robustness_runs`, `test_other_registered_ids_are_not_gated` |
| Complete robustness runs | `run_one` raises if any of P4-P9 or P11 is missing. `finish` now checks every trial's variants and robustness results **before the first append** (lines 303-308), so a partial run records nothing | `test_run_one_refuses_when_a_variant_run_is_missing`, `test_a_partial_run_records_nothing` (4 cases), `test_a_missing_robustness_input_still_fails_its_gate_closed_in_the_verdict` |
| Shared DSR | `finish` records both primary results, verifies both are in the registry (line 316), then computes each DSR. It requires N = 100 and at least 2 comparable results | `test_finish_records_both_results_before_any_dsr` (a spy confirms both results exist at each DSR call), `test_finish_refuses_one_trial_alone` |

What code cannot stop: someone writing new code that reads the raw data and recomputes the scores outside these
functions. That is covered by the registry rules, the data-access guard test (`test_edge.py`) and git history, not
by the gate. A test process can repoint the gate's paths (the `opened` fixture); production code has no parameter
to do so.

## 5. Remaining limitations

- **Survivorship bias.** The universe needs a price, so companies that delisted before the 2026 price download are
  missing. Nothing bounds this bias, and the −100% stress does not address missing companies.
- **No result here is proof of a deployable edge.** These are exploratory trials on 2015-2022 free data.
- **TTM check 4 is open**, so no result can carry the E2 label.
- **Quality flag uses a window median.** The approved share-outlier flag (`edge_split.share_outliers`, owner
  decision D5) takes each company's median share count over the exploration window, which runs through 2022-12. That
  is later information inside exploration, used for universe eligibility, not for rule C. It is pre-registered;
  robustness run P9 re-runs both trials with a point-in-time median. It is unchanged here because changing it would
  change the frozen specification.
- **`close_raw` reconstruction.** The price is rebuilt by undoing Yahoo's later split adjustments. It is right only if
  Yahoo's split history is complete. A split between a share-count date and the month-end mismatches count and
  price; that is a staleness error, not look-ahead.
- **The builder is checked, not hashed.** `equity/equity/monthly.py` builds `monthly_metrics.csv.gz` but is not
  imported by the run, so it is not in the code manifest; its output is hashed as an input. The 0-mismatch audit
  ties that output to the builder on a 4,878-row sample, not on every row.
- **Filing date as availability.** Availability is SEC's filing date: a filing dated on the month-end counts as
  known at that month-end. Trades execute at the next day's close.
- **Input-rule limitations** (`KNOWN_INPUT_LIMITATIONS`, printed in every B5 report): the General Dynamics false
  positive, the Abbott missed case, derivative-basis flags, rule C residuals from 25x to 100x, and Scinai.

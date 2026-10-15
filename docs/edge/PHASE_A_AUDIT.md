# Edge-discovery programme, Phase A: audit, data-split check and gap analysis

Written 2026-10-14 on branch `claude/edge-discovery-phase-a-j78pyp`, from `master` at `e8ec0e2` (PR #17 merged).
Evidence is cited as files, commits or command output from this session. Where something is inferred rather than
checked, it says so.

**Update, same evening:** the owner's decisions and the verification review they asked for are in §10. That
section supersedes §7-§9 and the counts it corrects. §11 records the owner's PR #18 review: the trial count is
now 96 (101 registry entries), and 253 large-cap months are flagged as share-count outliers.

**Bottom line.** The repository has a sound core for honest testing: point-in-time SEC data, a cross-sectional
harness, pre-registered Stage 2 tests that reproduce exactly, Newey-West statistics, factor alpha and a deflated
Sharpe. Phase A added what the new programme was missing (a separate trial registry, a code-level holdout guard,
written split and evaluation rules, Stage 2 diagnostics, data-integrity checks). Three things stop Phase A from
being complete: **the 2023-2026 holdout has been partly seen** (§3), the owner has not yet approved the split and
the rules that depend on it, and the dataset has **defects** that the programme must exclude or fix (§4.3).

---

## 1. Repository state

| Item | State |
|---|---|
| Base | `master` at `e8ec0e2`, clean working tree. The container's local `master` was stale (`edd9dc8`); the branch was cut from the fetched `origin/master`. |
| Branch | `claude/edge-discovery-phase-a-j78pyp` |
| Tests before changes | research 12, equity 117, trading 139: **268 passed** (no CI in the repo; run locally) |
| Research data | `/mnt/project-files/research-data/`: metrics 2009-12 to 2026-09, prices 2011-01 to 2026-10, insider trades 2014-01 to 2022-12. No `signal_log/` directory yet (first run 2026-11-03). |

## 2. Audit: what already exists

### 2.1 Stage 2 signal definitions, results and diagnostics

- **Definitions:** `research/prereg/stage2.md` (11 trials, then addenda for S6c, S7a, S7b and S9) and
  `research/stage2.py` `TRIALS`. Tests in `research/tests/test_stage2.py` (lags, insider windows, residual momentum,
  DCF, base rate uses no future data).
- **Results:** `equity/reports/research/stage2_signals.md` and `.json`: 0 of 15 pass in large caps,
  2015-01 to 2022-11.
- **Reproduced in Phase A:** `python3 stage2.py` on today's data gives a byte-identical report and identical JSON
  for every trial (mean IC, t, DSR, verdict).
- **Diagnostics that already existed:** mean IC, NW t, IC hit rate, decile spread and t, top-quintile net, turnover,
  sub-period IC, up/down market IC, sector IC, FF5 + momentum alpha, DSR. The JSON had every figure the programme
  doc left blank; the blanks were an extract gap, not missing data.
- **Diagnostics that were missing:** IC standard deviation and minimum detectable effect (power), horizons beyond
  1 month, overlap-aware standard errors, non-overlapping checks, factor loadings in the report. Added (§5).

### 2.2 Trial registration and experiment tracking

| Registry | What it holds | Verified? |
|---|---|---|
| `research/stage2.py` `TRIALS` + `prereg/stage2.md` | Stage 2's 15 trials, counted in its DSR | Order shown by git: prereg `42cefcc` (16:29:17) before results `1256fcc` (16:30:53); addenda likewise. Git proves commit order, not that nothing was run before a commit. |
| `research/experiments/E001-E015.json`, `AGENDA.md`, `LOG.md` | ETF and allocation research (132 trials) | Schema validated by `trading/tests/test_m2_intelligence.py`; a different question (ETFs), not reused here |
| `equity/research/screen_backtest_prereg.md` | M8 screen test (1 trial) | Committed before results (`51c9031` → `290510e`) |
| Post-hoc audit sub-scores (`bt_audit.py`) | 5 exploratory ICs | Not registered anywhere; Stage 2's DSR did not count them |
| **New:** `research/edge/trials.jsonl` | The programme's own registry | Added in Phase A (§5) |

### 2.3 Historical data, filing timestamps, survivorship and ticker mapping

- **Filing timestamps:** each fact is kept at its first filing date (`equity/panel.py`); monthly metrics use only
  filings on or before the month-end (`equity/monthly.py`). Checked: 0 of 1,440,013 rows use a later filing.
- **Quarterly fundamentals exist:** 10-Q facts and trailing-twelve-month figures (`panel.ttm`). Not independently
  cross-checked: the only second-source check (13 companies vs Yahoo) was on annual figures.
- **Survivorship:** measured, not fixed. Companies that stopped filing have fundamentals but 0% have prices
  (Stage 1 report). Fixing it needs paid data (owner decision, deferred).
- **Ticker mapping:** each company is priced from the first ticker in **today's** SEC list
  (`equity/monthly.py` line 149). One ticker per company (5,360 companies); other share classes are ignored; no
  point-in-time ticker history.
- **Industry:** SIC is today's code (`sec_companies.csv.gz`), so sector-neutral ranks use a mildly forward-looking
  classification.
- **Data is rebuilt monthly:** `monthly_signal_log.sh` runs `research-data --refresh`, overwriting these files.
  Nothing recorded which file versions Stage 2 used. Phase A adds a manifest (§5).

### 2.4 Statistical testing, standard errors and overlapping horizons

- Spearman IC per month with a Newey-West t (3 lags) (`xsection.newey_west_t`), tested on a planted signal.
- Stage 2 measured 1-month outcomes only, so overlap never arose. Nothing handled overlapping multi-month outcomes.
  Phase A adds max(3, h) lags plus a non-overlapping cross-check (`stage2_diagnostics.ic_stats`, tested on a
  12-month moving-average series).

### 2.5 Factor-adjusted alpha and deflated Sharpe

- `stage2.factor_alpha`: FF5 + momentum OLS with a Newey-West intercept SE. **Had no test**; Phase A adds one that
  recovers a planted alpha and betas.
- `stage2.deflated_sharpe`: Bailey and López de Prado. Existing test only checked that more trials lower it;
  Phase A adds a check against the formula computed by hand.
- `research/engine.py` has a second DSR and block bootstrap for ETF strategies.

### 2.6 Portfolio backtesting, transaction costs and VWRP benchmarking

- **Stocks:** only the xsection harness (equal-weighted top quintile, monthly, 0.30% one-way on turnover) and the
  annual M8 backtest. **No concentrated 15-30 name portfolio, no rebalancing buffers, no sector caps, no GBP
  returns, no VWRP comparison.**
- **ETFs:** `research/engine.py` (monthly, costs, drift, lag check, bootstrap) and `research/dataset.py` (a GBP
  VWRP series: VWRL.L spliced onto a Ken French developed-market proxy). Reusable for the benchmark.
- **Costs:** 0.15% FX is Trading 212's published fee; the 0.15% spread is an estimate with no fill data behind it.

### 2.7 Exploration, confirmation and prospective monitoring

- STRATEGY_V2 §2.2 reserved one holdout for one use. Stage 2 enforced it in its own code (`run()` cuts at
  `END`; an assert checks the file holds the holdout). There was **no shared guard** that other research had to
  use, and no written rule for repeated confirmation.
- Prospective: `research/signal_log.py` logs from 2026-10-31, write-once, outcomes joined only after the month ends
  (tested).

### 2.8 Automation, tests, reporting and failure handling

Scheduled tasks, read from the scheduler on 2026-10-14:

| Task | State | Note |
|---|---|---|
| Research: monthly signal log | enabled, next 2026-11-03 | Runs tests first and stops on failure (exit 4). **Not in `equity/config/schedule.json`**, so the reliability check would not notice a missed run. |
| Equity: daily research pipeline | enabled | Same session as the signal log |
| T212 demo: research loop (ETF research, `research/LOOP.md`) | **enabled**, twice daily | Still targets the old `claude/trading212-agent-skills-r71zy3` branch and its "£100 account" brief. It may add shadow strategies; trading ops is disabled, so it cannot trade. |
| T212 demo: hourly trader + monitor, trading ops | disabled | As memory records |
| Weekday portfolio brief, weekly stock discovery | enabled | Read-only |

- **No CI**: tests run only inside routines and by hand.
- `trading/STATUS.md` is stale: it still describes `discretionary_intraday_v1` as current although the trading
  tasks are disabled.

## 3. The data split: what the holdout was for, and whether it has been seen

**Original purpose.** STRATEGY_V2 §2.2 (`0c9fab3`): "2023-01 to 2026-09 is held out for all signals until the
combined model is frozen, and is used once." It was for one final test of a combined model, which was never built.

**What did not touch it (checked):**

1. Stage 2's signal tests. `stage2.py` cuts decisions at 2022-11 before evaluating; all 15 JSON windows end
   2022-11-30; and Phase A's diagnostics, which **cut the data at 2022-12 before building any feature**, reproduce
   Stage 2's large-cap ICs (§6). So Stage 2's scores did not depend on post-2022 data.
2. The monthly signal log: starts at 2026-10-31; no log file exists yet.
3. Stage 1's coverage tables for 2023-2026: row counts, not outcomes.

**What did touch it (checked):**

| Look | When | What was read | Relevance to the new hypotheses |
|---|---|---|---|
| M8 screen backtest (`290510e`) | before STRATEGY_V2 | 12-month returns of the April 2022, 2023, 2024 and 2025 cohorts (outcomes to 2026-04), IC +0.147, +0.109, +0.260, −0.094 | **High.** screen-1.0 combines FCF-per-share growth, quality, valuation, dilution and leverage: the raw material of H1, H4 and H8 |
| 14 Oct audit sub-scores (`bt_audit.py`) | 2026-10-14 | Post-hoc ICs pooled over all 14 cohorts: FCF per share t = 2.9, valuation 1.4, quality 0.5, growth 0.2, risk −0.8 | **High.** The in-house precedent for H1 includes holdout-period cohorts |
| Programme proposal | 2026-10-14 18:58 | Ken French US factor means for 2023-2026 (HML −0.6, RMW −3.0, CMA −6.9, Mom 0.1, SMB −4.1), used to argue against factor strategies | **Medium-high.** It shaped which hypotheses were proposed |
| ETF research E001-E015 | 2026-10-13/14 | Out-of-sample periods to 2026-09, factor premia 2011-2026, BIG HiPRIOR / HiOP portfolios | Medium: factor-level |
| Stage 1 harness check (`ddb0770`) | 2026-10-14 | Equal-weighted large-cap return 2012-01 to 2026-08, as one number | Low |
| 14 Oct portfolio validation | 2026-10-14 | 5-year daily prices of 22 holdings and VWRP | Low-medium: specific stocks |
| General knowledge | always | How markets moved in 2023-2026 (the model's training data and the owner) | Cannot be removed |

**Conclusion.** The holdout is **not untouched**. Signal-level Stage 2 work never read it, but composite and
factor-level outcomes for 2023-2026 were read, and some of that shaped the new hypothesis list. It can still reject
ideas cleanly; a pass on it is conditional confirmation. Stage 2's commit order is consistent with pre-registration,
but git cannot show whether code ran before a commit. The policy and the open decisions are in
`docs/edge/SPLIT_POLICY.md`. Every look above is in the registry with `touched_holdout: true`.

**A further split risk.** The proposed rule "used once per pre-registered batch" lets the same 45 months confirm
batch after batch, each designed by someone who has seen the previous batch's holdout result. That needs an owner
decision (SPLIT_POLICY §6.2); the guard allows one run per batch but cannot stop knowledge carrying over.

## 4. Gap analysis

Status key: **V** implemented and verified · **U** implemented, not adequately verified · **P** partially
implemented · **M** missing · **B** blocked by a decision or data limitation. "After" is the status at the end of
Phase A.

### 4.1 Research governance

| Component | Before | After | Evidence | Minimum fix | Test of completion |
|---|---|---|---|---|---|
| Stage 2 definitions and results | V | V | prereg + code + tests; reproduced byte-identical today | none | `stage2.py` reproduces `stage2_signals.json` |
| Separate programme trial registry | M | V | none existed | `research/edge/trials.jsonl` + `edge_registry.py`: append-only, hash-chained, validated | `test_edge.py` registry tests; `python3 edge_registry.py` exits 0 |
| Prior looks recorded with holdout exposure | M | V | M8 and audit looks were unrecorded | 10 inherited entries with `touched_holdout` | `test_committed_registry_is_valid` |
| Exploration/confirmation/prospective policy | P | V (provisional) | single-use rule in STRATEGY_V2 only | `docs/edge/SPLIT_POLICY.md`; owner approval D1-D4 (`DECISIONS.md`) | approval recorded; gate and registry enforce one batch |
| Holdout guard in code | P (Stage 2 only) | V for exploration; confirmation locked | `stage2.run` cut only | `edge_split.exploration_view`, `assert_exploration_only`, `holdout_gate` | split tests: a 7x change to every 2023+ price changes nothing in the view |
| Holdout cleanliness | — | B (permanent; handled) | §3 | owner decided a pass is conditional E3, with 12 months of prospective evidence before demo capital (D3) | decision recorded |

### 4.2 Statistics

| Component | Before | After | Evidence | Minimum fix | Test of completion |
|---|---|---|---|---|---|
| IC + Newey-West t (1 month) | V | V | planted-signal test | none | existing tests |
| Overlapping horizons (3, 6, 12 months) | M | V | 1-month only | NW lags max(3, h) + non-overlapping t | `test_nw_se_...`, `test_diagnostics_find_a_planted_signal_at_every_horizon` |
| Power / minimum detectable effect | M | V | not reported | MDE and power in `ic_stats` | `test_ic_stats_mde_and_power`; diagnostics report |
| Factor-adjusted alpha | U | V | no test | planted-alpha test | `test_stage2_factor_alpha_recovers_planted_alpha_and_betas` |
| Deflated Sharpe | U | V | monotonicity test only | hand-computed check | `test_stage2_deflated_sharpe_matches_a_hand_computation` |
| Trial count spanning all looks | P | V | Stage 2 counted its own 15 only | `edge_registry.n_trials` (96 after §11) | registry tests |
| Written statistical specification | P | V | scattered across prereg docs | `docs/edge/EVALUATION_SPEC.md` §3, §5 | reviewed by the owner 2026-10-14 |

### 4.3 Data

| Component | Before | After | Evidence | Minimum fix | Test of completion |
|---|---|---|---|---|---|
| Point-in-time filing dates | V | V | 0 rows with a later filing | none | `edge_integrity` check |
| Quarterly fundamentals | U | U | built; no second-source check of quarterly TTM; staleness measured (§10.4) | the four checks in §10.4 | as §10.4 |
| **Share-count scaling errors** | unknown | P (flagged, not fixed) | 253 (283 in the draft, whose median used 2023-26 data; §10.2) of 43,220 large-cap company-months (53 companies) with shares > 10x or < 1/10 of the company's median, e.g. 1.9e14 shares; puts small companies in the large band | programme excludes flagged rows (`quality_flags`); a fix in `equity/monthly.py` would change the signal log's inputs, so it needs its owner thread | flag count 0 after a fix, or exclusion applied in every programme test |
| **Negative adjusted prices** | unknown | P (flagged, not fixed) | 344 price rows ≤ 0 (6 companies), 4 of them large-cap Stage 2 months (NFE 2022) | exclude in the programme; fix at source later | `edge_integrity` FAIL clears |
| Extreme returns | unknown | P | 3,864 monthly moves over 100% to 2022-12, largest +1.7e9% (small caps) | exclusion or winsorising rule registered per trial | stated in each trial |
| Mis-dated XBRL periods; negative share counts | unknown | P (WARN) | 106 rows / 15 companies; 4 rows | none needed for rank tests; noted | — |
| Survivorship | B | B | 0% of stopped filers priced | paid data (owner) | — |
| Ticker mapping / share classes | P | P | first ticker of today's SEC list | point-in-time ticker history (paid or SEC submissions history) | — |
| Point-in-time industry | P | P | today's SIC | SIC from historical filings | — |
| Dataset versioning | M | V | files rebuilt monthly, versions unrecorded | `edge_integrity.manifest` (SHA-256, rows, months); required in every batch | manifest in each result |
| Insider data for confirmation | — | P | ends 2022-12 | rebuild insiders to 2026 before any insider confirmation | integrity WARN clears |

### 4.4 Portfolio evaluation

| Component | Before | After | Evidence | Minimum fix | Test of completion |
|---|---|---|---|---|---|
| Concentrated 15-30 name strategy backtester with buffers and sector caps | M | M | xsection tests a ~100-name quintile only | Phase B: minimal backtester per EVALUATION_SPEC §4, reusing xsection | planted-signal strategy test; reproduces the xsection quintile when N = 20% |
| Band-specific costs | P | P (specified) | flat 0.30% | implement per spec | cost test |
| GBP returns and VWRP benchmark for stock strategies | M (ETF side exists) | M (specified) | `dataset.py` WORLD series exists | wire `usd_to_gbp_monthly` + WORLD into the backtester | IR vs VWRP reproduces on a known series |
| Factor-matched benchmark | P | P | alpha regression exists | apply to strategy returns | as above |

### 4.5 Automation and reporting

| Component | Before | After | Evidence | Minimum fix | Test of completion |
|---|---|---|---|---|---|
| Tests | V locally | V (268 + 28 new = 296) | no CI | optional CI workflow (owner: adds a GitHub Action) | — |
| Signal-log routine monitored for missed runs | M | M | absent from `schedule.json` | add an expectation (owner thread of the signal log) | `python -m equity reliability` flags a missed 3rd |
| Stale ETF research loop | — | paused | enabled on an old branch and brief | paused (D6) until reviewed and retargeted | scheduler shows it disabled |
| `trading/STATUS.md` current | P | P | describes the disabled intraday strategy | refresh in the trading thread | — |

## 5. What Phase A changed

Every change is a new file. No existing file was modified: Stage 2's code and results, the signal log, its schedule, the trading code and the account are untouched.

| File | Why |
|---|---|
| `research/edge_split.py` | Split boundaries by outcome month; `exploration_view` cuts data before features and drops forward returns that reach 2023; `holdout_gate` refuses confirmation without a batch, a pre-registration commit and the owner's approval |
| `research/edge_registry.py`, `research/edge/trials.jsonl` | The programme's own append-only, hash-chained trial registry, seeded with Stage 2's 15 trials, 6 M8 looks and 4 other holdout exposures, then the 45 diagnostic horizons (registered before they ran) |
| `research/stage2_diagnostics.py` | Missing Stage 2 diagnostics on exploration data only |
| `research/edge_integrity.py` | Read-only data checks and the dataset manifest |
| `research/tests/test_edge.py` | 19 tests for the above, including the first test of `stage2.factor_alpha` and a hand check of `stage2.deflated_sharpe` |
| `docs/edge/SPLIT_POLICY.md`, `docs/edge/EVALUATION_SPEC.md`, this file | Policy, rules and audit |
| `equity/reports/research/edge/` | Diagnostics and integrity reports from this run |

## 6. Stage 2 diagnostics: findings

Full tables: `equity/reports/research/edge/stage2_diagnostics.md`. All on exploration data only; large caps
unless stated.

- **Reproduction proves Stage 2 did not use post-2022 data.** With the dataset cut at 2022-12 before any feature
  was built, all 15 large-cap ICs and month counts match the published results.
- **Most nulls were underpowered.** The minimum detectable mean IC ranged from 0.011 to 0.036. For 11 of 15
  signals the chance of detecting a typical IC of 0.02 was below 50% (S6a, S6b, S9, S3a, S5a: about 20%). For those,
  "fail" means "not detected", as the programme proposal said.
- **Three nulls were well powered, so they are informative:** insider net buyers S7a (power 80%) and insider
  purchase value S7b (96%) and low accruals S2b (63%) had enough precision to see an IC of 0.02 and found about
  zero. That revises the proposal's reading of S7 as an implementation problem: as built, in large caps, there is
  little there.
- **Evidence against, not just absence:** residual momentum S6c is negative at every horizon and significantly so
  at 12 months (IC −0.050, NW t −2.51, non-overlapping t −3.19). Revenue acceleration S3b turns negative at 12
  months (−0.033, t −2.00; non-overlapping −1.68).
- **The one rising pattern:** gross profitability S2a strengthens with horizon (IC 0.013, 0.028, 0.038, 0.061 at 1,
  3, 6, 12 months; 12-month NW t 1.81, non-overlapping 2.03). It is below the E2 bar (t ≥ 3), it was found by
  looking at 4 horizons of 15 signals, and its 1-month spread loads on RMW (0.50) and momentum (0.34), so most of it
  is a known factor. It is a lead for a registered Phase B trial, not a finding.
- **Implementations carried the intended exposures:** momentum S6a loads 1.22 on Mom; EBIT/EV S1b 0.77 on RMW;
  S9 0.57 on HML and 0.63 on CMA. FCF yield ranked within SIC groups (S1a) loads mainly on CMA (0.62) and RMW
  (0.49), barely on HML (0.14), so it was a weak value test.
- **Small caps** (information only, survivor-biased): FCF yield, EBIT/EV, gross profitability, low issuance and
  insider purchase value have 1-month t above 2, as Stage 2 reported; low issuance S5a stays positive at 12 months in mid and
  small caps (t 1.83 and 2.02). These are the effects that survivorship-free prices would be needed to trust.

## 7. Outstanding decisions and blockers

Owner decisions (each changes what counts as evidence):

1. Approve the split (SPLIT_POLICY §6.1).
2. How many confirmation batches the holdout may serve (one recommended) (§6.2).
3. What a holdout pass earns given that the holdout is partly seen: full E3, or E3 plus prospective evidence before
   demo capital (§6.3).
4. Whether inherited trials count in the deflated Sharpe (default: yes) (§6.4).
5. The data-quality exclusion rule and the band-specific cost assumptions (EVALUATION_SPEC §1, §4).
6. Whether the old ETF research loop keeps running.

Blockers that are data, not decisions: survivorship (paid data), share-class and point-in-time ticker history,
point-in-time SIC. They limit small and mid caps far more than large caps.

## 8. Is Phase A complete?

**No.** Done: registry, guard, policy and specification written; diagnostics filled; integrity checks and manifest
in place; tests pass. Not done, by the task's own standard:

- **Data-split integrity is unresolved.** The holdout has been partly seen, and the split, the batch rule and what a
  holdout pass is worth all await the owner.
- **The statistical specification is written but not approved**, and its portfolio half (§4) is not implemented.
- **Data defects** (share-count errors, negative prices) are flagged and excluded by rule, but not fixed at source,
  and the quarterly TTM figures have no second-source check.

## 9. Recommended next action

The owner answers the four split decisions in SPLIT_POLICY §6 (recommended: approve the split, one batch only, a
holdout pass is conditional and needs prospective confirmation before demo capital, inherited trials count). Until
then Phase B exploration can proceed safely, because the guard makes the holdout unreadable and every trial is
registered; nothing can be confirmed.

## 10. Verification review after the owner's decisions (2026-10-14, evening)

The owner decided D1-D6 (`docs/edge/DECISIONS.md`) and asked for the checks below before PR #18 merges.
**No holdout outcome was run or inspected.** The only new computation on returns is §10.3, on data cut at 2022-12,
registered before it ran.

### 10.1 Price rows dated 2026-10-31

**This is a date-label issue: an unfinished month labelled as a month-end. It is not future-dated data, but it
is a defect for anyone who reads the row as a month-end close.**

- **Cause:**
  - The price build (`equity/equity/__main__.py` line 502, `monthly.fetch_prices`) asks Yahoo for monthly bars
    up to the moment it runs.
  - It labels every bar with its calendar month-end (`month_ends(...)[0]`), including the month in progress.
  - The file was written on 2026-10-14 at 16:23 UTC, so its 5,334 rows dated 2026-10-31 hold the price on
    14 October.
- **Who reads it:**
  - **Not exploration:** the data is cut at 2022-12.
  - **Not the holdout:** its last outcome month is 2026-09.
  - **Not the monthly signal log:**
    - it scores only months before today (`latest_complete_month`);
    - it joins an outcome only after that month has ended (`evaluate`);
    - it rebuilds the data before every run.
  - **`xsection.load()` does:** it computes 2026-09's `ret_next` from the row, which is a half-month return. That
    month is prospective, and nothing in the programme uses it.
- **Fix in this PR:**
  - `edge_split.complete_months` drops rows labelled after the fetch date.
  - `edge_integrity` reports them as a WARN.
  - The manifest now records each file's modified time.
- **Not fixed at source,** because the builder feeds the signal log, which must not change. The source fix
  (label only finished months) belongs to the signal log's owner.

### 10.2 Routes by which exploration could read confirmation outcomes

| # | Route | Status before | Now |
|---|---|---|---|
| 1 | **Quality flags on uncut data.** The share-count median used 2023-26 counts, which changes the flag on 626 banded exploration rows. | Present in the draft's integrity report. No exploration result used the exclusion. | **Closed.** `with_quality` computes flags on `cut_exploration` output and refuses an uncut frame. Test: a 2024 issuance cannot change a 2022 flag. |
| 2 | **New code reading the dataset directly** (`xsection.load()`, the CSVs), skipping the guard | Convention only | **Closed for new modules.** A test fails if any module outside a fixed list reads the data files. |
| 3 | **A forward column not named `ret_*`** (e.g. `fwd_ret`) | Not detected | **Closed.** `assert_exploration_only` refuses forward-looking names it cannot check. |
| 4 | **Factor, FX and benchmark series to 2026.** Excess return over VWRP is a holdout number. | Diagnostics cut factors by hand | **Closed.** `edge_split.cut_series`; the Phase B backtester must use it (its test). |
| 5 | **An unregistered look, or a rerun of a registered one** | Append-time checks only | **Closed.** `edge_registry.require` refuses both, and the registry rejects a second result. Diagnostics call it. |
| 6 | **A second confirmation batch** | One run per batch | **Closed (D2).** The gate and the registry both allow one batch, ever. |
| 7 | **Gate approval as free text** | Any non-empty value passed | **Closed.** It must equal the recorded approval, and the gate also needs `backtester_validated`. |
| 8 | **Survivorship conditioned on 2023-26.** No delisted company has a free price, so a company that stopped filing in 2023-26 is absent from 2015-22 exploration too. Of companies with at least $1bn revenue in 2015-22, 318 of 323 that stopped filing between 2023-01 and 2026-03 have no prices. | Known as survivor bias | **Open. It cannot be closed on free data.** The exploration universe is tilted towards companies that survived to 2026 without being acquired or failing. Every result states this. Paid survivorship-free prices would fix it. |
| 9 | **Today's SIC codes and tickers** | Known | **Open (mild).** Stated in results. |
| 10 | **Adjusted prices** | — | **Not a route.** Later dividends rescale all earlier prices by a constant, so returns within exploration are unchanged. `raw_close` undoes later splits; a split on the 29th to 31st misstates that month's raw close (an error, not a leak). |
| 11 | **Knowledge of 2023-26** (people and the model) | Known | **Open.** Handled by D3. |
| 12 | **Rewriting the registry wholesale,** recomputing the hash chain | — | **Open in code.** Git history is the anchor; review registry diffs in each PR. |

### 10.3 Are the quality exclusions applied consistently?

| Research path | Exclusion | Why |
|---|---|---|
| `stage2_diagnostics.py` published tables | No (by design) | They reproduce Stage 2, which had none, and match it exactly |
| `stage2_diagnostics.py --quality` | Yes | Measures the exclusion's effect |
| `edge_integrity.py` | Counts only | Reporting |
| Phase B backtester | Yes, required | Its tests check it |
| Stage 2, signal log | No | Unchanged by decision |

The sensitivity run (15 `QX-*` trials, registered first) is in
`equity/reports/research/edge/stage2_quality_sensitivity.md`. Its results:

- Applying the exclusion drops 55 to 257 large-cap rows per signal over 95 months.
- It changes no large-cap mean IC by more than 0.003 and no t by more than 0.31.
- No signal crosses a threshold.
- Without the exclusion, the run reproduces the published Stage 2 ICs.

The exclusion is implemented as specified and does not alter any Stage 2 conclusion.

### 10.4 Quarterly TTM figures: limitation and validation still needed

**How TTM is built** (`equity/panel.py` `ttm`):

- TTM = latest fiscal year + current year-to-date − prior year's year-to-date of the same length (±10 days), using
  facts public on the month-end.
- If no matching prior year-to-date exists, it falls back to the fiscal-year figure.
- `monthly.py` drops figures whose period ended more than 18 months earlier.

**Measured, large caps 2015-2022:**

- 41,045 of 43,788 company-months have a TTM figure.
- The TTM period ended a median of 3 months before the month-end (mean 2.8).
- 1.8% are more than 6 months old, and 0.5% are more than 12 months old.

**Limitations:**

- The basis (fiscal year only, or fiscal year plus year-to-date) is not stored, so the share of stale fiscal-year
  fallbacks cannot be measured directly.
- The ±10-day matching can fail across fiscal-year changes and some 52/53-week calendars.
- A restated prior-year comparative replaces the original once filed. This is point-in-time correct, but it mixes
  vintages within one TTM.
- 106 rows have mis-dated XBRL periods.
- Nothing has been checked against a second source.

**Validation needed before a TTM-based trial (H1 and others) can reach E2.** All use 2015-2022 values only:

1. **Store the basis.** Store `basis` per row, or compute it in research. Pass: the fiscal-year-only share is
   reported per year, and is below 10% for large caps.
2. **Fiscal-year identity check.** In the month after a 10-K is filed, TTM equals the 10-K's annual figure. Pass:
   100%, apart from listed exceptions.
3. **Jump review.** TTM revenue changes of more than 50% quarter on quarter are flagged, and a sample of 30 is
   reviewed by hand. Pass: each one is classified as real (an acquisition) or an error.
4. **Second-source cross-check.** About 30 large caps, revenue, operating cash flow and diluted EPS, at
   2015-2022 quarter-ends, against an independent source. Pass: within 2% on at least 90% of values.

Checks 1 to 3 need no new data. Check 4 needs a source. SEC's Financial Statement Data Sets are free but come from
the same filings, so they test the arithmetic, not the filing. A truly independent source is probably paid. This
remains open.

### 10.5 Tests

| Suite | Result |
|---|---|
| research | 40 passed (12 before Phase A; 31 in the draft) |
| equity | 117 passed |
| trading | 139 passed |
| **Total** | **296 passed** |

New in this review:

- the gate's one-batch and recorded-approval rules;
- the registry's one-batch, `require` and second-result rules;
- the cut-period quality flags;
- refusal of forward-looking column names;
- `cut_series` and `complete_months`;
- the data-access guard test.

**Unchanged** (checked against `origin/master`):

- `research/signal_log.py`, `research/monthly_signal_log.sh`, `research/stage2.py` and `research/xsection.py`;
- `equity/equity/` and `trading/`.

### 10.6 Is Phase A complete?

**Yes, subject to the owner's review of PR #18.**

- **Data-split integrity:** the split, batch rule, trial count and the value of a holdout pass are decided and
  enforced in code. The holdout's partial exposure is permanent and handled by D3.
- **Statistical specification:** reviewed and recorded.
- **Required diagnostics:** complete.

**Carried into Phase B as gates, not left open in Phase A:**

- backtester validation, including band-specific costs (D5);
- the TTM checks in §10.4, before any TTM-based trial reaches E2;
- survivorship (§10.2 route 8), stated in every result.

### 10.7 Next action

The owner reviews and merges PR #18. Phase B then builds the backtester to `docs/edge/PHASE_B_PLAN.md`.

## 11. Owner's PR #18 review: targeted fixes (2026-10-14, evening)

The owner asked for seven targeted fixes before merge. Each is below with its evidence. Nothing in this section ran
or inspected a holdout outcome on purpose; one accidental exposure is disclosed in §11.8.

### 11.1 Non-positive prices

- **Source:** 344 price rows are ≤ 0; 263 company-months to 2022-12, 4 of them in the large band (NFE, 2022:
  Yahoo's adjusted close for NFE is negative from 2019-01 to 2022-12, an adjustment error).
- **Defect found:** `forward_return` used only the two endpoint prices, so an h-month return could pass through an
  invalid or missing month. 302 one-month returns to 2022-12 touch a price ≤ 0; 4 cross the sign change.
- **Fix:** `forward_return` now compounds the h one-month returns and treats a price ≤ 0 as missing. 0 programme
  returns touch an invalid price; 0 invalid company-months are eligible (`bad_price` sets `quality_ok` False).
  Inputs to the published diagnostics change by 4 large-cap 1-month and 2 large-cap 3-month values; the
  diagnostics were not rerun (a rerun would be a new trial).
- **Integrity report** now separates *source* checks (defects in the files; "prices: positive prices" stays FAIL
  there) from *programme* checks (can the defect still reach a result; all PASS). It exits 1 only on a programme
  FAIL.
- **Unchanged:** Stage 2, `xsection.load` and the signal log keep their behaviour.

### 11.2 Point-in-time share-count exclusion

Registered first as 15 `QX-PIT-*` trials. Results in §1 of `EVALUATION_SPEC.md` and
`equity/reports/research/edge/stage2_pit_sensitivity.md`: 20 rows (6 companies) excluded only by the approved rule,
115 rows (12 companies) only by the point-in-time rule; IC changes ≤ 0.0006, t changes ≤ 0.06. **Recommendation:
keep the approved rule** (its look-ahead touches 20 rows with no measurable effect, while the point-in-time rule
wrongly drops genuine post-merger months); rerun under the point-in-time rule for any E2 candidate. The approved
rule is not changed.

### 11.3 Execution timing

Trading at the decision close is not achievable (the signal needs that close; some filings dated t are accepted
after it). Default: next trading day's close; robustness: next month-end close. Encoded in `edge_rules`
(`execution_time`, `exploration_execution`, `decision_frame`, `assert_executable`) and specified with the
per-rebalance alignment of prices, returns and turnover in `PHASE_B_PLAN.md` §2.1-2.2. The default needs a free
daily first-trading-day price build (Phase B step B1).

### 11.4 Delistings and missing prices

`edge_rules.holding_return`: close at the last valid price, then −30% (default) or −100% (stress); 0% only as a
labelled optimistic bound; a positive value is refused. Ticker changes and acquisitions cannot be told apart on
free data and get the same conservative treatment. **This does not remove survivorship bias:** companies delisted
before 2026 have no prices at all and are never held. `PHASE_B_PLAN.md` §2.4.

### 11.5 Benchmark

Three segments, labelled in every result: actual VWRP from 2019-08 (corrected 2026-10-15 from 2019-09, which was one month late; see PHASE_B_PLAN.md §7.4); VWRL-based 2012-06 to 2019-07; Ken French
developed proxy before 2012-06. Exploration checks: VWRP vs VWRL tracking error 0.37%/yr (40 months); VWRL vs proxy
2.82%/yr, mean difference −0.93%/yr (127 months). FX for these checks came from Yahoo GBPUSD because FRED was
unreachable; `dataset.build()` fails without FRED, to be fixed in B1. `PHASE_B_PLAN.md` §2.5.

### 11.6 Multiple testing and the deflated Sharpe

`edge_registry.deflated_sharpe` now takes a `stat` and pools the Sharpe variance only across results of that
statistic; N is every counted trial (96). Reconciliation, tested against the committed registry: 96 counted trials,
15 with a Sharpe (Stage 2, `xsection_q5_net_vs_universe`), 0 portfolio results; the 75 diagnostics are IC-only and
count in N only. A new kind, `exposure`, records an accidental look without counting it.

### 11.7 Reconciled counts

| Item | Value | Where |
|---|---:|---|
| Registry entries | 101 | `research/edge/trials.jsonl` (hash chain valid) |
| Counted trials (N for the DSR) | 96 | 15 Stage 2 + 6 M8 + 45 diagnostics + 15 QX + 15 QX-PIT |
| Holdout exposures recorded (not counted) | 5 | 4 inherited earlier looks plus `REVIEW-NFE-PRICES-2023` |
| Trials marked as having touched the holdout | 11 | 6 M8 + 5 exposures |
| Holdout (confirmation) runs | 0 | registry |
| Large-cap share-count outliers | 253 of 43,220 | integrity report |

DECISIONS.md, SPLIT_POLICY.md, EVALUATION_SPEC.md and the reports now carry these numbers; earlier counts (66, 81)
are marked as superseded where they remain as history.

### 11.8 Disclosure: an accidental holdout look

While diagnosing NFE's negative prices I printed its adjusted prices for 2023-01 to 2023-03, which are holdout
months. One company, three months, no return or signal computed, and no result depended on it. It is recorded in
the registry as `REVIEW-NFE-PRICES-2023` (kind `exposure`), and the example it produced was removed from code and
reports.

### 11.9 Tests

New `research/tests/test_edge_rules.py`, plus additions to `test_edge.py`: invalid prices cannot enter a return,
an eligible row or a holding; timing (next-day, next-month, weekend month-ends, decision close refused, exploration
boundary); a perturbation test proving decision inputs ignore later data; filing look-ahead refusal; holding
returns at −30%, −100% and an invalid mid-holding price; positive missing returns refused; point-in-time flags;
DSR pooling, floor, equality with `stage2.deflated_sharpe`, and reconciliation with the committed registry.

### 11.10 Reconciliations the owner asked for before merge (2026-10-15)

**(a) "11 entries touched the holdout" versus "0 holdout runs".** These count different things.

- A *holdout run* is the single, pre-registered confirmation batch that the programme will use to test candidates
  on 2023-01 to 2026-09 (registry event `holdout_run`, enforced by `holdout_gate` and D2). **None has happened;
  the one allowed batch is unused.**
- `touched_holdout` marks every earlier look, inside or outside the programme, that saw some holdout-period
  data. They are listed so the holdout is never described as clean:

| Registry id | What was seen | Counted in N? |
|---|---|---|
| M8-T1 | screen-1.0 12-month IC for 2023-2025 cohorts | yes |
| M8-AUDIT-fcf_per_share, -quality, -growth, -valuation, -risk_fit | post-hoc sub-score ICs pooled over 14 cohorts, 3 of them in the holdout | yes (5) |
| STAGE1-HARNESS | equal-weighted large-band return vs the market to 2026-08 | no (exposure) |
| ETF-RESEARCH-E001-E015 | factor and ETF research with out-of-sample periods to 2026-09 | no (exposure) |
| PORTFOLIO-VALIDATION-2026-10-14 | 5-year prices of the 22 demo holdings and VWRP | no (exposure) |
| PROGRAMME-DOC-FACTOR-TABLE | US factor means for 2023-2026 | no (exposure) |
| REVIEW-NFE-PRICES-2023 | one company's prices, 2023-01 to 2023-03 (§11.8) | no (exposure) |

So: 11 looks touched holdout data, 6 of them signal tests that count in the deflated Sharpe; 0 confirmation runs.

**(b) What the NFE look changes.** Very little, and nothing it could bias:

- It showed three monthly prices of one company. NFE is not a candidate, no return, rank, IC or signal was
  computed from them, and they cannot inform which hypotheses are chosen.
- It does not move the holdout from "clean" to "seen": the holdout was already partly seen through the M8 looks,
  the sub-score audit (the origin of H1) and the factor table. D3 already treats a holdout pass as conditional
  E3 for that reason, and requires 12 months of prospective evidence before any demo allocation.
- What it does show is that interactive inspection can leak. From B1 on, every data build is cut at 2022-12 at
  the download itself (no later date is requested), so an interactive look at the exploration files cannot see
  2023.

**(c) Limitations that no Phase B result may imply are solved.** They are in code, not only here:
`edge_rules.STANDING_LIMITATIONS` holds the text, and `edge_rules.require_disclosure(report)` refuses any
backtest report that does not open with it (tested). In short:

1. **Survivorship bias.** Companies that stopped trading before 2026 have no free prices, so they are never held.
   Every backtest is biased upward by an unknown amount. The missing-price stresses (−30%, −100%) apply only to
   companies that *are* in the data and do not remove this bias.
2. **Missing prices are indistinguishable.** Delistings, acquisitions and ticker changes look the same and get the
   same conservative mark-down; acquisitions are therefore penalised and failures possibly under-penalised.
3. **The holdout is partly seen** (above), so a holdout pass is weaker than a clean out-of-sample test (D3).
4. **One ticker per company, today's SIC codes, and an unofficial free price source** (Yahoo).
5. **Benchmark segments:** actual VWRP only from 2019-08 (corrected from 2019-09 on 2026-10-15); VWRL before that.

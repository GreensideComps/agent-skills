# Edge-discovery programme, Phase A: audit, data-split check and gap analysis

Written 2026-10-14 on branch `claude/edge-discovery-phase-a-j78pyp`, from `master` at `e8ec0e2` (PR #17 merged).
Evidence is cited as files, commits or command output from this session. Where something is inferred rather than
checked, it says so.

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
| Exploration/confirmation/prospective policy | P | B | single-use rule in STRATEGY_V2 only | `docs/edge/SPLIT_POLICY.md` | owner approval recorded (§6 of the policy) |
| Holdout guard in code | P (Stage 2 only) | V for exploration; confirmation locked | `stage2.run` cut only | `edge_split.exploration_view`, `assert_exploration_only`, `holdout_gate` | split tests: a 7x change to every 2023+ price changes nothing in the view |
| Holdout cleanliness | — | **B** | §3 | owner decision on what a holdout pass earns; no technical fix exists | decision recorded |

### 4.2 Statistics

| Component | Before | After | Evidence | Minimum fix | Test of completion |
|---|---|---|---|---|---|
| IC + Newey-West t (1 month) | V | V | planted-signal test | none | existing tests |
| Overlapping horizons (3, 6, 12 months) | M | V | 1-month only | NW lags max(3, h) + non-overlapping t | `test_nw_se_...`, `test_diagnostics_find_a_planted_signal_at_every_horizon` |
| Power / minimum detectable effect | M | V | not reported | MDE and power in `ic_stats` | `test_ic_stats_mde_and_power`; diagnostics report |
| Factor-adjusted alpha | U | V | no test | planted-alpha test | `test_stage2_factor_alpha_recovers_planted_alpha_and_betas` |
| Deflated Sharpe | U | V | monotonicity test only | hand-computed check | `test_stage2_deflated_sharpe_matches_a_hand_computation` |
| Trial count spanning all looks | P | V | Stage 2 counted its own 15 only | `edge_registry.n_trials` (66) | registry tests |
| Written statistical specification | P | V | scattered across prereg docs | `docs/edge/EVALUATION_SPEC.md` §3, §5 | reviewed by owner |

### 4.3 Data

| Component | Before | After | Evidence | Minimum fix | Test of completion |
|---|---|---|---|---|---|
| Point-in-time filing dates | V | V | 0 rows with a later filing | none | `edge_integrity` check |
| Quarterly fundamentals | U | U | built; no second-source check of quarterly TTM | cross-check TTM revenue, OCF and EPS for ~30 companies against a second source | agreement within 2% on ≥ 90% of values |
| **Share-count scaling errors** | unknown | P (flagged, not fixed) | 283 of 43,220 large-cap company-months (53 companies) with shares > 10x or < 1/10 of the company's median, e.g. 1.9e14 shares; puts small companies in the large band | programme excludes flagged rows (`quality_flags`); a fix in `equity/monthly.py` would change the signal log's inputs, so it needs its owner thread | flag count 0 after a fix, or exclusion applied in every programme test |
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
| Tests | V locally | V (268 + 19 new) | no CI | optional CI workflow (owner: adds a GitHub Action) | — |
| Signal-log routine monitored for missed runs | M | M | absent from `schedule.json` | add an expectation (owner thread of the signal log) | `python -m equity reliability` flags a missed 3rd |
| Stale ETF research loop | — | flagged | enabled on an old branch and brief | owner: keep, re-brief or pause | — |
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

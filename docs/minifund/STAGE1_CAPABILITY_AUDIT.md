# Mini fund Stage 1: repository capability and dependency audit

Date: 2026-10-23. Requested by the owner (roadmap message `cmsg_01U4KMvkBYNknqm4HRVie8uvJhN52zcHwKcac12ofKnTgS`,
09:47Z). Audited at master `b8cccb4` plus the open draft PRs #27 (pm-1.0) and #29 (G2). **Analysis and docs only:**
no code, config, registry, scheduled task, gate or account was changed. Stage 0 (PR #29 / G2) is not touched.

Evidence labels: **[V]** checked directly for this audit · **[T]** a test on master asserts it · **[R]** taken from an
earlier report on master or in the project files, not re-run · **[A]** inference.

Baseline re-run for this audit [V]: offline, credentials stripped, Python 3.13.16 with `office/requirements-worker.txt`
(pytest 9.1.1, statsmodels 0.15.0): trading **139**, equity **118**, research **460**, office **44** passed.

Classes: **W** working (implemented and exercised) · **P** partial · **M** missing · **U** unverified (code exists, never
shown working in operation, or the claim rests on an untested assumption).

---

## 1. Capability matrix against the target architecture

### 1.1 Data ingestion and event history

| Component | Class | Evidence |
|---|---|---|
| Market prices (daily, US + LSE ETFs, FX) | P | `equity/equity/prices.py`, `research/data_sources.py`: Yahoo chart API, unofficial, price-only closes plus `adjclose` [V]. Survivorship-biased: delisted names have no price (B4, D13) [R]. B1 daily exec prices to 2022 in `research-data/edge/exec_prices_to_2022.csv.gz` [R]. |
| Fundamentals (US filers) | W | `equity/equity/sec.py`, `fundamentals.py`: SEC companyfacts, keeps `original` (first filed) and `latest` per period with accession and filed date [V]. 118 equity tests [V]. Panel `sec_facts_panel.csv.gz` (123 MB) [R]. |
| Fundamentals (non-US, IFRS) | P | IFRS filers that file with the SEC only (M2) [R]. No non-US-listed coverage, so VWRP's ~40% non-US weight is outside the research universe [A]. |
| Filings as events (8-K, timestamps) | M | `sec.py:95` can fetch `submissions` JSON but nothing stores filing events. The JSON carries `acceptanceDateTime` to the second [V: live read of CIK 320193, 23 Oct] and 8-K item codes; unused. |
| Insider transactions | W | `equity/equity/insiders.py`, SEC Form 345 data sets; used by S7a/b [V]. Filed **date** only, not time. |
| News | M | No news source, store or parser anywhere in the repo [V: grep of every URL in `*.py`]. |
| Macro data | P | `research/data_sources.py` lists FRED (UK 3m rate, GBPUSD) and Ken French factors [V]. FRED was unreachable from the container on 14 Oct [R]; ALFRED's home page answered 200 on 23 Oct [V], data endpoint untested. No vintage (as-first-published) macro series anywhere [V]. |
| Portfolio records (demo account) | W | `trading/t212bot/readonly.py` `ReadOnlyClient` [T]; office `h_demo_snapshot` runs it in a child process [T]; weekday brief 23 Oct £1,193.28 [R]. |
| Append-only event history | W | Office: hash-chained git event log with compare-and-swap push (`office/office/store.py`, 44 tests) [T], live on `claude/office-state` since 20 Oct [R]. Equity: append-only JSONL ledgers in `equity/data/` [V]. Edge registry: hash-chained `research/edge/trials.jsonl` [T]. Three separate histories, no shared schema. |

### 1.2 Point-in-time data and feature store

| Component | Class | Evidence |
|---|---|---|
| Timestamps / availability | P | Fundamentals carry filed **date**; B5 uses only filings known at each decision date [R]. No intraday availability time for anything, which a 1-day news horizon needs [A]. |
| Source provenance | P | Accession numbers on facts [V]; manifests with sha256 for B5 inputs (`docs/edge/B5_RUN_MANIFEST_3.json`) [V]. Price rows carry no download timestamp or vendor version [A: not seen in `prices.py`]. Library versions not recorded with research runs (T17) [R]. |
| Revisions | P | `original` vs `latest` per fact [V]. Price revisions (Yahoo re-adjustments) are not tracked [A]. |
| Data quality | P | Input audit, share-PIT audit, negative-price guard, quality flags (`research/edge_integrity.py`, `edge_b5_input_audit.py`) [R]. Check 4 open: 26–31% of eligible rows unscored [R: PR #23]. |
| Historical universe | P | Monthly SEC-filer universe including stopped filers, but stopped filers mostly unpriced [R: Stage 1 coverage]. |
| Corporate actions | P | Splits applied to per-share facts (`fundamentals.py:352`) [V]; prices rely on Yahoo `adjclose`; 2021 10-for-1 splits mishandled for CoStar and The Trade Desk by both quality rules [R: b5_trials.md]. No dividend ledger. |
| Feature store | M | Features are recomputed inside each study script (`stage2.py`, `edge_b5_inputs.py`); no shared, versioned feature table [V]. |
| Reproducible datasets | P | Research data in `/mnt/project-files/research-data/` with a manifest for `edge/` [V]. Rebuild command exists (`python -m equity research-data`) [R]; a rebuild today would pull revised Yahoo data, so it is not byte-reproducible [A]. |

### 1.3 AI research engine

| Component | Class | Evidence |
|---|---|---|
| News interpretation, event extraction, novelty | M | Nothing in the repo [V]. |
| Company analysis | P | `equity/equity/valuation.py`, bear-case records, `screener.py` (screen-1.0) [V]. Screen-1.0 itself is unvalidated: M8-T1 has no verdict in the registry and touched the holdout [V: registry]; `equity/config/evidence.json` records it as E1 with a failed pre-registered backtest (IC t = 1.92 vs 2.0), and every screen and paper report prints an "unvalidated" banner [V; corrected 23 Oct, see §4]. |
| Catalyst identification, source verification | M | [V] |
| Research planner (draft only) | U | `office/office/planner.py` on draft PR #27, not merged [V]. Owner allowed it (D-T15) [R]. |
| Weekly stock discovery routine | P | Scheduled task exists [R]; its output is not wired into any gated process [A]. |

### 1.4 Quantitative signal engine

| Component | Class | Evidence |
|---|---|---|
| Momentum, value, quality, issuance, insider, accruals, expectations gap | W (as research code) | `research/stage2.py` TRIALS S1a–S9 [V]; all 15 failed or inconclusive in large caps 2015–2022 [V: registry]. |
| Earnings revisions (S8) | M | Needs paid consensus data; `NOT_RUN` in `stage2.py:248` [V]. |
| Earnings surprise (S4 SUE) | W (failed) | S4 fail, IC 0.008 [V: stage2_signals.md]. |
| Volatility signals | P | Old ETF studies (`research/h09_vol_managed_leverage.py`, E006/E015, rejected) [V]; no cross-sectional low-vol signal [V]. |
| Validated event signals | M | None exists [V]. |
| Monthly prospective signal log | U | `research/signal_log.py` + task, first run 3 Nov 2026 [R]. Not yet run in operation. |

### 1.5 Research validation and strategy registry

| Component | Class | Evidence |
|---|---|---|
| Pre-registration and registry | W | `research/edge_registry.py`, hash-chained, 147 register + 105 result events [V]; manifest gate in `edge_b5_run.py` [T]. |
| Baselines | P | VWRP benchmark in B5 (VWRL before 2019-08) [R]; no standard baseline ladder (no-trade, simple momentum, category rule) as the roadmap's §3 asks [V]. |
| Walk-forward testing | M | Single fixed exploration window 2015–2022 [V]; no rolling re-fit harness [V]. |
| Holdouts | P | Split policy and one-confirmation-batch rule enforced in `edge_split.py` [T]; the 2023–26 holdout is PARTLY SEEN [R: DECISIONS.md]. A clean holdout exists only going forward (prospective). |
| Costs | W | 0.30% one-way, next-day close, B2 synthetic validation [T]. Costs are a flat assumption, not measured from T212 spreads/FX [A]. |
| Multiple testing | W | DSR with N = 102 [T]. Gap: the 15 ETF experiments E001–E015 are registered as holdout **exposure** only (`counts_for_dsr: false`) [V], so they are not in N. |
| Experiment tracking | P | Two registries: edge `trials.jsonl` and the legacy `research/experiments/E*.json` (read by the bot report) [V]. |
| Verdict stored with the result | P | B5 V3 result events hold `sr_monthly` but **no `verdict` field**; the fail verdict lives only in `b5_trials.md` [V]. Anything reading the registry (pm-1.0 eligibility, the planner) cannot see "fail", only "not pass". Safe direction, but a gap. |

### 1.6 Core portfolio

| Component | Class | Evidence |
|---|---|---|
| 100% VWRP default proposal | U | `pm.py` on draft PR #27 returns 100% VWRP with every limit shown [V: code read]; not merged, not run in operation. |
| VWRP total-return tracking | P | VWRP prices via Yahoo in B5 and paper-1.1 (PR #27) [V]. No dividend/OCF ledger; VWRP is accumulating so price ≈ TR net of OCF [A]. |
| Contributions, drift, concentration monitoring | M | No contribution ledger, no drift report [V]. VWRP sector look-through entered from Vanguard 31 Aug 2026 (PR #27) [R]; company look-through UNVERIFIED [R]. |
| Tax/turnover awareness | M | ISA context recorded in memory only; no code [V]. |

### 1.7 Tactical portfolio

| Component | Class | Evidence |
|---|---|---|
| Eligible-strategy gate | U | `pm.eligible()` requires an owner `cmsg_` id and exactly one `pass` result per cited trial (PR #27) [V]. `office/config/pm_eligible.json` is empty [V]. |
| Strategy sleeves with attribution | M | pm-1.0 aggregates all strategies into one satellite set; no per-strategy ledger or attribution [V]. |
| Safe state when nothing passes | U | pm-1.0 verdict `default` = 100% VWRP [V: code], not exercised in operation. |
| Three-way comparison (VWRP / VWRP+tactical / tactical alone) | M | Equity paper book (screen-1.0, USD, price-only) vs SPY, plus VWRP on PR #27 [V]. No combined-portfolio book [V]. |

### 1.8 Independent portfolio risk controller

| Component | Class | Evidence |
|---|---|---|
| Exposure cap 20% outside core | U | `pm.check()` `outside_core` on summed direct weights [V]. |
| Concentration ≤5% per company | P | Direct weights enforced; look-through to VWRP holdings computed but `enforced: False` and UNVERIFIED [V]. |
| Sector ±10 pt active vs VWRP | U | Enforced with look-through, fails closed when data is missing or stale [V]. |
| Correlated positions, factor, currency exposure | M | No covariance or factor model in the controller [V]. Roadmap requires the cap to cover correlated positions. |
| Liquidity | M | [V] |
| Costs / turnover limits | M | [V] |
| Drawdown control | P | −15% relative review threshold opens a review only, no weight change (owner rule) [V]. |
| Stop conditions (research, performance, data, operational, usage, portfolio) | P | Operational: office pause event, stop file, kill file [T]. Research stop: one-run lock, spent authorisations [T]. Data stop: pm fails closed on stale look-through [V]; paper book has `max_price_age_days` [V]. Usage stop: none in code; G1/G2 records only [R]. Performance and portfolio stops: review-only / proposal-reject only. |
| Independence from the AI and the proposer | P | pm-1.0 is deterministic and imports no broker [V], but limits are checked **inside** `propose()`; no second, separate check guards any execution path, because none exists yet [V]. |

### 1.9 Paper execution, reconciliation and audit

| Component | Class | Evidence |
|---|---|---|
| Order state machine (intent, unknown outcome, recovery, pause) | U | `office/office/orders.py` + `test_orders.py` [T]; no adapter, no simulated broker in operation [V]. |
| Simulated fills | P | Equity paper book fills at decision price plus spread and FX (`paper.py`) [V]; office has none. |
| Cash and holdings reconciliation | P | Equity paper book replays trades into cash/positions [V]; bot executor reconciles demo positions [R]; no reconciliation between a decision record and a paper book [V]. |
| Daily reports | W | Weekday brief, equity health/portfolio/paper reports daily [V: `equity/reports/*/2026-10-23.md`]. |
| Immutable decision evidence | P | pm proposal records hashes of inputs [V], but proposals are not logged (owner: no proposal logging during G1) [R]. |
| Demo order path | M (by design) | Demo pies show 0 tradeable via API [R]; O8/O9 unapproved [R]. |

### 1.10 Operations: scheduler, queue, heartbeat, recovery, audit history

| Component | Class | Evidence |
|---|---|---|
| Durable queue, leases, fencing | W | `queue.py` [T]; live on `claude/office-state` [R]. |
| Scheduler / heartbeat | P | Heartbeat `trig_01WJoDNXpsh4WBpXARz5oB7X` every 3 h [R]. **G1 FAILED** 21 Oct (gap 6h01m vs 6.00h) [R]. Two safety-filter refusals of the worker command on the 06:57 slot (21 and 23 Oct) [R]. Weekly usage limit stopped all runs 21 Oct 12:58Z – 23 Oct 04:01Z [R]. |
| Recovery / crash drill | U | `worker --drill-crash` exists [R]; drill not run (paused with G1) [R]. |
| Alerts | P | Digest files and thread; email off; `health.py` holds a stale test alert 36 h after a pass (fix on PR #29) [R]. |
| CI | M | No `.github/` [V]; office `test_suites` task is the substitute [R]. |
| Equity daily pipeline | P | Missed 21 and 22 Oct, catch-up 23 Oct 04:36Z exited rc=1 [V: commit `b8cccb4`, `equity/reports/health/2026-10-23.md` lists both misses]. |

**Summary count (65 rows):** working 11 · partial 28 · missing 17 · unverified 9. Rows marked "W (as research
code)" or "W (failed)" count as W; "M (by design)" counts as M.

---

## 2. Dependency map

```
                       ┌──────────────── external, free ────────────────┐
                       │ Yahoo chart API (unofficial)   SEC EDGAR (companyfacts, submissions, Form 345)
                       │ Ken French library             FRED (reachability uncertain)   T212 DEMO API
                       └──────┬───────────────┬──────────────┬─────────────────┬────────┘
                              │               │              │                 │
  equity/equity  (stdlib only: sec, prices, fundamentals, universe, screener, valuation, paper, reliability)
      │  writes equity/data/*.jsonl (in git)          │ builds research-data/*.csv.gz (project files)
      │                                               ▼
      │                           research/ (pandas, numpy, scipy; statsmodels for one test)
      │                             stage2.py, xsection.py, edge_split.py, edge_rules.py, edge_backtest.py,
      │                             edge_b5*.py ──imports── equity (b2/b3/b5 scripts) ── reads /mnt/project-files
      │                             edge_registry.py → research/edge/trials.jsonl, status.json
      │                                               │
      │                                               ▼  (read-only, by file)
      │                           office/office (stdlib only)
      │                             store/queue/worker/director/health/gate  → git branch claude/office-state
      │                             handlers: test_suites (subprocess pytest), demo_snapshot (subprocess → trading)
      │                             [PR #27] pm.py, sectors.py, planner.py → reads trials.jsonl, office/config/*.json
      ▼
  trading/t212bot (requests-free stdlib client; Resend email)
      client/readonly/executor/monitor/report/intel; strategy retired (PR #20 draft hardens this)
      research_feed.py reads research/experiments/E*.json (legacy registry)

  Scheduled tasks (claude.ai triggers): heartbeat 3 h, digest 06:52, weekday brief 06:45 (clones old bot branch),
  equity pipeline 22:27 London, monthly signal log (3rd), weekly discovery.  No CI.
```

Key couplings and risks:
- **Python deps are undeclared except for tests.** `office/requirements-worker.txt` pins pytest and statsmodels only;
  research relies on the base image's pandas/numpy/scipy (versions unrecorded, T17) [V].
- **Research reads absolute paths** (`/mnt/project-files/research-data`, `edge_b5_manifest.py:13`,
  `edge_exec_prices.py:50`) [V]: research cannot run outside this project's container.
- **Office → trading** only through a child process with the kill file set and credentials stripped [T]. Good
  isolation; keep it for any paper broker.
- **Office → research** only by reading `trials.jsonl` (pm, planner) [V]. Registry schema changes must keep pm-1.0's
  reader working.
- **Three ledgers, three schemas** (office events, equity JSONL, edge registry). Consolidated exposure needs a single
  reader, not a merge.

---

## 3. Data-source inventory (no purchases; prices as published or reported, not quotes)

| Source | Data | History | Point-in-time quality | Cost | Licensing / limits | Status here |
|---|---|---|---|---|---|---|
| SEC companyfacts | XBRL fundamentals | 2009+ | Good: each value with accession and filed date | Free | Public domain; SEC fair-access ≤10 req/s, declared User-Agent | In use [V] |
| SEC submissions + EDGAR full index | Every filing, form type, 8-K item codes, `acceptanceDateTime` | 1994+ (index), JSON recent + paged history | Very good: second-level acceptance time | Free | As above | **Reachable, unused** [V] |
| SEC full-text search (efts) | Text search of filings | 2001+ | Good | Free | As above, undocumented API | Reachable [V] |
| SEC Form 345 data sets | Insider trades | 2003+ | Filed date | Free | Public | In use [V] |
| Yahoo chart API | Daily prices, adjclose, FX, ETFs | Decades | Poor: survivorship-biased, silent re-adjustment, no vendor PIT | Free | Unofficial; Yahoo terms restrict use; can break without notice | In use [V] |
| Ken French library | Factor returns | 1926+ | Revised over time | Free | Academic, attribution | In use, to 2022 files [V] |
| FRED / ALFRED | Macro series; ALFRED keeps vintages | Decades | ALFRED gives as-published values | Free | Free with attribution; some series third-party licensed | FRED unreachable 14 Oct [R]; ALFRED page 200 on 23 Oct [V], API untested |
| GDELT 2.0 | Global news metadata, events, tone, 15-min updates | Feb 2015+ (v1 events from 1979) | Good timestamps; article text not included | Free | Open use per secondary sources; official terms not confirmed | API answered 429 (rate limit) on 23 Oct, so reachable [V] |
| Vanguard VWRP factsheet / holdings | Sector and holdings look-through | Current | As-of dated | Free | Vanguard terms | Sector page 31 Aug 2026 entered on PR #27; holdings not yet [R] |
| T212 demo API | Account, positions, instruments | Live | Live | Free | Demo only | In use, read-only [V] |
| Norgate US (Platinum) | Survivorship-free US prices incl. delisted | 1990+ | Good | ~$630/yr [R: 14 Oct quote] | Personal use | Not bought (owner) |
| EODHD | Prices all-world; All-In-One adds news and fundamentals | Varies; news depth undocumented | Unclear for delisted | €19.99/mo; All-In-One €99.99/mo [reported, G2 Feb 2026, unverified] | Personal vs commercial tiers | Not bought |
| Polygon (Massive) news | Ticker-tagged news | ~2016+ [reported] | Publication timestamps | from ~$29/mo [reported] | Paid plans for history | Not evaluated in depth |
| Tiingo news | Ticker-tagged news | ~2014+ [reported; another source says 3 months] | Timestamps | $30–50/mo [reported] | Internal use tiers | Conflicting reports |
| Finnhub | News, sentiment, estimates | Unknown depth | Unknown | from ~$50/mo [reported] | Licensing clarity rated low by a third party | Not evaluated |
| Sharadar (Nasdaq Data Link) | Survivorship-free US fundamentals and prices | 1990s+ | Marketed as PIT [A] | Current price not found | Personal vs commercial | Not evaluated |
| Consensus estimates (for S8 revisions) | Analyst revisions | — | — | Paid only (I/B/E/S, Zacks, etc.) | Restrictive | Not available |

Findings:
1. **The best free event source is already reachable and unused:** SEC 8-K filings with second-level acceptance times
   and item codes (2.02 results, 7.01/8.01 disclosures, 1.01 agreements, 5.02 officer changes). They are primary
   sources, so syndication and novelty problems are smaller than in news feeds. This is the natural first data set for
   Stage 4 baselines 2–3 (market-adjusted event rule, category rule).
2. **No free source gives licensed, timestamped news *text* with deep history.** GDELT gives metadata and tone from
   2015, not article bodies. Any AI-extracted novelty score over 2015–2022 therefore needs either 8-K text (free) or a
   paid feed. A paid feed is an owner decision under O7 and needs a costed case.
3. **Survivorship-free prices remain the binding data gap** for any cross-sectional work (D13). Stage 2's exit
   criterion "no survivorship bias" cannot be met on free data [A, from B4].
4. **Vendor prices and archive depths above are from secondary sources** and must be confirmed on each vendor's own page
   before any costed case.

---

## 4. Status of prior trials ("the 102")

N = 102 is the DSR count, not 102 strategies [V: registry]. Of 147 registered ids, 102 have `counts_for_dsr: true`:

| Group | Count (in N) | What it is | Result | Still valid? | Rerun? |
|---|---|---|---|---|---|
| S2-S1a … S2-S9 | 15 | Pre-registered Stage 2 signals, large caps 2015-01..2022-11, monthly IC | 13 fail, 2 inconclusive (S2a, S3b) [V] | Valid as exploratory negatives on survivorship-biased data; underpowered (95 months) [R] | Only as **new** registered trials (raises N), ideally on survivorship-free data. Do not re-tune S2a/S3b on the same window. |
| B5-H1-FCFPS-ACCEL-V3, B5-S2A-GP-12M-V3 | 2 | B5 strategies under the validated backtester, vs VWRP, after costs | Both fail P1–P3 (H1 t_nw 1.66, DSR 0.15; S2a t_nw 2.10, DSR 0.27) [R: b5_trials.md] | Valid. Strongest evidence in the repo | **No (research stop).** Archive. |
| B5 V1/V2 definitions | 4 | Superseded definitions, never run | none | Counted, never evaluated | No |
| DIAG-* | 45 | Stage 2 horizon diagnostics (3/6/12 months) | no verdict (diagnostic) | Valid as information | No |
| QX-* | 30 | Stage 2 quality-exclusion sensitivity | no verdict | Valid as information | No |
| M8-T1 + 5 sub-score audits | 6 | screen-1.0 score vs 12-month return, 2012–2025 cohorts | no verdict in the registry; touched holdout [V]. `evidence.json`: pre-registered backtest failed, tier E1 [V] | Weak (post hoc, holdout exposure) | Screen-1.0 is **unvalidated** and already bannered as such in every report [V]; it still drives the equity paper book. D-C tightens the wording (`proposals/DC_evidence_labels.patch`). |

Not in N but relevant:
- **ETF research E001–E015** (trend, momentum sleeves, leveraged ETPs, intraday): 9 rejected, 2 insurance-only, 1
  "momentum supported" (E003), 2 promoted (E004 factor ETFs, E009 LQQ3, now retired) [V]. Recorded as holdout exposure
  only. If any momentum or factor-ETF idea returns in Stage 3, these 15 looks should be added to its trial count.
- **Robustness variants** (B5 ROB-*, 10) and hand-check: diagnostic, not counted [V].

Reusable signal code without duplication: `research/stage2.py` signal constructors (S1–S9),
`research/edge_b5_inputs.py` (TTM inputs with PIT rules), `research/edge_backtest.py` + `edge_rules.py` (monthly
portfolio engine, validated for exploration only), `research/xsection.py` (IC harness), `research/signal_log.py`
(prospective log). Stage 3 baselines should call these rather than re-implementing momentum or quality.

---

## 5. Can the pm and paper interfaces support two sleeves with shared risk controls?

**Short answer: partly. The pm-1.0 interface on draft PR #27 already models a core plus one aggregated tactical
sleeve with shared limit checks at proposal time. It cannot yet attribute performance per strategy, enforce exposure
on correlated positions, or re-check limits independently before a paper order, and no paper book holds the combined
portfolio.**

What already fits [V: `office/office/pm.py` at `ba825f2`]:
- Core = remainder, VWRP; satellites from several strategies are added up **per company** (`holdings()`), so overlap
  between strategies is counted once against the 5% and 20% limits.
- Sector check uses look-through `core × VWRP sector + satellites`, i.e. total exposure, not the sum of sleeve caps.
- Fails closed: unverified or stale look-through cannot pass; a breaching candidate is rejected whole, never scaled.
- Pure function, no broker import: a model cannot call around it today because there is nothing to call.

What is missing:
1. **Sleeve identity in the book.** `propose()` returns target weights only; there is no ledger keyed by sleeve and
   strategy, so "tactical alone" and per-strategy attribution cannot be computed.
2. **Overlap with the core.** Company look-through with VWRP is reported but `enforced: False`; VWRP company holdings
   are unverified. A 5% Apple satellite plus VWRP's ~4–5% Apple exposure is not blocked [A on the Apple weight].
3. **Correlation / factor exposure.** The 20% cap counts weights, not risk. No covariance, beta or factor check.
4. **Currency.** VWRP is GBP; US satellites add USD exposure; nothing measures it.
5. **Independent risk gate.** Limits live inside the proposer. The roadmap needs a separate controller that every
   simulated order passes through, that a proposer cannot skip, and whose rejection cannot be overridden.
6. **Paper book of record.** The equity paper book is a single screen-1.0 book in USD, price-only, benchmarked to SPY
   (+VWRP on PR #27). The office `orders.py` state machine has no simulated broker. Nothing holds VWRP + tactical in
   GBP with cash.
7. **Liquidity, turnover and cost limits**: none.

The changes in §7 add these as small, separate modules on top of pm-1.0 rather than rewriting it.

---

## 6. Outstanding reliability and execution items

Reliability (Stage 0, owned by the "Always-on research office plan" thread; listed, not acted on here):
- R1. G1 closed FAILED; G2 on draft PR #29 (patch `8f38044`) awaits owner review and authorisation [R].
- R2. Usage stop: the weekly usage limit removed 39 h of runs (21–23 Oct) [R]. No usage-ceiling stop in code.
- R3. Safety-filter refusals of the worker command, twice on the 06:57 slot [R]. Cause outside the repo.
- R4. Crash drill not run [R].
- R5. Stale test alert held 36 h (fix on PR #29) [R].
- R6. No CI [V].
- R7. Equity pipeline missed 21–22 Oct; 23 Oct catch-up rc=1 [V]. It runs outside the office queue, so the office
  health report does not see it [A].
- R8. Weekday brief clones the old bot branch (PR #24 has the replacement; recreate is an owner decision) [R].
- R9. Owner alert email untested for the office (T12, owner approval needed) [R].
- R10. Research dependency versions unrecorded (T17) [R].

Execution (Stage 5):
- X1. No simulated broker for `orders.py`; no paper cash/holdings reconciliation against decisions [V].
- X2. No independent risk gate before a paper order (§5.5) [V].
- X3. No consolidated exposure view across core, tactical and the demo account [V].
- X4. Costs are a flat 0.30% one-way assumption; T212 FX fee and spreads unmeasured [A].
- X5. Demo pies are not tradeable through the API; any demo execution needs O8/O9 approval [R].
- X6. Stop conditions: performance and portfolio stops are review-only; usage and data stops are not unified [V].
- X7. pm proposals are not logged (deliberately, during G1) [R]; Stage 5 needs immutable decision records.

---

## 7. File-by-file plan: small, independently testable changes

Ordering respects Stage 0: nothing below touches `office/office/{gate,health,worker,director}.py`,
`office/WORKER*.md`, scheduled tasks or the state branch. Items marked **after #27** build on pm-1.0 and should wait
for the owner's PR #27 decision. Each item is one PR with offline tests; none places an order or adds a cost.

### Stage 1 close-out (docs and metadata, can start now)
| # | File(s) | Change | Test / exit check |
|---|---|---|---|
| 1.1 | `docs/minifund/STAGE1_CAPABILITY_AUDIT.md` | This document | Owner review |
| 1.2 | `docs/minifund/INTERFACES.md` (new) | Define record schemas: `DataRecord` (source, retrieved_at, available_at, revision), `EventRecord` (roadmap §3 fields), `SleeveTarget`, `RiskVerdict`, `PaperFill`. Docs only | Review; schemas then used by 2.x/5.x tests |
| 1.3 | `research/edge_verdicts.py` (new), `research/edge/verdict_annotations.jsonl` (new) | D-A approved in principle 23 Oct. Separate append-only, hash-chained verdict ledger, so the pinned registry stays byte-identical. Exact events and patch in `proposals/` for review | 11 research tests + 2 pm tests, run in scratch copies (`proposals/README.md`) |

### Stage 2: trustworthy historical data
| # | File(s) | Change | Test |
|---|---|---|---|
| 2.1 | `equity/equity/filings.py` (new), `equity/tests/test_filings.py` | Store SEC submissions as append-only filing events: CIK, accession, form, 8-K items, `acceptanceDateTime`, retrieved_at. Free, already reachable | Fixture JSON → events; idempotent re-ingest; no network in tests |
| 2.2 | `equity/equity/prices.py` | Add `retrieved_at` and a content hash to each price row; flag silent re-adjustments on refresh | Fixture: changed adjclose produces a revision event, not an overwrite |
| 2.3 | `research/provenance.py` (new) | Record python and library versions plus input hashes with every research output (T17) | Unit test on a dummy run |
| 2.4 | `research/data_sources.py` | ALFRED vintage fetch for a short macro list (e.g. US CPI, payrolls, UK Bank Rate), cached | Offline fixture; as-of lookup returns first-published value |
| 2.5 | `docs/minifund/DATA_PURCHASE_CASE.md` (new) | Costed comparison (Norgate, EODHD, Sharadar, a news vendor) from vendors' own pages. **Decision for the owner; nothing bought** | Review |

### Stage 3: baselines and experiment registry
| # | File(s) | Change | Test |
|---|---|---|---|
| 3.1 | `research/baselines.py` (new) | Baseline ladder over the existing engine: VWRP hold, no-trade, 12-1 momentum and quality using `stage2.py` constructors (no new definitions) | Synthetic-world tests: hold == benchmark; turnover 0 for no-trade |
| 3.2 | `research/walkforward.py` (new) | Rolling-origin evaluation wrapper over `edge_backtest.run`, exploration window only (refuses holdout via `edge_split`) | Refuses dates past 2022-12; synthetic leak test |
| 3.3 | `research/edge_registry.py` | Registration requires `baseline_ids`, `experiment_count`, `data_requirements`, `rejection_criteria` for new trials (roadmap §6) | Missing field refused; old events still verify |
| 3.4 | `research/edge/prior_etf_families.json` (new) | D-B approved 23 Oct: the family rule in `MULTIPLE_TESTING_PRIOR_ETF.md` adds related E configurations to N at registration only | Counts match `research/experiments/E*.json`; DSR test with the extra N |

### Stage 4: news intelligence (SEC 8-K first)
| # | File(s) | Change | Test |
|---|---|---|---|
| 4.1 | `research/events.py` (new) | Event study harness: market-adjusted returns at +1, +5, +20 trading days from `available_at`, using B1 exec prices | Synthetic events with known drift recovered; event before availability refused |
| 4.2 | `research/event_dedup.py` (new) | Novelty: collapse repeated filings/stories per company per window | Duplicate fixtures counted once |
| 4.3 | `docs/edge/prereg/EVENT_BASELINES.md` (new) | Pre-register baselines 1–3 on 8-K item categories before any outcome is computed | Registry entries before results |
| 4.4 | later | AI extraction (candidates 4–5) only after 4.1–4.3 report, with the model and prompt hashed into the trial | — |

### Stage 5: portfolio manager and paper execution (after #27)
| # | File(s) | Change | Test |
|---|---|---|---|
| 5.1 | `office/office/risk.py` (new) | Independent controller: pure `assess(book, intent) -> RiskVerdict`. Re-implements the pm-1.0 limits from config, adds core-overlap enforcement, currency, liquidity (ADV), turnover and cost caps. Imports nothing from `pm.py` | Same cases as `test_pm.py` plus overlap and liquidity; a mutated proposer cannot pass a breach |
| 5.2 | `office/office/pm.py` | Return `SleeveTarget`s tagged by sleeve (`core`, `tactical`) and strategy id; keep pm-1.0 output unchanged as a view | Existing `test_pm.py` unchanged and passing |
| 5.3 | `office/office/paper_broker.py` (new) | Simulated broker implementing `orders.Broker`, fills from recorded prices with T212-style spread and FX; GBP base | `test_orders.py` scenarios against it |
| 5.4 | `office/office/paper_book.py` (new) | Book of record keyed by sleeve; cash, holdings, reconciliation after each fill; every intent passes `risk.assess` first | Reconciliation mismatch pauses; duplicate decision key refused |
| 5.5 | `office/office/attribution.py` (new) | The three comparison series (VWRP-only, VWRP+tactical, tactical alone) from the book | Hand-computed fixture |
| 5.6 | `office/office/stops.py` (new) | One table of the six stop types; each maps to a pause scope and never to a trade | Each stop produces a pause event and no order intent |
| 5.7 | `office/config/risk.json` (new) | Limits as data, versioned (`risk-1.0`), owner-approved | Config hash recorded in each verdict |

### Stage 6
Forward paper run on the Stage 5 book with criteria registered first, in the G-gate style. Not planned in detail here.

---

## 8. Owner decisions (recorded 23 Oct 2026 10:19Z)

The owner answered all five on 23 Oct (`cmsg_01U4KMvkBYNknqm4HRVie8uv964VkQcqvQbBHhfQQbHd8Z`). Scope and status for
each are in `STAGE1_DECISIONS.md`:
- D-A **yes**: an append-only verdict annotation for the failed B5 V3 trials, plus eligibility tests. Proposed, not
  applied (`proposals/`).
- D-B **yes, selectively**: a pre-defined family rule for E001–E015 (`MULTIPLE_TESTING_PRIOR_ETF.md`).
- D-C **yes**: label screen-1.0 and its paper book as unvalidated exploratory research, not investable evidence.
  Wording patch proposed.
- D-D **yes**: SEC 8-K filing events as the first Stage 4 data set, with deterministic, pre-registered category
  baselines before any AI scoring.
- D-E **yes, research only**: a vendor-verified data-purchase comparison. Nothing bought, subscribed or activated.

Record contracts for Stages 2–6 and the contradictions found against PR #27 are in `INTERFACES.md`.

### Corrections to this audit (23 Oct)

- §1.3 and §4 said screen-1.0 "has no recorded verdict". That is true of the registry only.
  `equity/config/evidence.json` records its pre-registered backtest as failed (E1), and every screen and paper
  report already carries an "unvalidated: not a recommendation" banner [V]. D-C is therefore a wording change, not a
  missing label.
- Plan item 1.3 proposed appending to `trials.jsonl`. That would break two D33/D34 protection tests, so the proposal
  is now a separate ledger (`proposals/README.md`).

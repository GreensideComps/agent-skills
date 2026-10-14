# Strategy v2: an evidence-tested wealth-growth engine

Written 2026-10-14, in response to the owner's strategic reset. This document supersedes the roadmap in
[`AUDIT_AND_PLAN.md`](AUDIT_AND_PLAN.md) §7. Everything that file records as built stays as built.

**Objective:** make demonstrably better capital-allocation decisions than a global tracker (VWRP), after costs.
VWRP is the benchmark and the fallback, not the goal.

**Standard of proof:** a component earns a role in decisions only by showing that it improves them. A component
being sophisticated is not evidence that it works. Nothing in this repository has yet demonstrated an edge over
VWRP.

**Hard limits:**
- The Trading 212 ISA stays read-only.
- No trade is executed or queued without the owner's explicit approval.
- Methodology changes (weights, gates, mandates) are the owner's decision.

---

## Part 1. Audit: what is useful, what is unvalidated, what must be rebuilt

Each verdict says what the component is good for **today**.

### Genuinely useful: keep and build on

| Component | Where | Why it earns its place | Known limits |
|---|---|---|---|
| SEC point-in-time fundamentals | `equity/equity/sec.py`, `fundamentals.py`, `ingest.py` | Every value carries its concept, accession number and filing date, and splits and restatements are handled. Cross-checked against Yahoo on 13 companies: 44 of 45 comparable values agree within 2%. The filing date is what makes honest historical tests possible, and paid data often lacks it. | **Annual only** (10-K, 20-F). **US SEC filers only.** Only 146 of 5,472 linked companies are ingested so far; the nightly pipeline adds 200 a weekday. SIC codes are not point-in-time. |
| Security master | `universe.py` | Keyed by ISIN and linked to Trading 212 instruments, so anything researched maps to something buyable in the ISA. | 37 low-confidence links. ADR ratios are missing. |
| Append-only ledgers, jobs, reliability checks | `store.py`, `jobs.py`, `reliability.py` | Idempotent, auditable, and detect missed runs. A prediction ledger needs exactly this property. | Git-backed JSONL will need a columnar store once quarterly and price data grow. |
| Point-in-time backtest harness | `backtest.py` (`pit_facts`, `raw_close`) | It reproduced exactly on a full re-run (2026-10-14). The filing-date filter is the right primitive for every signal test below. | Annual decision dates, today's listings only (survivorship), small samples. See Part 2. |
| Quant research engine and promotion gate | `research/` (`engine.py`, `PROMOTION_GATE.md`) | Pre-registration, frozen grids, out-of-sample splits, block bootstrap, deflated Sharpe, costs ×3, and one change per quarter. This is the right standard, and it has already killed 15 weak ideas honestly. | Built for ETF and allocation tests. It needs a stock-level cross-sectional mode. |
| Trading 212 safety layer | `trading/t212bot/client.py`, `readonly.py`, `executor.py`, `verify.py` | Locked to the demo account, order requests are never retried, a read-only facade exists, and a report-vs-account verifier passed 37 of 37 checks. Reuse it as the **execution and monitoring layer only**. | The client refuses the live host by design. That is correct until a readiness review. |
| Portfolio monitor | `portfolio.py` | Read-only snapshot, exposure, concentration and volatility. The 14 October validation found it gives the right kind of picture. | It reads sector from SIC (ASML is misclassified). Its 1-year correlations look abnormal. It does not measure exposure to the main economic driver (AI capex). |
| Paper ledger mechanics | `paper.py` | Recommendations are logged before outcomes, fills happen only at the logged price, and the ledger is append-only. This is the integrity a prospective test needs. | The mandate it currently runs (screen-1.0 top 10) is unvalidated. Keep it running as a forward test, not as advice. |

### Unvalidated: keep running, but it must not drive decisions

| Component | Status | Evidence |
|---|---|---|
| **Screen-1.0 score** (weights 30/25/20/20/5, 8 gates) | Failed its pre-registered test (t = 1.92 against a bar of 2.0) | It has **no evidence among companies above $10bn** (IC +0.04, t = 0.6) and **none in technology** (0 years with 10 or more scored names). The "11 of 14 years" basket averaged +0.5 points a year (t = 0.5). Source: `equity/research/audit_2026-10-14/`. |
| Gates | Partly evidence-based | Negative FCF, interest cover and dilution are real financial risks. They are now applied without a test of whether excluding these companies improves returns, and they misfire on one-offs (Broadcom's dilution from the VMware deal). |
| Sub-scores | Post-hoc hints only | FCF per share t = 2.9 and valuation t = 1.4 came from 5 tests run after the fact. They are hypotheses for new tests, not findings. |
| Bear-case records | Mechanism exists, never used | The research ledger is empty, so no company can legitimately be a candidate. |
| Paper portfolio (screen-1.0 top 10 vs SPY) | Forward test, started 2026-10-14 | Too young to say anything, and it cannot say much for years (Part 2, §2.4). |

### Needs rebuilding: currently misleading

| Component | Problem | Replacement |
|---|---|---|
| **Valuation val-1.0** (DCF bands, reverse DCF) | Growth is capped at 15% (bull case 20%) and starts from a 3-year average of FCF. That calls Nvidia, Microsoft, Alphabet, Amazon and Costco 50 to 90% overvalued, so it cannot single anything out. ADRs and non-USD filers are unvalued. | An **expectations engine** (Part 3, §3.3): what the price implies, compared with base rates and a company-specific scenario range. The output is an expected-return distribution, not a single "upside". |
| Industry classification | SIC is coarse, not point-in-time, and ASML is coded as machinery | A curated sector and economic-driver map for the investable universe, plus point-in-time SIC from filings for historical tests. |
| Fundamentals cadence | Annual only, so a signal can be up to 15 months stale | Add quarterly (10-Q) facts with filing dates. Earnings-surprise, fundamental-momentum and revision-style signals need them. |
| Demo trading bot strategy | Discretionary intraday trading in 3x ETPs. The repo's own research rejected every intraday rule it tested. Currently disabled. | Repurpose the bot to execute only owner-approved stock-portfolio proposals. The intraday strategy is retired unless the owner reinstates it. |
| Portfolio construction | Does not exist. The 14 October plan's weights were hand-picked. | A rules-based sizer: conviction × evidence tier, within risk budgets. Part 3, §3.5. |

---

## Part 2. Research programme: is there a repeatable edge after costs?

### 2.1 The question, stated so it can fail

> Does a decision process built from these signals produce better risk-adjusted, after-cost returns than
> (a) VWRP, and (b) a portfolio with the **same factor exposures** built from cheap factor ETFs?

Test (b) is what separates real stock-picking skill from simply holding more tech, momentum or size risk than
VWRP. A concentrated US-tech book can beat VWRP for years on beta alone; that is not edge.

### 2.2 Candidate sources of edge, each tested before it is used

Each row below gets one pre-registered test: frozen rule and parameters, and an out-of-sample period nobody has
looked at.

| # | Source of edge | Signal (frozen before testing) | Data | Status of data |
|---|---|---|---|---|
| S1 | Valuation dislocation | FCF yield and EV/EBIT, measured within sector and size band | SEC + prices | Free, have |
| S2 | Business quality | Gross profitability, ROIC level and stability, accruals | SEC | Free, have (annual); quarterly needed |
| S3 | Fundamental momentum | Acceleration in revenue and FCF over trailing 4 quarters | SEC 10-Q | Free, **to build** |
| S4 | Earnings surprise (PEAD) | Standardised unexpected earnings from seasonal random walk, drift after filing date | SEC 10-Q + daily prices | Free, **to build** |
| S5 | Capital allocation | Net share issuance and buybacks, asset growth, acquisition intensity | SEC | Free, have |
| S6 | Market behaviour | 12-1 month price momentum, residual (idiosyncratic) momentum, 52-week-high proximity | Prices | Free, have |
| S7 | Insider behaviour | Open-market insider purchases (Form 4), cluster buys | SEC Form 4 | Free, **to build** |
| S8 | Estimate revisions | Analyst EPS and revenue revision breadth | Consensus estimates | **Paid only.** Owner decision. |
| S9 | **Expectations gap** (the core thesis) | The growth the price implies, minus a base-rate forecast for companies with the same size and growth history | SEC + prices + base rates | Free, **to build** |
| S10 | Industry developments | Sector capex cycles, supplier and customer read-throughs | Filings, news | Qualitative. **Research input only, not a scored signal**, until a testable form exists. |

Discipline:
- **Every test** reports the information coefficient (IC) by month, a long-short decile spread **net of costs**,
  a long-only top-quintile return against the universe, and results by size band (large over $10bn is the one that
  matters here), sector and regime.
- **Every configuration ever tried is counted.** Promotion uses the deflated Sharpe ratio across that count.
- **2023-01 to 2026-09 is held out** for all signals until the combined model is frozen, and is used once.
- **Signals are combined only after each passes on its own.** The combination weights are fitted in-sample and
  evaluated once out-of-sample. No hand-tuned 30/25/20/20/5.
- **What counts as success:** an out-of-sample IC with t ≥ 2 in the large-cap universe, a deflated Sharpe ≥ 0.9,
  a long-only top-quintile return above the universe after costs in at least 2 of 3 sub-periods, and survival
  of costs ×3.

### 2.3 Bias controls (the failures of test 1, fixed)

| Bias | Control |
|---|---|
| Look-ahead | Facts filtered by filing date (have). Prices at the close after filing. Classification point-in-time. |
| Survivorship | **The universe is everything that filed with SEC at each date, including companies later delisted.** SEC has their fundamentals; free prices for delisted names generally do not exist. Two steps: (1) measure the bias by counting companies that stop filing and their last known state; (2) **owner decision**: buy a survivorship-free US price history (several vendors sell one for a modest annual fee; to be quoted before any purchase). |
| Data-snooping | Pre-registration, a trial count, deflated Sharpe, one untouched holdout. |
| Small samples | Monthly decision dates instead of annual. A universe of around 3,000 US companies a month instead of 32 to 96. |
| Costs | Trading 212 FX 0.15% each way, spread by size band, 0.5% UK stamp duty where relevant, and turnover measured. ISA, so no tax. |
| Benchmark gaming | Report against VWRP **and** against a factor-matched benchmark (Ken French developed-market factors: market, size, value, profitability, investment, momentum; free and survivorship-free). |

### 2.4 Prospective evidence: what live tracking can and cannot prove

These are statistical power estimates; the assumptions are stated, and none is a forecast.

- **A concentrated portfolio proves almost nothing quickly.** With 3%/yr excess return and 10% tracking error,
  reaching t = 2 takes about (2 × 10 / 3)² ≈ **44 years**. With 5% excess return, about 16 years. The paper
  portfolio's track record will be noise for a long time, and must not be read as proof either way.
- **A broad monthly cross-sectional signal proves much faster.** If a signal's monthly IC averages 0.03 and varies
  about 0.10 month to month (a typical spread), t = 2 takes about (2 × 0.10 / 0.03)² ≈ **44 months**.
- **Consequence:** prospective tracking logs **every** signal score for the whole universe every month, not just
  the holdings. It is there to confirm the historical evidence is not decaying. It cannot replace that evidence.

### 2.5 Kill and fallback rules (set now, before any results)

- **Signals:** a signal whose prospective IC over 36 months is ≤ 0, or is significantly below its historical IC
  (t < −2), is demoted to research-only.
- **The active book:** if it trails the factor-matched benchmark by more than 5 percentage points over a rolling 24
  months, **and** its prospective information ratio is below 0, it shrinks toward VWRP by half. The owner reviews
  before it grows again.
- **The project as a whole:** if, after Stage 2, no signal passes in large caps, the honest conclusion is that this
  data does not support active stock selection. The system then becomes a disciplined satellite-and-research tool
  and the default allocation stays VWRP. Saying so is part of the job.

---

## Part 3. System design

### 3.1 Opportunity database

All records are append-only, timestamped, and carry the ids of the snapshots and prices they used. They extend
the existing ledgers.

| Record | Key fields |
|---|---|
| `signals` (new) | company, date, signal id, method version, raw value, universe percentile, data confidence. **One row per company per month, for every company.** This is the prospective-test dataset. |
| `opportunities` (new) | company, status (`idea → researching → candidate → approved → held → exited` or `rejected`), source (signal, discovery or owner), owner agent |
| `theses` | variant perception (what we believe and the market does not), drivers, **catalysts with expected dates**, invalidation conditions (measurable), evidence links |
| `bear_cases` (exists) | at least 3 evidenced objections, written by a different agent from the thesis, with watch items |
| `expectations` (replaces `valuations`) | implied growth and margins at today's price; base-rate distribution; bear, base and bull with **probabilities**; expected-return distribution; margin-of-safety price |
| `forecasts` (new) | every quantitative prediction (12-month return range, probability that a catalyst happens, next-year FCF), frozen at the time it is made, for later calibration scoring |
| `decisions` (new) | proposal, alternatives considered, expected-return gain against the best alternative and against VWRP, cost, owner verdict |
| `outcomes` (new) | realised returns against benchmarks, attribution, forecast scores. Written only by code, never edited. |

### 3.2 Agent responsibilities

**Deterministic jobs:**

| Agent | Job | Writes | May not |
|---|---|---|---|
| Data | Ingest SEC (annual, quarterly, Form 4), prices, factors; data quality checks | fundamentals, prices, factor data | Score or rank |
| Signal | Compute every promoted signal for the whole universe monthly; log all scores | `signals` | Use unpromoted signals in rankings |
| Expectations | Reverse-engineer what prices imply; base rates; scenario ranges | `expectations` | Override a thesis analyst's numbers silently |
| Portfolio constructor | Size candidates by conviction × evidence tier within risk budgets; compare against current holdings and VWRP | `decisions` (proposals) | Place orders |
| Risk monitor | Daily exposure, concentration, economic-driver exposure, drawdown, limit breaches | alerts | Trade |
| Performance and learning | Monthly attribution, forecast calibration, signal decay | `outcomes`, reports | Edit past records or re-score them with new methods |
| Reliability | Missed runs, stale data, ledger integrity | jobs, alerts | — |

**Claude routines, one per session:**

| Agent | Job | Writes | May not |
|---|---|---|---|
| Discovery | Turn top-decile signal names and owner ideas into `opportunities` | opportunities | Promote to candidate |
| Thesis analyst | Variant perception, drivers, catalysts, invalidation conditions | theses, forecasts | Write the bear case for the same company |
| Independent bear | Strongest evidenced case against | bear_cases | See the thesis's conclusion before writing |
| Signal researcher | Pre-register and run tests in `research/` | experiment records | Change live weights; the promotion gate does that |

**Gates in code:**
- **Candidate:** needs a thesis, a bear case and an expectations record.
- **Proposal:** needs data confidence ≥ medium.
- **Trade:** needs the owner's approval.

### 3.3 Research workflow, for one company

1. A signal or the owner flags it, and an `opportunity` is created with its source.
2. The expectations agent writes what the price implies, and how unusual that is against base rates.
3. The thesis analyst answers four questions:
   - Where is the market wrong, and why?
   - What would show it (a catalyst with a date)?
   - What would prove us wrong (measurable invalidation)?
   - What 12-month return range and probabilities do we forecast?
4. The independent bear writes its case.
5. Status becomes candidate only if the code gates pass.
6. The portfolio constructor ranks it against current holdings and the best alternative.
7. On a schedule and on events (a new filing, a price move over 15%, an invalidation trigger), the thesis is
   re-checked.

### 3.4 Evidence standards (tiers)

| Tier | Meaning | Allowed use |
|---|---|---|
| E0 | Idea, anecdote, narrative | Research priority only |
| E1 | Economic rationale plus published literature | Research priority only |
| E2 | Positive in-sample historical test | Research priority only |
| E3 | Passed a pre-registered out-of-sample test with costs and deflated Sharpe, in the relevant size band | May drive rankings and sizing |
| E4 | E3 plus at least 24 months of consistent prospective IC | Full weight |

A thesis is rated by its weakest load-bearing claim. Position size is capped by tier, for example:
- E2 thesis: 2% maximum
- E3: 5%
- E4: 8%

### 3.5 Ranking, sizing and continuous reassessment

- **Rank by expected excess return over VWRP, adjusted for confidence:**
  (probability-weighted expected return − VWRP expected return) × evidence-tier shrinkage, minus costs. Every
  number comes from the expectations and forecasts records, so it can be audited.
- **Opportunity cost is explicit.** Every holding is compared weekly with the best non-held candidate. A switch is
  proposed only if the expected-return gain exceeds round-trip costs **plus** an uncertainty margin that shrinks as
  evidence improves. This stops churn on noise.
- **Risk budgets are set by the owner.** Examples:
  - largest position
  - single economic driver (for example, AI capex)
  - sector
  - tracking error against VWRP
  - turnover per year

  They are enforced by the constructor, and breaches are flagged daily.

### 3.6 Monitoring and performance attribution

- **Daily:** holdings, limits, invalidation triggers, data freshness, missed runs.
- **Monthly:**
  - **Returns against both benchmarks:** returns against VWRP and against the factor-matched benchmark.
  - **Attribution:** a factor regression (market, size, value, profitability, investment, momentum) on the book,
    so returns from beta and factor tilts are separated from selection.
  - **Selection detail:** within-sector selection against sector allocation.
  - **Cost drag:** actual trading costs.
- **Quarterly:** forecast calibration, signal decay, and a written review of every decision that went badly *and*
  well, judged on the information available at the time (no hindsight).

### 3.7 Failure controls

- **Process:**
  - Pre-registration and trial counting.
  - A single held-out period.
  - At most one methodology change per quarter, approved by the owner.
  - Past records are never re-scored.
- **Data:** freshness gates; cross-source checks (SEC against a second source); stale data blocks a proposal
  instead of being silently used.
- **Portfolio:** risk budgets; the kill and fallback rules (§2.5).
- **Operational:** demo-only execution; the ISA stays read-only; owner approval for every trade; no more than 10
  orders per run; reliability alerts.
- **Human:** the owner sees every proposal with its strongest counter-argument and its evidence tier.

---

## Part 4. Staged plan

Ordered by expected impact on decision quality, not by technical interest. Each stage ends with checks that
either pass or fail.

### Stage 0: decision hygiene (now, small)

- Label screen-1.0 and val-1.0 outputs as unvalidated wherever they are shown. The ranking stays visible for
  research priority.
- Keep the paper portfolio as a forward test, renamed in reports to "screen-1.0 forward test".
- Add `evidence_tier` to recommendation and decision records.
- The 14 October validation stands as the current portfolio advice.

**Acceptance:**
- No report presents a screen rank or DCF upside as a recommendation without its tier.
- Tests pass.

### Stage 1: research data foundation (highest leverage: every later decision depends on it)

- **Quarterly fundamentals:** ingest 10-Q facts with filing dates, plus quarterly derived metrics.
- **Historical universe:** every SEC XBRL filer per month from 2010, including companies that later stopped
  filing. The `companyfacts` bulk file covers them.
- **Monthly PIT market caps:** point-in-time shares × price. Classify large (over $10bn), mid and small each month.
- **Survivorship measurement:** count companies with missing prices and their last fundamentals.
- **Factor data:** Ken French developed-market and US factor returns, ingested for attribution and factor-matched
  benchmarks.
- **Harness:** extend the backtest to monthly dates and arbitrary signals; the old annual test is kept and still
  reproduces.

**Acceptance:**
- Over 2,000 scored US companies per month from 2012; over 300 large-caps per month from 2015.
- Missing-price bias quantified and reported.
- Test 1 still reproduces (t = 1.918).
- Owner decision recorded on buying survivorship-free prices.

**Result (2026-10-14, free data; report `equity/reports/research/stage1_coverage.md`):** built (12.8M facts,
17,066 companies, 1.44M company-months, prices for 5,360 tickers). Coverage targets **not met**: scored US
companies a month from 2012 range 693 to 2,286 (median 1,648); large caps from 2015 range 297 to 707 (median 504).
The shortfall is survivorship: companies that later stopped filing have fundamentals but no free prices (0% priced
among stopped filers with $1bn+ assets). Harness check: equal-weighted large-band return vs French US market,
correlation 0.969. The annual backtest code is unchanged. Stage 2 may run on large caps from 2015, with the
survivor bias stated on every result, until the owner decides on survivorship-free prices.

### Stage 2: signal tests S1 to S7 and S9 (the core research)

- One pre-registration per signal, committed before it runs; S8 only if estimates data is bought.
- Results reported by size band, sector and regime.
- The trial count logged.

**Acceptance:** a promotion table where each signal is E3-pass, fail, or inconclusive, with the evidence
committed. **Zero passes is an acceptable, reportable outcome.**

**Interim result (2026-10-14; `equity/reports/research/stage2_signals.md`, pre-registration
`research/prereg/stage2.md`):** 0 of 11 trials pass in large caps (first batch) from 2015-01 to 2022-11. Nine fail; gross
profitability (S2a) and revenue acceleration (S3b) are inconclusive (IC t 1.18 and 1.37). The largest
large-cap IC is 0.013, and no top quintile beats the universe after costs except low net issuance (+0.7% a year,
DSR 0.12 after 14 trials). Some small caps have IC t > 2 (FCF yield, gross profitability, low issuance), but
that band is not the deciding one and is the most exposed to survivor bias. Addendum 1 (residual momentum S6c,
insider net buyers S7a, insider purchase value S7b) also fails: 0 of 14. Addendum 2 (S9 expectations gap, the
core thesis) fails too (IC −0.002, t −0.12): **0 of 15 pass in large caps.** The §2.5 project kill rule is
therefore met on free data. Every Stage 2 signal stays at E0/E1: none may drive rankings or sizing.

**Owner decision (2026-10-14): satellite mode.** VWRP is the core allocation. No paid data for now. The system
keeps researching and logs all 15 signals for the whole universe every month, before outcomes exist
(`research/signal_log.py`, run by `research/monthly_signal_log.sh`; report `equity/reports/research/signal_log.md`).
The log starts with decisions at 2026-10-31, so the 2023-01..2026-09 holdout stays unread. Paid data is revisited
only if the live log shows something worth confirming.

### Stage 3: expectations engine (replaces val-1.0)

- Base-rate tables (growth persistence by size and starting growth) built from the SEC history.
- Reverse DCF on current FCF with a reinvestment assumption.
- Scenario probabilities; ADR ratios; currency handling.

**Acceptance:**
- It no longer flags most mega-caps as 50 to 90% overvalued by construction.
- The expectations-gap signal (S9) is tested in Stage 2's framework.
- Margin-of-safety prices are reproducible from stored inputs.

### Stage 4: opportunity database and research workflow

- New ledgers: `signals`, `opportunities`, `forecasts`, `decisions`, `outcomes`.
- Thesis, bear and expectations routines, each in its own session.
- Code gates for candidacy.

**Acceptance:**
- 10 complete research files, each with a thesis, a bear case, expectations, catalysts and invalidation
  conditions.
- Every forecast frozen and timestamped.
- Gates enforced by tests.

### Stage 5: portfolio construction and continuous reassessment

- Sizing by conviction × tier; owner-set risk budgets; switch hurdle; weekly holdings-vs-alternatives review.
- Proposals go to the owner. Approved ones execute on demo.

**Acceptance:**
- A proposal shows its expected excess return, tracking error against VWRP, costs, factor exposures and the
  strongest counter-argument.
- The demo bot executes only approved proposals.
- No order without an approval record.

### Stage 6: performance, attribution and learning loop

- Monthly attribution against VWRP and the factor-matched benchmark.
- Forecast calibration (Brier score, interval coverage).
- Signal decay monitor; quarterly no-hindsight review.

**Acceptance:**
- The report runs unattended monthly.
- Attribution reconciles to total return within 0.1%.
- Calibration is reported once 30 or more forecasts have resolved.

### Stage 7: live readiness review (owner's decision)

**Evidence the review needs:**
- Stage 2 results.
- At least 12 months of prospective signal logs.
- The demo track record.
- Reliability record.
- ISA constraints.

The owner decides. No code change to the live host before then.

---

## Decisions only the owner can make

1. **Paid data.** Pick neither, one or both:
   - **Survivorship-free US prices:** the biggest remaining bias in stock-level tests.
   - **Consensus estimates:** S8, revisions, a well-documented signal family.

   Quotes will be gathered before asking for money.
2. **Risk budgets:**
   - maximum position
   - maximum single economic driver (AI capex)
   - maximum tracking error against VWRP
   - turnover
3. **Retire the intraday demo strategy** and repurpose the bot to execute approved stock-portfolio proposals only.
4. **What to hold meanwhile.** Whether the demo portfolio holds steady (the 14 October validation's minimal plan)
   while Stages 1 and 2 run.

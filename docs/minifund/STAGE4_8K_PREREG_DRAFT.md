# DRAFT pre-registration: deterministic SEC 8-K category baselines (owner decision D-D)

**Status: DRAFT for owner review. Not registered.** Nothing in this document has been run.
- No event has been joined to a price.
- No return, mean, t-statistic or count of outcomes has been computed or looked at for any 8-K category, in any
  period.
- The rules below were written without data. This follows the owner task of 2026-10-23 11:39Z
  (`cmsg_01U4KMvkBYNknqm4HRVie8uv464y4sReNiYrojmwW6sV3V`), item 3: "Do not calculate event-study results or inspect
  outcomes to tune the rules before the specification is registered."

**Registration is the commit that adds the trial events to the registry.** Until then this text may change; after
it, it may not. Registration is blocked today by the registry pin (U1) and needs the Stage 2 filings data (§9).

## 1. Purpose and prior knowledge

**Purpose.** These baselines set the bar that any later AI-scored 8-K signal must beat (roadmap Stage 4). The
expected result is that no category earns a tradable net return. "No trade" (B1) is the default, and it stands
unless a baseline passes every criterion in §7.

**Prior knowledge, disclosed.** The authors (the owner and the model) know the published literature on:
- post-earnings-announcement drift, which is weaker in recent decades and in large caps;
- returns around material agreements and executive changes.

The 2023–2026 market is broadly known (`SPLIT_POLICY.md` §3). No in-house study of 8-K outcomes exists. A repository
search on 23 Oct found 8-K references only in two unrelated test fixtures. This knowledge is why the categories
are fixed by item code here and are not chosen from results.

## 2. Events: categories and eligibility

**Source.** `FilingEvent` records (INTERFACES §1.2) from Stage 2 ingestion (`STAGE2_FREE_DATA_READINESS.md` §1).

**Event definition.**
1. Form `8-K` only. `8-K/A` amendments are excluded as events and counted in the report.
2. One event per (CIK, acceptance date in America/New_York). Several 8-Ks on the same date merge into one event
   whose item set is the union.
3. Item set as filed (`taxonomy_version: 8k-items-1.0`), i.e. post-August-2004 item codes. Nothing is learned or
   inferred.

**Categories (fixed; 4 tested + 1 comparator).**

| Id | Category | Rule |
|---|---|---|
| B1 | No trade | Holds nothing; return 0 versus the benchmark. The comparator, not a trial. |
| B2 | Any 8-K | Every eligible event. |
| B3a | Results of operations | Item set contains `2.02`. |
| B3b | Material definitive agreement | Item set contains `1.01`. |
| B3c | Officer or director change | Item set contains `5.02`. |

An event may belong to more than one B3 group. Overlap counts between groups are reported.

**Eligibility (all must hold, judged with data available at `available_at`).**
1. The CIK maps to a common stock in the research dataset (`research/dataset.py`) in the **large** band at the last
   month-end before `available_at` (the bands B5 used; cost §5).
2. Close at entry ≥ $1.00 (B5's `min_price`).
3. Entry close and SPY close both exist on the entry date.
4. The event has no item `1.03` (bankruptcy) or `3.01` (delisting notice). These are excluded because the free price
   data is missing most failed companies (Stage 2 §5.1), so their outcomes would be biased upward. The excluded
   count is reported.
5. `available_at` is not null (a header was found).

## 3. Timestamps and the next-tradable-price convention

- **Information time** = `available_at`: the EDGAR header `ACCEPTANCE-DATETIME`, read as America/New_York and
  stored in UTC. The submissions JSON time is never used (INTERFACES C10).
- **Entry** = the close of the first NYSE session whose ET date is **strictly after** the ET acceptance date. Examples:

  | Accepted (ET) | Entry close |
  |---|---|
  | Tue 09:00 | Wed |
  | Tue 20:00 | Wed |
  | Fri 18:00 | Mon |
  | Sat | Mon |

  This deliberately gives up the same-day reaction, so it cannot use a price set before the filing was public. It
  matches the `next_day_close` convention of B4/B5.
- **Exit at horizon h** = the close h NYSE sessions after the entry session, for h ∈ {1, 5, 20}.
- **Calendar:** SPY trading days (as `nyse_calendar_to_2022.csv.gz`).
- **Missing prices:** if the stock has no close at exit, the last close is used and then the B5 rule applies
  (`edge_rules.holding_return`, `missing_return = −0.30`). The count of such events is reported.

## 4. Returns

- **Stock return** r_i(t0, t0+h) from adjclose (total return).
- **Benchmark:** SPY adjclose over the same sessions. **Market-adjusted return** AR = r_i − r_SPY. US large caps
  are benchmarked to the US market here. The VWRP comparison belongs to the portfolio layer (Stage 5), not to this
  event test.
- **Secondary (reported, not used for pass/fail):** AR against the equal-weighted large-band universe, and alpha on
  Fama-French 5 factors plus momentum (daily, Ken French library).
- **Calendar-time portfolio (primary statistic).** For each category c and horizon h:
  1. on each session d, hold an equal weight in every event of c whose holding window covers d;
  2. the portfolio's daily return is the mean daily AR of those events, minus costs (§5) on entry and exit days;
  3. sessions with no open event are left out, and their count is reported.

  This handles overlapping and same-day events, which are cross-correlated, without assuming independence.
- **Event-level mean net CAR** is reported alongside, with standard errors clustered by entry date.

## 5. Costs

- 0.30% one way for the large band, FX included (`docs/edge/EVALUATION_SPEC.md` §4, `B5_PREREGISTRATION.md` §6), so **0.60% round trip
  per event**.
- Also reported at **2× costs** (1.20% round trip).
- No borrow cost: long only. The tactical sleeve is long only.

## 6. Duplicates and overlaps

1. Same company, same ET date: merged (§2.2).
2. 8-K/A: excluded. The original 8-K is the event.
3. **Same company, overlapping windows, same category:** the earlier event is kept and a later event whose entry
   falls inside its window is dropped, for each horizon separately. Drops are reported by category and horizon.
4. Different companies on the same day are kept. Calendar time (§4) absorbs their correlation.
5. Re-filed or corrected headers (revision events in Stage 2) use the first version's `available_at`, never a later
   one.

## 7. Windows, holdout boundary and rejection criteria

### 7.1 Exploration window

- Events with `available_at` from **2012-01-01**.
- Outcomes realised by **2022-12-30**: for each h, the last eligible entry is the session h trading days before
  2022-12-30.
- This uses `edge_split`'s boundary-by-outcome rule (`SPLIT_POLICY.md` §1), adapted from months to sessions. The
  window starts in 2012, as `SPLIT_POLICY` allows; the 2005–2011 events are not used.

### 7.2 Holdout and prospective

- **2023-01 to 2026-09 is not used by this registration.** It is partly seen (`SPLIT_POLICY.md` §3), and only
  **one** confirmation batch is allowed, ever (`MAX_BATCHES = 1`, decision D2).
- Spending it on baselines whose likely result is "no trade" would waste it.
- Prices after 2022-12-31 are not joined to any event by this trial. The run script calls
  `edge_split.assert_exploration_only`.
- A category×horizon that passes exploration becomes an **E2 candidate only**. Its confirmation is **prospective**:
  events after the registration date, logged write-once, for at least 12 months (`DECISIONS.md` D3 by analogy), before any
  paper allocation. Using the holdout instead would need a separate owner decision (U5).

### 7.3 Multiple testing

- **Trials:** 4 categories × 3 horizons = **12 registered trials**, each `counts_for_dsr: true`, `kind: trial`,
  `phase: exploration`, `families: ["none"]`.
- **D-B families:** `none`, so 0 configurations are added from E001–E015 (`MULTIPLE_TESTING_PRIOR_ETF.md`).
- **Registry N** at registration = n_trials before registration + 12. Today that is 102 + 12 = **114**.
- **Within the batch:** Holm–Bonferroni over the 12 one-sided tests at family-wise α = 0.05. This is reported, and
  a trial must survive it.

### 7.4 Rejection criteria

A category×horizon **fails** unless all of these hold. Failure is the default.

| # | Criterion |
|---|---|
| R1 | Calendar-time net mean daily AR > 0 and Newey-West t ≥ **3.0**, with lags = max(5, h) (E2 bar, `EVALUATION_SPEC.md`) |
| R2 | It survives Holm at family-wise 0.05 (§7.3) |
| R3 | Net mean > 0 at **2× costs** |
| R4 | Net mean > 0 in at least **2 of 3** sub-periods: 2012–2015, 2016–2019, 2020–2022 |
| R5 | FF5 + momentum alpha of the calendar-time net series > 0 with t ≥ 2.0 |
| R6 | Deflated Sharpe (annualised calendar-time Sharpe; `edge_registry.deflated_sharpe` with the registry N) ≥ **0.9** |

- **Sample size:** fewer than **200 events or 100 distinct companies** after eligibility makes the trial
  **inconclusive**. That is never a pass, and it is reported as such.
- **No re-runs:** a failed or inconclusive trial may not be re-tuned in exploration (new item groups, horizons,
  entry rules or universes). Any variant is a new registered trial counted in N.
- **Verdicts:** each trial gets a `TrialVerdict` (INTERFACES §2.2) recorded through the D-A verdict ledger
  (`edge_verdicts.py`, if approved), so pm eligibility can read it.

## 8. Reporting (always, pass or fail)

For each category×horizon the report gives:
- events before and after each eligibility filter (with reasons), by year and by item;
- distinct companies;
- 8-K/As excluded, same-day merges and overlap drops;
- missing-exit events and the 1.03/3.01 exclusions;
- sessions with no open position;
- all of R1–R6 with their values;
- the two secondary benchmarks;
- the survivorship caveat (§2, Stage 2 §5.1).

Nothing is left out because it looks bad.

## 9. What must exist before registration

1. Stage 2 §1 filings data for the universe, with the header cross-check passed.
2. Stage 2 §2 daily prices to 2022 (+ manifest hash).
3. Stage 2 §3 run provenance.
4. A run script (`research/edge_8k_baselines.py`) and its tests, committed **before** registration. It refuses to
   run unless the 12 trials are registered and their registration commit hashes this document and the script.
   Tests use synthetic events and prices only.
5. Owner approval of U1 (registry prefix pin) and of this text.

Allowed before registration: counting events by year and item (no prices, no returns), to check that the
sample-size floor is reachable. Not allowed: anything that joins a price or a return to an event.

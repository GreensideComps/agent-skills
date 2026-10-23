# Mini fund record contracts (proposed, Stage 1 close-out)

Status: **proposal for owner review.** Docs only: no code, config, schema or ledger implements these contracts yet.
They define what Stages 2–6 must write and read, so each small PR in the audit's §7 plan can be tested against a
fixed contract. Version of this document: `contracts-0.1` (2026-10-23).

Evidence labels as in `STAGE1_CAPABILITY_AUDIT.md`: [V] checked directly, [T] a test asserts it, [R] from a report,
[A] inference.

## 0. Rules that apply to every record

### 0.1 Envelope (required on every record)

| Field | Type | Meaning |
|---|---|---|
| `schema` | string | Contract name, e.g. `FilingEvent`. |
| `schema_version` | semver string | Contract version. A field removed or redefined is a major bump. Readers refuse a major version they do not know. |
| `record_id` | hex sha256 | Hash of the canonical JSON (sorted keys, no whitespace) of every field except `record_id` and `prev`. The same content always has the same id. |
| `prev` | hex sha256 or genesis | Hash of the previous line in the same ledger, as in the registry and office log. Required for decision-grade ledgers (§3.5–3.11); optional for bulk data ledgers, which are hashed per file instead. |
| `recorded_at` | UTC timestamp | When this system wrote the record (writer's clock). |
| `writer` | object | `{component, method_version, git_commit, config_sha256}`. `config_sha256` covers every config file the writer read. |

### 0.2 Timestamps

All timestamps are ISO 8601 UTC with a `Z` suffix and at least second precision. Dates without times are allowed
only where the source has no time, and the field name then ends in `_date`.

Four different times are kept apart and never substituted for each other:

| Field | Meaning | Example |
|---|---|---|
| `event_time` | When the thing happened in the world | fiscal period end; a trade's execution time |
| `available_at` | The earliest time this system could have known it. **Point-in-time logic uses only this field.** | SEC acceptance time; vendor publication time |
| `retrieved_at` | When this system fetched it | download time |
| `recorded_at` | When this system wrote the record | envelope |

Rules:
- A record with no defensible `available_at` is labelled `available_at_basis: "unknown"` and may not feed a
  backtest. If only a date is known, the value is that date plus a stated conservative lag: next trading day close
  for prices, and 23:59:59 America/New_York on the filed date for SEC filings without a time.
- `available_at_basis` records how `available_at` was found: `source_timestamp`, `filed_date_plus_lag`,
  `retrieval_time` (forward collection only) or `unknown`.
- Converting to UTC uses the IANA zone named in `source_tz`, never a fixed offset.

### 0.3 Provenance

Every data-bearing record carries a `source` object:
`{name, url, licence, vendor_version|null, retrieval_method, content_sha256}`, where `content_sha256` is the hash of
the raw bytes as fetched. Raw payloads are kept (or their hashes, when they are too large or the licence forbids
keeping them) so a record can be re-derived. A derived record lists its inputs by `record_id` in `derived_from`.

### 0.4 Revisions

- Nothing is overwritten. A correction is a new record with `revision` (an integer, starting at 0),
  `supersedes` (the `record_id` it replaces) and `revision_reason`.
- A point-in-time read "as of T" returns, for each key, the latest revision with `available_at <= T`. A plain read
  of "latest" exists only for monitoring and is never used by research.
- A vendor's silent restatement (for example, Yahoo re-adjusting a past close) is detected on refresh and written as
  a revision with `revision_reason: "vendor_restatement"`.

### 0.5 Versioning

- `schema_version`: the record's shape (this document).
- `method_version`: the logic that produced it (`screen-1.0`, `paper-1.1`, `pm-1.0`, `risk-1.0`, ...). Any rule
  change is a new method version. Old records keep their version and are never restated.
- `config_sha256`: the exact parameters. Two records with the same method version and different config hashes are
  not comparable without a note.

## 1. Data layer (Stage 2)

### 1.1 `DataRecord` (a price, fundamental fact or macro value)

| Field | Notes |
|---|---|
| `kind` | `price`, `fundamental`, `macro`, `fx`, `corporate_action` |
| `key` | e.g. `{instrument_id, field}` or `{cik, concept, period_end, unit}` or `{series_id}` |
| `value`, `unit`, `currency` | `currency` is required for money; ISO 4217 |
| `event_time` / `period_end_date` | the observation's own time |
| `available_at`, `available_at_basis`, `retrieved_at` | §0.2 |
| `return_basis` | prices only: `price` or `total_return`. VWRP is accumulating, so its price is effectively `total_return` net of fees. |
| `adjustment` | prices only: `raw`, `split_adjusted` or `split_dividend_adjusted`, with the factor used |
| `revision`, `supersedes`, `revision_reason` | §0.4 |
| `source` | §0.3 |
| `quality_flags` | list of named flags from the data-quality checks, e.g. `negative_adjclose`, `share_outlier` |

Maps to today's code: SEC companyfacts values already carry accession and filed date (`fundamentals.py`) [V]. Price
rows carry neither `retrieved_at` nor a content hash [A]; adding them is audit plan item 2.2.

### 1.2 `FilingEvent` (SEC filing, the first Stage 4 data set, owner decision D-D)

| Field | Notes |
|---|---|
| `cik`, `accession`, `form` | e.g. `8-K`, `8-K/A` |
| `items` | 8-K item codes as filed, e.g. `["2.02", "9.01"]` |
| `acceptance_time_source` | the `<ACCEPTANCE-DATETIME>` value from the filing header, verbatim (America/New_York) |
| `available_at` | **proposed:** the header time converted to UTC with `source_tz: "America/New_York"`, `available_at_basis: "sec_header_acceptance_et"`. Provisional until the 200-filing cross-check passes; `null` (never a substitute) when the header is missing or unparseable |
| `submissions_json_acceptance` | the `acceptanceDateTime` from `data.sec.gov/submissions`, kept **verbatim as a string**, never parsed into `available_at` and never normalised |
| `filed_date` | the EDGAR filing date |
| `is_amendment`, `amends` | links an `/A` filing to the original accession |
| `period_of_report_date` | the event date the filer states |
| `source` | §0.3 (filing index URL and header hash) |

**Timestamp finding [V, one filing, 23 Oct].** For Apple's 8-K `0000320193-26-000018`, the filing index and header
say accepted `2026-07-30 16:30:28` (America/New_York, so 20:30:28Z). The submissions JSON gives
`2026-07-31T00:30:28.000Z`, which differs from the header's UTC time by four hours **in this one filing**. Nothing
is concluded about other filings, about the cause, or about whether the offset is constant. The contract therefore
**proposes** the header as the source of `available_at`, keeps the JSON value verbatim, and makes the rule final only
after the Stage 2 cross-check of at least 200 filings across EST and EDT dates (`STAGE2_FREE_DATA_READINESS.md` §1).
If that check finds the header itself unreliable, `available_at` stays `null` for the affected filings.

### 1.3 `EventRecord` (an interpreted event: roadmap §3)

| Field | Notes |
|---|---|
| `event_type` | from a fixed, versioned taxonomy (`taxonomy_version`). For 8-K baselines it is the item code itself. |
| `entity` | `{cik, instrument_id}` |
| `source_records` | `record_id`s of the `FilingEvent`s or articles used |
| `source_time` | the earliest `available_at` of those sources |
| `novelty` | `{status: new|repeat|update, cluster_id, first_seen_record_id}`. Copies of one story or filing share a `cluster_id` and count once. |
| `expected_impact` | optional structured fields (revenue, margin, cash flow, valuation direction). Empty for deterministic baselines. |
| `market_response` | filled later, only from data with `available_at` after `source_time`, at fixed horizons (+1, +5, +20 trading days) |
| `decision` | always `research_only` until a validated rule applies; a link to the `DecisionRecord` otherwise |
| `extractor` | `{type: rule|model, method_version, model_id|null, prompt_sha256|null, temperature|null}`. A model extraction is reproducible only to the extent recorded here. |

### 1.4 `FeatureValue`

`{feature_id, feature_version, entity, as_of, value, inputs: [record_id...], available_at}`, where
`available_at = max(available_at of inputs)`. Any feature computed on data past `as_of` is refused at write time.

## 2. Research layer (Stage 3)

### 2.1 `TrialRegistration`

The existing registry `register` event (`research/edge_registry.py`) [V], plus the fields owner decision D-B and the
roadmap §6 require for **new** trials:

| Field | Notes |
|---|---|
| `baseline_ids` | the registered baselines this trial must beat |
| `families` | from the fixed vocabulary in `MULTIPLE_TESTING_PRIOR_ETF.md` |
| `experiment_count` | N used for the deflated Sharpe, with its breakdown (`registry_n`, `prior_etf_n`) |
| `data_requirements` | data set ids and the earliest `available_at` needed |
| `rejection_criteria` | the gates, fixed before any result exists |

### 2.2 `TrialVerdict`

| Field | Notes |
|---|---|
| `trial_id` | registered id |
| `verdict` | `pass`, `fail` or `inconclusive`. This is the only vocabulary a portfolio reader uses. |
| `label` | the producing gate's own label, verbatim (B5 uses `fail`, `lead, not a pass`, `E2 candidate`, or the blocked-E2 label) |
| `phase` | `exploration`, `confirmation` or `prospective` |
| `evidence`, `evidence_sha256` | the report |
| `source` | `result` (the verdict is on the result line) or `annotation` (in the D-A ledger) |

Mapping of B5 labels to `verdict`: `fail` → `fail`; `lead, not a pass` → `inconclusive`; `E2 candidate` and the
blocked-E2 label → `pass` **with `phase: exploration`**, which is never sufficient for allocation (§3.1).

## 3. Portfolio, risk and paper layer (Stage 5)

### 3.1 `StrategyEligibility`

`{strategy_id, owner_decision, trials: [trial_id], verdicts: [TrialVerdict], evidence_tier, eligible, reason}`.
Eligible only if every cited trial has exactly one `TrialVerdict` with `verdict: pass` **and** `phase` is
`confirmation` or later, and the strategy's evidence tier is at least the one the owner set for paper allocation
(D3: a conditional E3 holdout pass, then 12 months of prospective evidence before any demo allocation).

### 3.2 `SleeveTarget`

`{decision_id, sleeve: core|tactical, strategy_id|null, instrument_id, weight, currency, reason, evidence: [ids]}`.
The core sleeve's target is VWRP and the remainder. Every tactical row names its strategy, so per-strategy
attribution is possible.

### 3.3 `RiskVerdict`

`{decision_id, risk_version, config_sha256, checks: [{constraint, limit, value, calc, evidence, enforced,
status: pass|fail|unverified}], verdict: accept|reject, independent_of: [component versions]}`. It is produced by
the independent controller (audit plan 5.1) from the book and the intent alone. It never reads the proposer's own
check results. An `unverified` enforced check rejects.

### 3.4 `DecisionRecord`

`{decision_id, decision_time, data_cutoff, inputs: [record_id], proposal_ref, risk_verdict_ref, outcome:
no_trade|rebalance|rejected, explanation}`. `data_cutoff` is the `available_at` bound used for every input. "No
tactical trade" is a normal, recorded outcome.

### 3.5 `OrderIntent`

`{decision_key, decision_id, sleeve, instrument_id, side, quantity, position_before, limit_reference_price,
risk_verdict_ref}`. `decision_key` is unique and used once (as `orders.py` already enforces) [T]. An intent without
an `accept` RiskVerdict is refused.

### 3.6 `PaperFill`

`{decision_key, fill_time, quantity, price, price_record_id, fill_rule, costs: {spread_bps, fx_bps, commission},
currency, fx_rate_record_id}`. `fill_rule` names the rule (`next_day_close`, `decision_price_plus_spread`, ...) and
must equal the rule the strategy was tested under.

### 3.7 `BookSnapshot` and `Reconciliation`

`BookSnapshot`: `{book_id, as_of, base_currency: GBP, cash, positions: [{instrument_id, sleeve, strategy_id,
quantity, price_record_id, value_gbp}], nav_gbp}`.
`Reconciliation`: `{book_id, as_of, expected_from_fills, observed, differences, status: ok|mismatch}`. A mismatch
pauses the affected workflow (an operational stop).

### 3.8 `StopEvent`

`{stop_type: research|performance|data|operational|usage|portfolio, scope, trigger, evidence, raised_at,
action: pause, cleared_by: owner_message|null}`. A stop never creates an order intent.

### 3.9 `AttributionSeries`

Three series, all in GBP on the same dates: `vwrp_only`, `vwrp_plus_tactical` and `tactical_alone`, each with
`return_basis` stated.

## 4. Contradictions found (schemas vs audit vs PR #27)

Each one is listed with the side these contracts take. None is fixed in code by this document.

| # | Where | Contradiction | Proposed resolution |
|---|---|---|---|
| C1 | PR #27 `pm.trial_verdicts` vs registry | pm reads `verdict` only from `result` events. B5 V3 results have none [V], so pm sees "results are none", not "fail". Safe (it refuses), but the reason is wrong and any future verdict-less result looks "unknown" rather than failed. | D-A ledger plus the pm patch in `proposals/DA_pm_on_pr27.patch`. |
| C2 | PM_SPEC §1 vs `docs/edge/DECISIONS.md` D3 and `equity/config/evidence.json` | pm-1.0 makes a strategy eligible on the owner's listing plus one `pass` result. It does not check the phase (an exploration pass qualifies) or the evidence tier. D3 requires a holdout pass (conditional E3) then 12 months of prospective evidence, and `evidence.py` lets only E3/E4 drive sizing. | §3.1: eligibility also requires `phase >= confirmation` and the owner-set tier. Needs a pm-1.1 spec change (owner). Today the owner listing is the only guard. |
| C3 | Verdict vocabularies | Three vocabularies: Stage 2 `pass/fail/inconclusive`; B5 labels; evidence tiers E0–E4. pm-1.0 knows only `pass`. | §2.2 mapping; tiers stay a separate field. |
| C4 | PR #27 pm vs §0.1 | pm's record has `as_of` (a date) and input file hashes, but no `decision_time`, `data_cutoff`, `git_commit` or limit-constant version. Its limits are code constants, not a hashed config. | `writer` envelope; limits move to `office/config/risk.json` (audit plan 5.7). |
| C5 | PR #27 pm vs roadmap §2 and audit §5 | The company look-through check is computed but `enforced: False`. The roadmap says the tactical cap must cover overlapping holdings. The owner's 20 Oct rule keeps it UNVERIFIED until holdings are sourced. | Keep it unverified now. Once sourced, it becomes enforced in `risk.py`, not in pm. |
| C6 | Paper books | `paper-1.0`/`1.1` are in USD, price-only [V]. The mini fund's book and VWRP are in GBP, and VWRP is accumulating. | §3.7: the GBP fund book is separate. paper-1.1 stays as the diagnostic "screen alone" book, with `return_basis` stated. |
| C7 | Fill rules | Research uses `next_day_close` (`edge_rules.py`) [V]. The equity paper book fills at the logged decision price plus costs (`paper.py`) [V]. A strategy can be tested under one rule and paper-traded under the other. | §3.6: `fill_rule` must match the tested rule. |
| C8 | `orders.Broker` vs pm output | `orders.py` takes ticker quantities and a decision key [T]. pm outputs weights with no decision key and no sleeve tag. | `SleeveTarget` → `OrderIntent` translation in `paper_book.py`, with `decision_key` derived from `decision_id`. |
| C9 | Ledgers | Office log and edge registry are hash-chained [T]. The equity JSONL ledgers give each record a 16-hex content id (`rid`, `store.py:29`) but no chain to the previous line [V]. | §0.1: decision-grade records chain; bulk data hashes per file. |
| C10 | SEC timestamps | `submissions` JSON `acceptanceDateTime` disagrees with the filing header by +4 h in one case [V]. | §1.2: header proposed as the `available_at` source, subject to the 200-filing cross-check; JSON kept verbatim. Not generalised from one filing. |
| C11 | Audit §1.3 / §4 vs `equity/config/evidence.json` | The audit said screen-1.0 "has no recorded verdict". The registry entry M8-T1 indeed has none [V], but `evidence.json` already records screen-1.0 as **E1, pre-registered backtest failed (IC t = 1.92 vs 2.0)**, and every screen and paper report prints an "unvalidated: not a recommendation" banner [V]. | The audit is corrected (see its §4). D-C changes only the wording and adds the missing paper-1.1 entry (`proposals/DC_EVIDENCE_LABELS.md`). |
| C12 | PR #27 paper-1.1 vs `evidence.json` | PR #27 adds `paper-1.1` but `evidence.json` lists only `paper-1.0` [V], so `evidence.tier("paper-1.1")` returns E0 and the banner says "allowed use: none recorded". | Add a `paper-1.1` entry (in D-C proposal, applied on PR #27 only after owner review). |
| C13 | pm-1.0 vs registry kinds | pm checks `kind == "trial"` but not `counts_for_dsr`. The research-side helper in the D-A proposal checks both. | Align pm to the stricter check when C2 is fixed. |

## 5. Unresolved assumptions

- A1. The SEC header time is the acceptance time (C10). Checked on one filing only; to be tested on ≥ 200 filings before it is relied on.
- A2. VWRP's accumulating price is a fair total-return proxy net of its ongoing charge [A].
- A3. A single GBP base for the fund book is right for an ISA holding USD shares (FX costs come from the T212 fee
  schedule, not yet measured) [A].
- A4. Moving the equity ledgers to chained records (C9) is assumed unnecessary for bulk data. That holds only if per-file hashes are recorded with each research run (audit plan 2.3).
- A5. `record_id` over canonical JSON is stable across Python versions for floats. It needs a test with
  representative values before Stage 2 depends on it.

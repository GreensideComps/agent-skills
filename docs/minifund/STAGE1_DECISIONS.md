# Mini fund Stage 1: owner decisions and their scope

Recorded from the owner's message of 2026-10-23 10:19Z (`cmsg_01U4KMvkBYNknqm4HRVie8uv964VkQcqvQbBHhfQQbHd8Z`),
in reply to `STAGE1_CAPABILITY_AUDIT.md` §8. The owner's words are quoted; "Status" is what has been done under each.

**Standing boundary for all of them:**
- Stage 0 is not touched: PR #29, G2, the G1/G2 files, worker/gate/health code, scheduled tasks, the state branch,
  credentials, permissions and account settings stay as they are.
- PR #27 and PR #29 are not merged.
- There is no live test, drill or acceptance run, no purchase, and no paid service.
- None of these decisions authorises a merge or live operation.

| Id | Owner decision (verbatim) | Scope | Status (23 Oct) |
|---|---|---|---|
| D-A | "YES — propose an append-only verdict annotation for the failed B5 V3 trials. Do not rewrite or delete registry history. Add eligibility tests so failed trials cannot qualify." Also: "Do not modify the registry yet; present the exact proposed append-only annotation and test diff for review first." | Two annotations (H1, S2a V3 → `fail`); eligibility tests on both the research side and pm-1.0 | Proposed in `proposals/` and tested in scratch copies; **registry unchanged**. It is a separate ledger, so the pinned registry stays byte-identical (`proposals/README.md`). Awaiting review. |
| D-B | "YES, selectively — document and apply a pre-defined multiple-testing rule for relevant prior ETF experiments E001–E015 when researching related momentum/factor strategies. Do not indiscriminately count unrelated experiments for every strategy." | Rule and family table fixed before any new trial; applied at registration from Stage 3 | Rule written: `MULTIPLE_TESTING_PRIOR_ETF.md`. Family assignment awaits review. The code is Stage 3 (audit plan 3.3). N today stays 102. |
| D-C | "YES — clearly label screen-1.0 and its paper-book results as unvalidated exploratory research, not investable evidence." | `screen-1.0`, `paper-1.0` (and `paper-1.1` if PR #27 proceeds) | Existing E1 banners confirmed [V]. Wording patch `proposals/DC_evidence_labels.patch` tested (equity 119); awaiting review because it changes daily pipeline output. |
| D-D | "YES — use SEC 8-K filing events as the first Stage 4 dataset, starting with deterministic, pre-registered category-based baselines before AI scoring." | Stage 4 data set and baseline order | Contract `FilingEvent` in `INTERFACES.md` §1.2, with the acceptance-time finding (C10). Ingestion is Stage 2 code (audit plan 2.1), not built. Pre-registration of the category baselines comes before any outcome is computed. |
| D-E | "YES, research only — prepare a vendor-source-verified data-purchase comparison. No purchase, subscription, account creation or paid API activation is authorised." | Read vendors' own public pages only | Done 23 Oct: `DATA_PURCHASE_COMPARISON.md`, from vendors' public pages only (no account, trial, key or contact form). No purchase recommended. Norgate price and Finnhub pages could not be verified. |

## D-D: order of work for the 8-K data set (plan, nothing registered)

1. Stage 2 builds `FilingEvent` ingestion from EDGAR (free; ≤10 requests a second with a declared User-Agent), with
   a proposed header-based `available_at` (JSON time kept verbatim) and a sampled check of the header against the JSON times across EST and EDT dates.
2. Freeze the category taxonomy as 8-K item codes plus amendment status (`taxonomy_version 8k-items-1.0`). There are
   no learned or AI categories.
3. Pre-register the baselines on the exploration window only (`edge_split`), each with families `none` under D-B:
   - B1: no trade;
   - B2: market-adjusted drift after any 8-K;
   - B3: one fixed rule per pre-chosen item group, e.g. 2.02 results, 1.01 material agreements, 5.02 officer
     changes.
   Horizons are +1, +5 and +20 trading days from `available_at`, with B1 execution prices and `next_day_close`
   fills.
4. Only after the baselines' report: AI-extracted candidates (roadmap candidates 4–5). Each is a new trial with the
   model and prompt hashed into its registration.

## D-E: comparison plan

- **Candidates:** Norgate Data (US prices including delisted), EODHD (prices, fundamentals, news), Sharadar via
  Nasdaq Data Link (fundamentals and prices), Polygon/Massive news, Tiingo news, Finnhub, and one consensus-estimates
  source for S8 revisions.
- **For each:** price and plan as published on the vendor's own page (URL and retrieval date), history start,
  delisted coverage, point-in-time handling, timestamps, and personal versus commercial licence terms.
- **Output:** a comparison only. The owner decides separately whether any purchase case is worth writing.

## Stage 1 close-out and free-data readiness (owner task 2026-10-23 11:39Z)

Task `cmsg_01U4KMvkBYNknqm4HRVie8uv464y4sReNiYrojmwW6sV3V`, documentation and offline planning only.

| Item | Where | Status |
|---|---|---|
| Schemas DataRecord, EventRecord, SleeveTarget, RiskVerdict, PaperFill (timestamps, provenance, revisions, versioning) | `INTERFACES.md` §0–§3 | Done (contracts-0.1) |
| D-A..D-E and their boundaries | This file | Done |
| screen-1.0 / paper-book label, historical results unaltered | `SCREEN_1_0_LABEL.md` (label of record, files pinned by hash) | Done; future-banner wording still the proposal `proposals/DC_evidence_labels.patch` |
| E001–E015 multiple-testing policy | `MULTIPLE_TESTING_PRIOR_ETF.md` | Done; family table awaits review |
| Append-only annotations and tests | `proposals/` (D-A) | Proposed, **registry not modified** |
| Stage 2 free-data readiness plan | `STAGE2_FREE_DATA_READINESS.md` | Plan only, nothing built |
| Stage 4 8-K pre-registration | `STAGE4_8K_PREREG_DRAFT.md` | Draft, not registered, no outcome computed |
| Sharadar validation | `SHARADAR_VALIDATION_CHECKLIST.md` | Public pages only; 4 items open |

### Approvals needed before the next stage (none is given by this document)

| Id | Approval | Unblocks |
|---|---|---|
| U0 | Accept the Stage 1 close-out: the D-A ledger design and two events, the D-C banner wording, the D-B family table | Applying `proposals/` |
| U1 | Change the registry pin from whole-file to prefix (lines 1–252 stay byte-identical) | Any new trial registration (Stage 3, Stage 4) |
| U2 | Build Stage 2 §1–§3 as draft PRs (code and offline tests; no scheduled tasks) | Stage 2 |
| U3 | First bulk SEC header pull for the universe (≤ 5 req/s, from a session) | 8-K data set |
| U4 | ALFRED access route: free FRED API key (an account) or public pages only | Stage 2 §4 |
| U5 | Confirm the 8-K baselines use exploration + prospective only, not the one-ever holdout batch; approve the draft text for registration | Registering the 12 trials |
| U6 | Download Sharadar's public sample (free, no account) for comparison with SEC data | Checklist rows 4–6 |
| U7 | Read NYSE's published holiday and early-close notices to compile `research/calendars/nyse_sessions.csv` (a live read) | Price `available_at` (Stage 2 §2) |

### Owner decision 2026-10-23 12:06Z (`cmsg_01U4KMvkBYNknqm4HRVie8uvGZrinrG9nzsK8dtuPiDUzc`)

- **U0:** "Provisionally approved in principle". The direction for D-A, D-B and D-C is accepted, but nothing is
  applied until the exact diff, tests and before/after evidence have been reviewed. Historical results stay
  unchanged.
- **U2:** "Approved with limits". There are three separate draft PRs, built in this order:
  1. Stage 2 §3, research provenance;
  2. Stage 2 §1, SEC filings and the header cross-check tooling;
  3. Stage 2 §2, daily-price provenance and revisions.

  The work is code and offline tests on committed fixtures only, with:
  - no live requests, bulk pulls, vendor samples or accounts;
  - no scheduled-task, G1/G2, worker, gate or health change;
  - no registry-pin change, trial registration or event-study outcome;
  - no merge.
- **Five review points, resolved in the documents before implementing:**
  1. Eligibility is split into filing-time, execution and outcome stages (prereg §2).
  2. Close timestamps, early closes, and decision-time versus adjusted prices (Stage 2 §2; prereg §3–4).
  3. D-B rationale by family and for the other prior trials (`MULTIPLE_TESTING_PRIOR_ETF.md` §6).
  4. The SEC JSON time is kept verbatim, and the header is the *proposed* `available_at` source subject to the
     200-filing check (INTERFACES §1.2, Stage 2 §1, prereg §3).
  5. No guessed values; limitation blocks are required (Stage 2 §0, prereg §3 and §8).
- **Still unapproved:** U1, U3, U4, U5, U6, and U7, which is new.

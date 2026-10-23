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
| D-E | "YES, research only — prepare a vendor-source-verified data-purchase comparison. No purchase, subscription, account creation or paid API activation is authorised." | Read vendors' own public pages only | Not started in this pass. It is the next documentation task (`DATA_PURCHASE_COMPARISON.md`). It uses only public pricing and licence pages: no sign-ups, trials, API keys or contact forms. |

## D-D: order of work for the 8-K data set (plan, nothing registered)

1. Stage 2 builds `FilingEvent` ingestion from EDGAR (free; ≤10 requests a second with a declared User-Agent), with
   header-based `available_at` and a sampled check of the header against the JSON times across EST and EDT dates.
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

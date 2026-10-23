# Sharadar validation checklist (research only, owner decision D-E)

Owner task 2026-10-23 11:39Z (`cmsg_01U4KMvkBYNknqm4HRVie8uv464y4sReNiYrojmwW6sV3V`), item 4. "No account creation,
purchase, subscription or paid API activation." All facts come from Sharadar's public pages, read on 2026-10-23 with
no sign-in.
- [V] = stated on the cited page.
- [NS] = not stated there.
- **Open** = must be settled before any purchase case is written.

Licence summaries paraphrase the terms; they are not legal advice, and the vendor's text governs.

## Why Sharadar is on the list

Sharadar is the cheapest verified source covering both binding gaps at once: delisted US prices (N1) and
point-in-time fundamentals including delisted companies (N2). The Full History Bundle lists at $69 a month or $499 a
year (`DATA_PURCHASE_COMPARISON.md` §3). Nothing is bought.

## Checklist

| # | Question | What the public pages say | Status | How to close it without an account |
|---|---|---|---|---|
| 1 | **Historical coverage** | Fundamentals from January 1998, stock prices from December 1997, tickers from June 1990 [V: /sample]. "nearly 18,000 active and delisted US public companies", common stock on Nasdaq, NYSE, NYSEMKT; "99% survivorship-bias free" [V: /docs/fundamentals]. | Partly verified | Compare the published ticker-table row count for delisted names with EDGAR's full-index filer list for one year (e.g. 2008), using only the docs. The "99%" claim cannot be checked without data. |
| 2 | **US only?** | Exchanges listed are US only [V]. | Verified: no help with the ~40% of VWRP outside the US (Stage 2 §5.2) | — |
| 3 | **As-reported vs restated** | Dimensions: AR (ARQ/ARY/ART) "excludes restatements" and is "time-indexed to the date the form 10 regulatory filing was submitted to the SEC". MR (MRQ/MRY/MRT) "includes restatements" [V: /docs/fundamentals]. | Verified in docs | Use **AR only** for any point-in-time test. Open: whether AR values ever change after first publication (vendor corrections). |
| 4 | **Point-in-time availability** | "Point-in-time/As-Reported financials available via AR dimension" [V]. A `datekey` field exists, but how it is derived is [NS]. `lastupdated` = "last date on which a record was updated" [V]. | **Open** | Is `datekey` the SEC filing date, the acceptance time or Sharadar's load date? Check it on the sample against EDGAR acceptance times for 20 filings (row 6). Until then, `available_at` = `datekey` + 1 trading day, flagged `vendor_date`. |
| 5 | **Prices: adjustment and delisting** | Prices back to December 1997 [V]. The split/dividend adjustment method and the last price of delisted stocks are [NS] on the pages read. | **Open** | Read `/docs/stocks` and `/docs/bulk` (public). The delisting-return treatment decides whether the −30% missing-return rule is still needed. |
| 6 | **Sample-data access** | Sample = the 30 Dow stocks, last 5 years, 150+ indicators. Tables: Fundamentals, Prices, Corporate Actions, S&P 500 Constituents, Tickers, Daily Fundamentals, Indicator Descriptions. The links use a public placeholder `api_key=test-api-key`; the page does not say sign-up is needed [V: /sample]. AAPL sample "no sign-up required" [V: home page]. | Available without an account, **not downloaded** in this task | Needs a go-ahead (free, no account): download the sample once into `research-data/vendor-samples/sharadar/` with its hash, then compare with SEC companyfacts for the same companies. **Limitation:** the 30 Dow names are all survivors, so the sample cannot test delisted coverage (row 1). |
| 7 | **Cloud-processing rights** | Licence "granted solely to natural persons for personal use"; "not available to legal entities or institutions" [V: /terms §2–3]. Use on cloud servers or third-party services: [NS]. Use with AI/LLM tools: [NS]. | **Open: the key risk** | The owner's use is personal. Processing in cloud sessions run by an AI service is not addressed. Ask Sharadar by email only if the owner chooses to (it is the owner's contact, not a form filled in by us). |
| 8 | **Derived-data storage rights** | Derived works that cannot reproduce the data may be kept after termination; attribution is not needed for "research outputs, backtest results, models, summary statistics"; no sharing of "derivative data that allows reverse engineering" [V: /terms §4, §6, §10]. | Mostly verified | Store only raw vendor files (deleted on termination) and derived results (kept). Open: the `/mnt/project-files` folder counts as "computer systems you … operate"? Raw data must be deletable on termination within 30 days [V: §10]. |
| 9 | **Redistribution** | "You may not transfer or make available access to either the Services or the Service Data to others" [V: §4]. | Verified | Raw data never goes in the git repo (which is on GitHub). Only hashes and derived statistics are committed. |
| 10 | **Automated access** | API and bulk files exist; no rules on automated access in the terms [NS]. | Open, low risk | Read the `/docs/bulk` rate limits. |
| 11 | **Fit with the 8-K baselines** | Not needed: the 8-K baselines use free SEC data. Sharadar would mainly fix survivorship in prices (rows 1, 5). | — | — |

## Result

- **Verified:** history from 1998, delisted coverage claimed, as-reported (AR) versus restated (MR) separated,
  personal-use licence, derived results can be kept, no redistribution.
- **Open before any purchase case:**
  - how `datekey` is defined (row 4);
  - the delisting-return treatment in prices (row 5);
  - whether processing in cloud AI sessions is within personal use (row 7);
  - where raw data may be stored (row 8).
- **Next step that needs no account:** download the public sample (row 6) and compare it with SEC data. This is free
  and uses no account, but it was not done here. It needs the owner's go-ahead (U6).

Sources: https://www.sharadar.com/, https://sharadar.com/docs/fundamentals, https://sharadar.com/sample,
https://sharadar.com/terms (all read 2026-10-23). The Nasdaq Data Link SF1 documentation page rendered only its
title, so nothing was taken from it.

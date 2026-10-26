# U6: scope, provenance and licensing plan for the Sharadar public sample (plan only, nothing downloaded)

Owner decision record of 26 Oct 08:12Z, item 7 (U6): "Sharadar sample download not yet authorised; prepare the scope,
provenance and licensing plan first". This is that plan. Nothing has been downloaded, and no account, key, purchase or
subscription exists or is proposed. The facts come from `SHARADAR_VALIDATION_CHECKLIST.md` (vendor pages read
2026-10-23).

## 1. Scope

- **Data:** only the public sample on sharadar.com/sample: the 30 Dow stocks, last 5 years. The tables are
  Fundamentals (SF1), Prices (SEP), Corporate Actions, S&P 500 Constituents, Tickers, Daily Fundamentals and Indicator
  Descriptions. It is reached through the page's own public placeholder key `test-api-key`, so no sign-up is needed.
- **Requests:** at most one file per table (7), at least 5 s apart, no retries beyond one. A sign-in prompt, a
  CAPTCHA or any request for personal details ends the download.
- **Purpose:** answer the checklist's open rows that the sample can answer:
  - row 4: how `datekey` is defined, compared with SEC acceptance times for 20 filings;
  - row 5: the price adjustment method;
  - an AR-dimension spot-check: 10 company-quarters against SEC companyfacts.
- **Out of scope:** delisted coverage (all 30 names are survivors) and any backtest or outcome on the sample. The
  holdout years 2023-2026 in the sample are **not looked at** for any return or signal statistic; only field
  definitions and dates are compared.

## 2. Provenance

- Raw files go to `/mnt/project-files/research-data/vendor-samples/sharadar/raw/<sha256>`, never into git.
- A `manifest.json` beside them records, per file, the URL (with the placeholder key), HTTP status, `retrieved_at`,
  bytes, sha256 and the terms page's sha256 on that day.
- The comparison is done by a new offline script, `research/vendor_sample_check.py`, tested on synthetic fixtures
  first. It reads only the stored raw files and writes a report with counts and a per-field verdict. The report is
  committed; the raw data is not.

## 3. Licensing

- The sample is published for evaluation without sign-up. The terms (§2-3, §4, §6, §10) grant personal use to
  natural persons, forbid making the data available to others, and allow derived results that cannot reproduce the
  data to be kept.
- **Rules for this project:** no raw value is committed to GitHub; the report contains only definitions, match rates
  and dates. The raw folder is deletable at any time, and is deleted if the owner says so.
- **Open, decides any purchase:** whether processing in cloud AI sessions counts as personal use (checklist row 7).
  The sample download does not settle it and is not taken as permission for a purchase.

## 4. Acceptance

- 7 files or fewer stored, each with its hash in the manifest.
- The report answers rows 4 and 5 or says exactly why it cannot.
- The git diff contains no vendor data values.

# Stage 2 free-data readiness plan (plan only, nothing implemented)

Owner task 2026-10-23 11:39Z (`cmsg_01U4KMvkBYNknqm4HRVie8uv464y4sReNiYrojmwW6sV3V`), item 2. This is the plan for
Stage 2 using free sources only. **No code in it exists yet**, and none may be written until the owner approves
Stage 2 implementation (§7). Contracts are `INTERFACES.md` (contracts-0.1). [V] = checked in the repository or by
a request on 23 Oct; [A] = assumption to be checked when built.

## 0. Ground rules for every Stage 2 component

- **Offline tests only.** Every parser and checker is tested on fixtures committed under `tests/fixtures/`. No test
  makes a network request. Each live fetch is a separate CLI command, never run by a test or a scheduled task.
- **No scheduled-task change.** Stage 2 adds commands only. Wiring any of them into a routine is a later, separate
  owner decision. G1/G2 files, the office worker, gate and health code are not touched.
- **Raw bytes are kept.** Each fetch stores the response body unchanged, plus its SHA-256, URL and `retrieved_at`.
  Parsed records point to that raw file, so any parse can be re-run and checked.
- **Append-only.** A corrected value is a new record with `revision` and `supersedes` (INTERFACES §0.4). No file is
  rewritten.
- **Point-in-time reads use `available_at` only** (INTERFACES §0.2). `retrieved_at` is when we saw it, and is never
  used as the time the market knew it.
- **Research data stays outside the repo** in `/mnt/project-files/research-data/`, as `edge/manifest.json` does
  today [V]. The repo holds code, fixtures, manifests and hashes.

## 1. SEC submissions and 8-K ingestion (`FilingEvent`, owner decision D-D)

**What exists [V].**
- `equity/equity/sec.py` `SecClient`:
  - fetches `submissions` JSON with a declared User-Agent, at 0.2 s between requests (5 req/s, under SEC's 10);
  - retries 429/5xx.
- It caches by file modification time and **overwrites** the cache, so it keeps no retrieval history.
- Nothing reads `form`, `items`, `acceptanceDateTime` or the filing header today.

**The timestamp finding (INTERFACES C10).** For Apple 8-K `0000320193-26-000018`:
- the filing header has `<ACCEPTANCE-DATETIME>20260730163028`, which is Eastern time, i.e. 20:30:28Z;
- the submissions JSON has `2026-07-31T00:30:28.000Z`, which is 4 hours later.

So the JSON is not usable as UTC. This was checked on one filing only.

**Proposed files.**

| File | Purpose |
|---|---|
| `equity/equity/filings.py` | Builds `FilingEvent` records. It reads the submissions JSON `filings.recent` arrays plus the older `filings.files[]` pages for the filing list (accession, form, `items`, `filingDate`, `acceptanceDateTime` kept as `json_acceptance_raw`). For each 8-K or 8-K/A it then reads that filing's header (`<accession>.hdr.sgml` or the index header). It sets `available_at` from `ACCEPTANCE-DATETIME`, interpreted as America/New_York (`available_at_basis: "sec_header_acceptance_et"`, `source_tz: "America/New_York"`). |
| `equity/equity/sec.py` (small change) | Adds `get_raw(url)` returning bytes, status and `retrieved_at`, with no overwrite caching for event data. The existing JSON cache is unchanged for other callers. |
| `equity/equity/filings_store.py` | Append-only store. Raw bodies go in `research-data/sec/raw/<sha256>`, records in `research-data/sec/filing_events.jsonl`, both hash-chained via the INTERFACES envelope. |
| `equity/equity/filings_check.py` | Header-vs-JSON cross-check on a sample, plus the counts and gaps report. |
| `equity/tests/test_filings.py` | Offline tests (below). |
| `equity/tests/fixtures/sec/` | Real, small fixtures: two submissions JSON extracts and four headers. They are chosen in EST and EDT, with one 8-K/A, one multi-item 8-K and one filing accepted after 17:30 ET (which SEC dates the next business day). |

**Dependencies.** Standard library only (`zoneinfo` for America/New_York, `urllib`, `hashlib`). The owner-approved
SEC contact (`SEC_USER_AGENT` exported per command; the email is never written into repo files). No new package.

**Tests (offline).**
1. Header `ACCEPTANCE-DATETIME` → UTC is correct in both EST and EDT, and on the two DST-change days.
2. The JSON's `acceptanceDateTime` is kept verbatim and never used for `available_at`.
3. `items` "2.02,9.01" parses to `["2.02","9.01"]`. Empty or missing items give `[]` with a flag, never a guess.
4. 8-K/A is recorded with `amendment: true` and the accession of the original when the header names it.
5. Re-ingesting the same raw bytes writes nothing. Different bytes for the same accession write a revision event.
6. A filing whose header is missing is stored with `available_at: null` and excluded from point-in-time reads.
7. The rate limiter never issues two requests less than 0.1 s apart (fake clock).
8. No test opens a socket (a guard fixture patches `urllib` to raise).

**Data limitations.**
- **Size:** roughly 500 thousand to 1 million 8-Ks since 2004 at one header request each. Exploration needs only
  companies in the research universe, about 4,374 tickers [V: manifest], which is far fewer. Even so, at ≤ 5 req/s a
  full pull takes hours, and is split into resumable chunks.
- **Item codes:** the current numbering dates from **August 2004**. Earlier 8-Ks use the old scheme, so the event
  window starts after it.
- **Late filings:** filings accepted after 17:30 ET have the next business day's `filingDate`. `available_at` uses
  the acceptance time, not `filingDate`.
- **Unknown coverage of `items`:** whether older filings in the JSON `files[]` pages carry `items` is unknown [A]. A
  missing value means parsing the header's `ITEM INFORMATION` lines.
- **Survivorship:** EDGAR keeps filings of delisted companies, but our universe comes from today's ticker file
  (§5.1).

**Acceptance criteria.**
- All 8 tests pass offline.
- A sampled cross-check of ≥ 200 8-Ks (half EST, half EDT, across ≥ 10 years):
  - header-vs-JSON offset is reported;
  - every `available_at` is ≤ the filing's `filingDate` end-of-day ET + 1 business day;
  - 0 unexplained cases.
- The counts report shows events by year and item, the number with missing items and the number with missing
  headers.
- No outcome or price is joined at this stage (the pre-registration comes first, see
  `STAGE4_8K_PREREG_DRAFT.md`).

## 2. Price provenance and revision detection (`DataRecord` for prices)

**What exists [V].**
- `equity/equity/prices.py` stores one Yahoo close per listing per day in the `prices` ledger with a content `rid`,
  but no raw body hash and no `retrieved_at` distinct from the record time.
- `research/edge_exec_prices.py` builds month-end execution prices to 2022 with a manifest of file hashes
  (`research-data/edge/manifest.json`). It holds the first trading day after each month-end only, **not every
  trading day**.
- An 8-K event study needs daily closes for every event window. That is a new, larger file.

**Proposed files.**

| File | Purpose |
|---|---|
| `research/price_provenance.py` | `fetch_daily(symbol, start, end)` keeps the raw Yahoo chart body and its sha256, `retrieved_at`, the request URL and `period2`. It parses close and adjclose as `DataRecord`s with `available_at` = that session's 16:00 ET close (`available_at_basis: "exchange_close"`). |
| `research/price_revisions.py` | Compares a new pull with the stored one for the same symbol and dates. It emits a `revision` event per changed value, with old and new values, the size of the change and a class: `split_or_dividend_adjustment` (adjclose changes by one common factor from some date back), `unexplained`, or `new_row`/`dropped_row`. |
| `research/daily_prices_to_2022.py` | Builds `research-data/edge/daily_prices_to_2022.csv.gz` for the universe, cut at 2022-12-31 like the existing manifest (`period2 = 2023-01-01T00:00Z`). It adds it to `manifest.json` as a new file with its own hash and history entry; existing entries are not changed. |
| `research/tests/test_price_provenance.py` | Offline tests on chart-body fixtures. |

**Dependencies.** pandas, already used by research [V]. No new package.

**Tests (offline).**
1. Raw body hash and `retrieved_at` are recorded, and parsing a stored body twice gives identical records.
2. A pull whose adjclose differs by one constant factor before a date is classified as an adjustment, not
   `unexplained`.
3. A changed close with unchanged adjclose ratios is `unexplained` and is reported.
4. Nothing after the cut-off date can enter the `_to_2022` file (reuses `edge_exec_prices.assert_cut`).
5. Existing `manifest.json` entries and hashes are unchanged after adding the daily file.

**Data limitations.**
- Yahoo is unofficial, with no licence for redistribution (stated in `prices.py` [V]).
- It has **no prices for most delisted companies**: none above $1bn were priced in Stage 1 (survivorship, §5.1).
- adjclose is rewritten by Yahoo after every split or dividend, so "as first seen" adjusted prices cannot be
  recovered for the past. Only future pulls get revision history.
- It is not a point-in-time vendor record of what was known on the day.

**Acceptance criteria.**
- Tests pass offline.
- A re-pull of a 50-symbol sample one week apart shows every difference classified, with an `unexplained` count
  reported (not required to be 0, because Yahoo revises).
- The daily file's coverage of the universe (symbols and days) is reported, along with the share of events that
  have both entry and exit prices.

## 3. Research-run dependency versions and input hashes (`writer` and `run_manifest`)

**What exists [V].**
- The B5 run had a manifest with input SHA-256s (`edge_b5_manifest.py`, `edge_integrity.py`).
- `office/requirements-worker.txt` pins pytest 9.1.1 and statsmodels 0.15.0.
- No general run record captures the Python version, package versions or the git commit for every research run.

**Proposed files.**

| File | Purpose |
|---|---|
| `research/provenance.py` | `run_manifest(inputs: list[Path], params: dict) -> dict` returns: python version; versions of numpy, pandas, scipy and statsmodels (from `importlib.metadata`); `git rev-parse HEAD` and whether the tree is dirty; a sha256 per input file; the sha256 of the canonical params JSON; and UTC start and end times. `write(manifest, out_dir)` writes it next to the output. |
| `research/requirements-research.txt` | Pins the versions the suites ran with on 23 Oct (to be read from the venv at build time). It sits beside, and does not edit, `office/requirements-worker.txt`. |
| `research/tests/test_provenance.py` | Offline tests. |

**Tests.**
1. The same inputs and params give the same manifest, apart from the times.
2. Changing one input byte changes that file's hash and nothing else.
3. A dirty tree is recorded as `dirty: true` and is never hidden.
4. A missing package is recorded as `null`, not as an error.

**Limitations.**
- This records the environment; it does not reproduce it.
- OS-level libraries (BLAS) are not captured.

**Acceptance criteria.**
- Tests pass.
- A dry run on an existing exploration script (with no outcome computation, e.g. a data-coverage report) writes a
  manifest whose hashes match `manifest.json` for the shared files.

## 4. ALFRED point-in-time macro data

**What exists [V].**
- `research/data_sources.py` `fred(series)` reads current FRED values only. Current values include later revisions,
  so they are not point-in-time.
- The exec-price build saw FRED refuse connections on 15 Oct ("Remote end closed connection").
- The ALFRED home page returned 200 on 23 Oct.

**Access question (needs the owner).** The supported route to vintages is the FRED/ALFRED API with
`realtime_start` / `realtime_end` or `vintage_dates`. It **requires a free API key, which means creating an account**.
That is outside the current authorisation. The alternative is ALFRED's public download pages without a key; whether
they give machine-readable vintage files from this container is unverified [A]. Nothing is fetched until the owner
chooses (§7, U4).

**Proposed files.**

| File | Purpose |
|---|---|
| `research/alfred.py` | `vintages(series, start, end)` returns one `DataRecord` per (observation date, vintage date). The value's `available_at` is the vintage date at 08:30 ET for BLS/BEA releases, or the release time when ALFRED gives it (`available_at_basis` records which). `as_of(series, t)` returns the latest vintage with `available_at ≤ t`. |
| `research/tests/test_alfred.py` | Offline tests on fixtures. |
| `research/tests/fixtures/alfred/` | Hand-written fixtures in ALFRED's documented format: one series (e.g. PAYEMS) with three vintages, one revised observation and one benchmark revision. They are labelled as synthetic until replaced with a real download. |

**Tests.**
1. `as_of` never returns a vintage published after `t`.
2. A revised observation keeps both values, linked by `supersedes`.
3. An observation first published after `t` is absent at `t`.
4. Parsing gives identical records twice.

**Limitations.**
- Vintage release times are dates, not timestamps, for many series, so a conservative release time is assumed.
- ALFRED covers US series. UK and global macro point-in-time data have no verified free source.
- Macro data is not used by any planned baseline yet. It is plumbing for Stage 3 regime trials.

**Acceptance criteria.**
- Tests pass offline on the fixtures.
- After the owner chooses an access route, a real two-series download replaces the synthetic fixtures, and
  `as_of` is checked on five known revision dates.

## 5. Unresolved gaps

### 5.1 Survivorship bias (binding)
- **Prices:** Yahoo has no prices for most delisted companies.
- **Universe:** today's SEC ticker file lists current registrants.
- **8-K study:** an 8-K study over 2004–2022 built this way **systematically drops companies that later failed**.
  Bad-news 8-Ks (bankruptcy item 1.03, delisting item 3.01) are the most affected. The first baseline therefore
  excludes items 1.03 and 3.01, and reports the survivorship caveat on every number (pre-registration §2).
- **Free mitigations:**
  - EDGAR's quarterly `full-index` lists every filer, including delisted ones, so the *event* list can be complete
    even where prices are not;
  - report how many events have no price, by year and item.
- **Full fix:** a paid source of delisted prices (`DATA_PURCHASE_COMPARISON.md`; Sharadar checklist in
  `SHARADAR_VALIDATION_CHECKLIST.md`). No purchase is authorised.

### 5.2 Global-market coverage
- VWRP is about 60% US, so about 40% is outside the US.
- SEC 8-Ks cover US filers only (plus some foreign private issuers on 6-K, which is not in scope).
- UK RNS announcements and other markets have no verified free, timestamped, bulk source.
- Any 8-K-based tactical sleeve is therefore **US-only**, and its benchmark and overlap checks must say so.

### 5.3 Other gaps
- **No news text:** GDELT gives metadata and tone, not text. Paid news is not authorised.
- **No consensus estimates:** S8 stays untestable.
- **Yahoo licence:** fine for personal research; not redistributable. Raw bodies stay in the project folder.
- **Corporate actions and ticker changes:** CIK is the stable key. Ticker-to-CIK history before today's file is
  incomplete.
- **Registry pin:** new trial registrations are blocked by the whole-file pin on `trials.jsonl` (decision U1, §7).

## 6. Order of build (after approval)

1. §3 provenance (smallest; used by everything else).
2. §1 SEC filings (D-D's data set), with the cross-check report.
3. §2 daily prices and revisions.
4. §4 ALFRED, after the access decision.

Each step is its own draft PR with offline tests and no scheduled-task change. No outcome is joined to an event
until the 8-K pre-registration is registered.

## 7. Approvals needed (see the summary in the report)

- **U1 Registry pin.** Change `HISTORICAL_SHA256` from a whole-file pin to a prefix pin (the first 252 lines
  stay byte-identical), so new registrations can be appended. Without it no Stage 3 or 4 trial can be registered.
- **U2 Stage 2 implementation.** Approval to build §1–§3 as draft PRs (code and offline tests only, no scheduled
  tasks, no live fetch beyond small fixtures).
- **U3 First live pull.** A separate approval for the first bulk SEC pull: about one header per 8-K for the
  universe, at ≤ 5 req/s, from a session, not a routine.
- **U4 ALFRED access.** Either a free FRED API key (needs an account, so it is the owner's decision) or public
  pages only, accepting that they may not work.

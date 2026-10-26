# U4: read-only plan for ALFRED vintage macro data (plan only, nothing fetched)

Owner decision record of 26 Oct 08:12Z, item 7 (U4): "public ALFRED access not yet authorised; prepare the read-only
plan first". This is that plan. No request has been made to ALFRED or FRED, and no API key or account exists.

## 1. Why

`research/data_sources.py` `fred()` reads current FRED values, which include every later revision, so they are not
point-in-time. ALFRED keeps each series' vintages (the values as first published and as revised). Stage 3 regime
trials need as-published macro data; nothing in Stage 2 depends on it (STAGE2_FREE_DATA_READINESS §4).

## 2. Access route

| Route | Account | Machine-readable vintages | Recommendation |
|---|---|---|---|
| FRED/ALFRED API (`fred/series/observations` with `realtime_start`/`realtime_end` or `vintage_dates`) | Needs a free API key, so an account | Yes, documented | Not used: an account is a new external permission, which the owner's permanent rules exclude. |
| ALFRED public pages and their download links (no key) | None | Unverified from this container | **Use this route**, after the one-off probe in §3 shows it works. |

## 3. The first live step: one probe

- **What:** one GET of one series' ALFRED download page and file, for a single series (PAYEMS, US non-farm payrolls),
  with a User-Agent naming the project. At most 3 requests, at least 5 s apart. No retries beyond that.
- **Stored:** the raw bytes under `/mnt/project-files/research-data/alfred/raw/<sha256>`, with URL, HTTP status,
  `retrieved_at` and sha256 in `/mnt/project-files/research-data/alfred/manifest.json`. Nothing goes into git except
  hashes and derived statistics.
- **Stop:** any non-200 status, a page that needs a sign-in, a CAPTCHA, or terms that forbid automated download. Each
  of these ends the probe and is reported. Nothing is worked around.
- **Licence check before any bulk use:** FRED's terms allow use with attribution, but some series carry third-party
  copyright (noted per series). Only series whose ALFRED page shows no third-party restriction are used.

## 4. Code (offline first, as for Stage 2 §1-3)

| File | Purpose |
|---|---|
| `research/alfred.py` | `parse_vintages(raw)` returns one `DataRecord` per (observation date, vintage date). `as_of(records, t)` returns the latest vintage with `available_at <= t`. `available_at` is the vintage date at a conservative release time (08:30 ET for BLS/BEA releases), with `available_at_basis` recording that it is assumed. |
| `research/tests/test_alfred.py` | Offline tests on synthetic fixtures in the documented shape: as-of never returns a later vintage; a revision keeps both values linked by `supersedes`; an observation first published after `t` is absent; identical bytes parse identically; any network attempt raises. |
| `research/tests/fixtures/alfred/` | Hand-written, labelled synthetic, until replaced by the probe's real file. |

## 5. Acceptance

- The parser handles the probe's real file, and both parse runs are identical.
- `as_of` reproduces three hand-checked first-published PAYEMS values.
- The manifest records every byte fetched. No write outside `/mnt/project-files/research-data/alfred/`.

## 6. Limits

- Many vintages carry a date, not a time, so the release time is assumed and flagged.
- ALFRED is US-only. UK and global as-published macro data have no verified free source.

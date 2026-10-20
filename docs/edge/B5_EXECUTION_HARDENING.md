# B5 execution hardening and P7 evaluation-window review (proposal)

This document responds to the owner's decision of 2026-10-19 12:15Z, which approved work on execution-control
hardening and the P7 window review only.

Nothing here is registered or executed:

- MANIFEST-3 stays proposed and unregistered.
- Run 1's lock stays in place.
- No authorisation is written.
- No scoring data is read.
- No trial runs.
- The registry, `status.json` and the lock are byte-identical to their state after run 1.

## 1. Execution hardening (code: `research/edge_registry.py`, `research/edge_b5_run.py`)

**Before.** The gate, `edge_registry.b5_run_open`, opened when `status.json` said `authorised: true` with a `cmsg_`
id and a lock named the same id. After run 1 both were still true. The gate therefore read as open. Only
`preflight` (run by `main`) stopped a new start, because the lock existed. A direct call to `load_inputs`,
`run_one` or `finish` was not refused.

**After.** The gate opens only when all of the following hold.

1. **Authorisation** (`b5_authorisation`):
   - `authorised` is `true` and the owner message is a `cmsg_` id;
   - that id is not in `B5_SPENT_AUTHORISATIONS`, a frozen list in code that holds run 1's D26 id
     `cmsg_…4iY3kK`;
   - the authorisation names the current manifest by id (`manifest_id` = `B5-V3-RUN-MANIFEST-3`) and by
     `manifest_sha256`.

   An approval given for one manifest can never authorise a run of other code or inputs. D26 can never authorise
   anything again, whatever `status.json` says.
2. **Lock:** it exists and names the same owner message and the same manifest sha256.
3. **Manifest** (`b5_manifest_ok`):
   - the manifest file has that sha256;
   - the real registry registers `B5-V3-RUN-MANIFEST-3` at that sha256;
   - in the entry points that touch data or results (`load_inputs`, `run_one`, `finish`; `verify_files=True`),
     every input and code file the manifest lists is re-hashed and must match.

The gate reads only module paths (status, lock, registry, manifest, repository root), never arguments.

**Coverage of each entry point:**

- `preflight` runs the same authorisation check and also requires `manifest_sha256` to equal the manifest file's.
  It refuses before taking the lock.
- `edge_registry.require`, called by every `bt.run_trial` and `bt.record`, runs the gate without re-hashing the
  listed files, because it runs once per backtest. The run's own entry points re-hash them.

**State now:** in the real repository the gate is **closed**. It refuses at the first check because D26 is spent,
before the lock, the registry or any listed file is read.

## 2. Run 1 lock: proposed archival and reset procedure (NOT executed)

Run 2 cannot start while `research/edge/b5_run.lock` exists, because preflight's `O_CREAT|O_EXCL` refuses. The
lock is run 1's incident artefact:

- sha256 `c06eeaa3a6020adc…`;
- names D26 and MANIFEST-2;
- committed in 4215a98.

Proposed steps, each only on the owner's recorded decision. The decision can cover all steps or each separately.

1. **Record the decision** as a DECISIONS row citing the owner's message id.
2. **Archive the lock unchanged:** `git mv research/edge/b5_run.lock docs/edge/incidents/B5_RUN_1_LOCK.json`, then
   verify the sha256 is still `c06eeaa3…`. Add a line to `B5_RUN_1_INCIDENT.md` naming the new path.
3. **Reset the authorisation:** set `status.json` `b5_trial_run` to
   `{"authorised": false, "history": [{"run": 1, "owner_message": "<D26 id>", "decision": "D26", "outcome": "stopped with an error, nothing recorded (D27)", "lock": "docs/edge/incidents/B5_RUN_1_LOCK.json", "lock_sha256": "c06eeaa3…"}]}`.
   D26 also stays permanently in `B5_SPENT_AUTHORISATIONS`.
4. **Verify (read-only) and commit:**
   - the registry is byte-identical (sha `b027de18…`, N = 102, no B5 result);
   - the gate and preflight refuse ("not authorised");
   - the real-state tests are updated to the new state.
5. **Separate later approvals, not part of this procedure:**
   - register MANIFEST-3;
   - write a new authorisation with a new owner message, `manifest_id` and `manifest_sha256`;
   - preflight then takes a fresh lock for run 2.

Nothing is deleted at any step: the lock file, its history and the D26 record are all kept.

## 3. P7's evaluation window: why 94 dates, and options

### Why

- **Primary and the other variants:** the next-day-close convention trades the decision at month-end *m* on the
  first trading day after it. Decisions run from 2015-01 to 2022-11, so the trade dates run from 2015-02-02 to
  2022-12-01. That gives 95 valuation dates and 94 monthly returns.
- **P7:** the next-month-close convention trades the decision at month-end *m* at the close of month-end *m + 1*.
  It takes that close from the B1 file's `me_adjclose` for month *m + 1* (`edge_backtest.price_table`).
- **The cause:** the B1 file (`exec_prices_to_2022.csv.gz`, built by `edge_exec_prices.py`) has one row per
  decision month from 2009-12 to 2022-11. It stops at 2022-11 because a 2022-12 decision would need a January 2023
  next-day execution, which the strict cutoff forbids.
- **What that leaves:** there is no 2022-12 row, so there is no 2022-12-30 close. The 2022-11 decision cannot trade
  under P7, and P7's last trade is the 2022-10 decision's, on 2022-11-30.
- **P7's window:** its first trade is the 2015-01 decision's, at the 2015-02 month-end. It has 94 valuation dates
  (2015-02-28 to 2022-11-30) and 93 monthly returns.
- **Status of this behaviour:** it predates Fix 2 and is not a cutoff requirement. The missing close, 2022-12-30,
  falls *inside* the exploration window. The data file was simply built per next-day decision.

### Can the 2022-12-30 close be obtained reliably?

**Same source (Yahoo), technically yes.**

- B1's requests already ended at 2023-01-01 00:00 UTC, so the 2022-12-30 bars were downloaded but not kept. No raw
  daily cache exists.
- Yahoo answered from this container (HTTP 429, rate-limited). I checked reachability only; no price was fetched.

Problems:

- **Not independent.** It is the same vendor as B1.
- **Adjustment vintage.** Yahoo's `adjclose` is re-scaled for every corporate action known on the download date.
  A December close fetched now and set beside B1's 2022-11-30 close (downloaded 2026-10-15) mixes two vintages. Any
  dividend or split since then makes the one-month return wrong. A safe build would re-download each name's series
  and splice by its own 2022-11-30 ratio, with a check that the overlap reproduces B1's earlier ratios.
- **Coverage.** Names delisted since B1 may no longer return data. That adds a new survivorship gap in exactly the
  month being added.

**Independent second source: not available here without an owner decision.**

- Stooq is unreachable from this container.
- Alpha Vantage and Nasdaq Data Link answer but need API keys (credentials).
- Norgate and EODHD are paid and were declined earlier.

**Code and governance cost.**

- `price_table` refuses any row whose `exec_date` is after the cutoff, so a 2022-12 row needs either a new
  `me_only` row type or a separate file.
- That is a change to the backtester and to a registered input. It needs a new B1 integrity audit, a new manifest,
  a written addendum and owner approval, and it reopens B4's `backtester_validated` acceptance for that input.

### Options (none selected; each needs the owner's choice)

| Option | What it means | Effect on registered methodology | Approvals needed |
|---|---|---|---|
| **A. Keep and disclose** | P7 runs as registered over 2015-02-28 to 2022-11-30 (93 monthly returns). The report states the window next to P7's result. | None. P7's gate is P7's own net excess (mean monthly excess over the benchmark on P7's own dates) > 0, not a difference from the primary, so an identical window is not needed for the comparison to be fair. | Owner acknowledgement of the disclosure text. |
| **B. Add the 2022-12-30 close from Yahoo** | Re-download, splice to B1's vintage, audit, and add a `me_only` 2022-12 row. P7 then has 94 returns. | Changes a registered input and the backtester's price table. The same-vendor limitation remains. | Addendum, new B1 audit, new manifest, owner approval. |
| **C. B plus an independent cross-check** | As B, with each close verified against a second vendor. | As B. | As B, plus credentials (an API key) or a paid source. |
| **D. Common-window comparison** | Also evaluate the primary over P7's dates, or P7 over the primary's. | Changes how a gate is defined. Pre-registered gates may not change after registration without a new version, which means new trial ids and a higher N. | New version and registrations; not a bug fix. |

My recommendation is **A**. It needs no change to a registered input or definition. The one-month difference
affects a veto-only robustness check that is computed on P7's own dates. B and C add a new data source and code into
a validated pipeline to gain one month.

The choice is the owner's. No option has been applied.

## 4. Unchanged

These limitations still apply:

- Survivorship bias is material and unbounded.
- TTM check 4 is open, and the E2 label is withheld.
- There is no holdout access, no confirmation testing, no PR #19 merge and no account change.

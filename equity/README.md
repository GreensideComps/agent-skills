# equity: company research database (Milestones 1 and 2)

This is the foundation of the stock-discovery and screening system: a security master for every stock tradable on
Trading 212, fundamentals extracted from SEC filings with provenance on every number, an auditable pipeline of
company statuses, and a job ledger. It is separate from the demo trading bot in `../trading`, and only
`sync-universe` touches the broker, read-only, through the bot's `ReadOnlyClient`.

System-wide audit and roadmap: [`../docs/AUDIT_AND_PLAN.md`](../docs/AUDIT_AND_PLAN.md).

## Commands (run from `equity/`)

```bash
export SEC_USER_AGENT="my-research-app me@example.com"   # SEC requires a contact email
python3 -m pytest -q                                     # 60 offline tests
python3 -m equity sync-universe                          # T212 instruments + SEC ticker map -> security master
python3 -m equity ingest --symbol AAPL --symbol KO       # fundamentals snapshot(s) from SEC XBRL
python3 -m equity ingest --all-sec --random 40 --seed 1  # random sample of SEC-linked companies
python3 -m equity show NVDA --provenance                 # metrics + concept, accession and filing date per value
python3 -m equity search --min-roic 0.2 --min-fcf-margin 0.1 --supported-only
python3 -m equity coverage --method fund-2.0 --json reports/coverage.json  # confidence by taxonomy/industry, top gaps
python3 -m equity discover TICKER --source S --reason R --evidence URL
python3 -m equity status TICKER --to research_queue --reason R --evidence E
python3 -m equity crosscheck --symbol AAPL ...           # independent check vs Yahoo -> reports/verification/
python3 -m equity health                                 # last ok/failed run per job, stuck jobs, coverage
```

## Design

| Concern | How it is handled |
|---|---|
| Durable state in ephemeral containers | Append-only JSONL ledgers in `data/`, committed to git. `merge=union` in `.gitattributes` lets concurrent scheduled sessions append without merge conflicts. The SQLite index in `cache/` is rebuilt from the ledgers on demand. |
| Idempotency | Every record has a deterministic `rid`; appending an existing `rid` is a no-op. Jobs take an idempotency key (`ingest:<company>:<date>`); a completed key is skipped, a failed one is retried. |
| Identifiers | Listing = T212 ticker id (survives renames). Security = ISIN (one ISIN can have several listings). Company = `SEC:<cik>` for SEC filers, else `ISIN:<isin>`. Symbols come from `shortName` because T212 ticker ids go stale after renames. |
| History | Security changes, removals and reappearances are new versions. Fundamentals snapshots are written only when the filed data or method version changes, and each links to its predecessor. Status transitions are never edited. |
| Provenance | Each value records its XBRL concept, unit, accession number, form and filing date, plus the *first-filed* value (`orig`, point-in-time) next to the *latest* (`v`, includes restatements). Derived metrics carry the formula text (`methods`). Calculated substitutes (implied shares, operating-income proxy) are labelled. |
| Taxonomy and currency (M2) | Each company is read in `us-gaap` or `ifrs-full`, whichever has the most recent annual revenue, OCF or net income (companies switch). All money values come from one reporting currency, the one most annual facts use; others (e.g. a USD convenience translation next to TWD) are ignored and flagged `ignored_currencies`, never mixed. |
| Industry templates (M2) | SIC from SEC's submissions API maps to `industrial`, `bank`, `insurer`, `financial_other`, `reit` or `spac` (`industry.py`). Outside `industrial`, metrics that mean nothing for that business (FCF, ROIC, net debt, margins) are blanked from the summary and flagged `not_meaningful`; inputs the template does not need (a bank's capex) don't lower confidence. Those companies are `screen_supported: false` and the `candidate` gate refuses them. |
| Snapshot size (M2) | Values are packed losslessly (filings, concepts and units stored once; first-filed value only when it differs), formulas live once per method version in `methods.jsonl`, derived metrics are rounded to 6 significant figures. On the 54 stored M1 snapshots this is 36 KB → 13 KB each (round trip exact). Readers always unpack through `ingest.last_snapshot`. |
| Share splits | Filings are chained through the periods they both report, which gives every filing a cumulative multiplier to the current share basis. Splits are adjusted (`split_adj`, `v_as_filed`) and are not counted as restatements. |
| Data quality | Flags for missing inputs, stale annual data (>15 months), short history, restatements, concept switches, mixed currencies, unlinked split basis. Confidence is `high`/`medium`/`low`; missing revenue, OCF, capex or shares, or stale data, means `low`. |
| Gates | The pipeline refuses transitions without a reason and evidence, and paths that aren't allowed. `candidate` additionally requires a recorded bear case, data confidence that is not `low`, and a classified, supported industry template (snapshots from before M2 are unclassified until re-ingested). The bear-case record arrives in M4, so nothing can reach `candidate` yet. |
| Secrets | Job errors are redacted for the T212 and Resend secrets. The SEC contact comes from the environment, never from code. |

Pipeline statuses: `discovered → research_queue → qualified → watchlist → candidate`, with `rejected` and
`thesis_broken` reachable from the later stages. `rejected → research_queue` is allowed for reconsideration after a
material change.

## Known limitations (measured, not assumed)

- Fundamentals: **SEC filers only** (5,472 of 10,897 companies have a verified SEC link). Since M2 this includes IFRS
  20-F/40-F filers (e.g. TSMC, Novo Nordisk) when T212 lists their US line; issuers with no SEC filing still have no
  fundamentals source.
- Annual data only; no quarterly YoY/QoQ yet.
- Company-specific XBRL extension tags are not in SEC's companyfacts API, so some values are genuinely unavailable (e.g. NVIDIA capex before FY2022).
- Banks, insurers, other financials, REITs and SPACs are classified and excluded from screening rather than scored;
  their own metrics (ROE, combined ratio, FFO) are not built yet.
- IFRS has no standard short-term investments line, so `net_debt` for IFRS filers subtracts cash only.
- Debt excludes operating leases; it includes finance leases where the filer tags debt and leases together (e.g. Coca-Cola).
- Full-universe snapshots at ~13 KB each are ~70 MB of ledger, written only when filings change. Fine for git for
  now; a move to compressed ledgers would be the next step if it grows.
- The security master contains only stocks tradable on Trading 212, not the whole global market.

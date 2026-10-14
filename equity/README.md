# equity: company research database and stock screener (Milestones 1-5)

This is the foundation of the stock-discovery and screening system: a security master for every stock tradable on
Trading 212, fundamentals extracted from SEC filings with provenance on every number, an auditable pipeline of
company statuses, and a job ledger. It is separate from the demo trading bot in `../trading`, and only
`sync-universe` touches the broker, read-only, through the bot's `ReadOnlyClient`.

System-wide audit and roadmap: [`../docs/AUDIT_AND_PLAN.md`](../docs/AUDIT_AND_PLAN.md).

## Commands (run from `equity/`)

```bash
export SEC_USER_AGENT="my-research-app me@example.com"   # SEC requires a contact email
python3 -m pytest -q                                     # 97 offline tests
python3 -m equity sync-universe                          # T212 instruments + SEC ticker map -> security master
python3 -m equity ingest --symbol AAPL --symbol KO       # fundamentals snapshot(s) from SEC XBRL
python3 -m equity ingest --all-sec --random 40 --seed 1  # random sample of SEC-linked companies
python3 -m equity show NVDA --provenance                 # metrics + concept, accession and filing date per value
python3 -m equity search --min-roic 0.2 --min-fcf-margin 0.1 --supported-only
python3 -m equity coverage --method fund-2.2 --json reports/coverage.json  # confidence by taxonomy/industry, top gaps
python3 -m equity prices                                 # latest close for every ingested company (Yahoo, US lines)
python3 -m equity screen                                 # Master Stock Screener -> reports/screens/<date>.md
python3 -m equity explain ADBE                           # every sub-score, gate and input behind one result
python3 -m equity valuate RL                             # multiples, bear/base/bull DCF, growth the price implies
python3 -m equity thesis RL --actor A --summary S --point P --evidence ACCN   # one --evidence per --point
python3 -m equity bearcase RL --actor B --objection O --evidence E --watch W  # >= 3 triples, B != thesis author
python3 -m equity alerts                                 # changes between screen runs
python3 -m equity paper                                  # paper portfolio: monthly rebalance if due, mark vs SPY
python3 -m equity discover TICKER --source S --reason R --evidence URL
python3 -m equity status TICKER --to research_queue --reason R --evidence E
python3 -m equity crosscheck --symbol AAPL ...           # independent check vs Yahoo -> reports/verification/
python3 -m equity health                                 # last ok/failed run per job, stuck jobs, coverage
python3 -m equity ingest --all-sec --new-only --limit 200  # grow the universe: companies with no snapshot yet
python3 -m equity ingest --all-sec --refresh 300         # re-check the 300 oldest snapshots (over 7 days old)
python3 -m equity reliability                            # missed runs, stuck jobs, stale data -> reports/health/
bash daily_run.sh                                        # the whole daily pipeline, then commit + push (needs SEC_USER_AGENT)
```

Scheduling: the "Equity: daily research pipeline" routine runs `daily_run.sh` on weekdays at 22:27 London.
`config/schedule.json` lists every scheduled run (the T212 demo bot's routines included) and the evidence that
proves it ran: a commit with a given prefix on a branch, or an ok job in `data/jobs.jsonl`. `reliability`
compares the two; it never trusts that a schedule exists.

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
| Screener (M3) | `screener.py` + `config/screener.json`. Five scores on absolute 0-100 scales with your baseline weights: FCF per share 30 (5-year FCF/share CAGR, years of positive FCF), quality 25 (ROIC, FCF margin, gross margin, cash conversion, SBC), growth 20 (revenue and EPS CAGR), valuation 20 (FCF yield, EBIT/EV), risk fit 5 (net debt/EBITDA, goodwill share of assets). Data confidence is reported, not blended. Gates (industry, confidence, latest FCF > 0, FCF consistency, leverage, interest cover, dilution, valuation available) are each pass/fail/unknown with the number decided on; only companies with no failed gate and no unknown critical gate are ranked. A missing metric re-weights its component; under 50% coverage the component and total are left empty. Changing weights, scales or gates bumps `method_version` and needs your approval. |
| Prices and market cap (M3) | Yahoo's chart endpoint (free, unofficial, delayed), one record per listing per day in `prices.jsonl`. Market cap = price × cover-page shares outstanding (summed over classes), else latest diluted weighted shares as a labelled proxy. 20-F/40-F filers' US lines are usually ADRs with an unknown ratio, so their valuation is reported unavailable rather than guessed. |
| Valuation (M4) | `valuation.py` (`val-1.0`): base FCF = 3-year mean; 5 years at a scenario rate, fade to 2.5% over 5 more, 9% discount; bear/base/bull rates derived mechanically from the company's own history with caps; a reverse DCF gives the 5-year FCF growth the current EV implies. Every record stores its assumptions, snapshot and price ids. `screen` runs it for every company with a market value. |
| Research records and alerts (M4) | `research.py`: theses and bear cases, append-only. A bear case needs >= 3 objections, each with evidence and a `watch` (what would confirm it), from someone other than the thesis author, and goes stale when a newer annual filing arrives. `status --to candidate` now checks it. `alerts.py`: alerts only on changes between runs (entered/left ranking, score move >= 10, a company with a bear case dropping out), keyed by date so repeats are impossible. |
| Paper portfolio (M5) | `paper.py` + `config/paper_portfolio.json` (`paper-1.0`): 10,000 USD notional, top 10 ranked with total >= 60, equal weight, monthly rebalance, 25 bps per trade (spread + T212 FX fee), SPY buy-and-hold benchmark with the same cash and costs. Recommendations are logged with the decision price, rank, scores and implied growth before any outcome exists (`recommendations.jsonl`); fills only use the logged price; every price is checked before anything is written. Dividends are excluded from both books. No broker is touched. |
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
- Screener: valuation covers US-listed domestic filers only (ADR ratios unknown); the screen runs only over companies
  already ingested (128 on 2026-10-14), not yet the whole SEC universe; prices are Yahoo's, unofficial and delayed.

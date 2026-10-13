# t212bot: Trading 212 Practice-account trading bot

An automated, demo-only trading system that runs the strategy selected in
[`../research/REPORT.md`](../research/REPORT.md). It journals every decision
and fill, tracks itself against shadow portfolios, and is operated by
scheduled cloud routines (see [`RUNBOOK.md`](RUNBOOK.md)).

**Live status:** see [`PERFORMANCE.md`](PERFORMANCE.md) (regenerated on every run), the daily reports in [`reports/daily/`](reports/daily/), and [`STATUS.md`](STATUS.md) for what is and isn't operational.
**Daily intelligence report, email and withdrawal adviser:** see [`REPORTING.md`](REPORTING.md).

## What it trades now

| | |
|---|---|
| Strategy | `momentum_tilt_v1`: 50% `VWRPl_EQ` (FTSE All-World) + 50% `IWMOl_EQ` (MSCI World Momentum) |
| Why | The only premium in the research with 100 years of survivorship-free evidence, post-publication persistence in developed markets (t=2.1, 2011–2026) and a positive tradeable out-of-sample result (+2.6%/yr vs MSCI World, p=0.09). The 50/50 split keeps a world-index core against momentum crashes. |
| Rebalancing | Checked every weekday. Trades only when a holding drifts beyond ±5 percentage points, uninvested cash exceeds 3%, or once a year in January |
| Benchmarks (shadow) | A = 100% VWRP; C = GEM-12 dual momentum; B-at-close = same rules at daily closes, which isolates execution cost |

## Safety design

| Risk | Control |
|---|---|
| Touching real money | The only reachable host is `demo.trading212.com`, hard-coded. `T212_ENV` must equal `demo`. The live URL does not appear anywhere in the package (enforced by a test). |
| Duplicate orders (API is not idempotent) | Order POSTs are never retried after a timeout, 5xx or network error. The bot reconciles against pending orders and history, journals the result and stops. Only HTTP 429 (rejected before processing) and validation 400s are retried. |
| Runaway trading | Long-only and no leverage (config validation). At most 10 orders per run. No trading while any order is pending. Trades below £1 are skipped. |
| Bad prices | Quotes must be under 1 hour old when trading, and within 3% of Trading 212's own `currentPrice` for held positions. The quote's currency must match the instrument's. |
| Thin markets | Trades only inside the instrument's T212 working schedule, excluding the first and last 15 minutes |
| Selling what isn't there | Sells are capped at `quantityAvailableForTrading` |
| Cash overdraw | Planner budgets the 0.15% FX fee and a 1.5% buffer. Each buy is re-sized against fresh cash, using a learned estimate of Trading 212's undocumented market-buy cash hold. |
| Rate limits | Official per-endpoint limits from the OpenAPI spec, enforced client-side. 429s wait for `x-ratelimit-reset`. |
| Secrets | Credentials come only from the environment and never appear in logs, reprs or exceptions (tested). A pre-commit check greps staged diffs for them. |
| Emergency stop | Create `trading/KILL` or set `T212BOT_KILL=1`. The bot still snapshots and reconciles, but places nothing. |

## Things learned from the live demo (not in the official docs)

1. **Market buys need about 5–9% cash headroom.** With £50.70 free, buys of £49.17 and £48.67 were rejected (`insufficient-free-for-stocks-buy`) and £46.71 was accepted. The bot learns the bounds by bisection and stores them in `journal/state.json` → `buy_reserve`.
2. USD instruments can be bought from the GBP account with market orders. The FX fee appears as `CURRENCY_CONVERSION_FEE` in `fill.walletImpact.taxes` (£0.07 on £49.23 = 0.14%).
3. 4-decimal fractional quantities are accepted for `VWRPl_EQ` and `IWMOl_EQ`. If a quantity is rejected for precision, the bot steps down a decimal place and records what worked.
4. Fills landed 4–12 bps above Yahoo's roughly 15-minute-delayed reference quote.

## Usage

```bash
cd trading
python3 -m pytest -q                       # 113 tests, offline (fake T212 server, fake email provider)
python3 -m t212bot status                  # account + dry-run plan, no orders
python3 -m t212bot run                     # snapshot, reconcile, plan (dry run)
python3 -m t212bot run --execute           # ...and trade if a rebalance is due
python3 -m t212bot run --execute --force   # rebalance to target now
python3 -m t212bot reconcile               # match orders to fills
python3 -m t212bot report                  # regenerate PERFORMANCE.md
python3 -m t212bot daily-report [--send]   # daily intelligence report (read-only), optional email
python3 -m t212bot daily-report --sample   # EXAMPLE-DATA sample report
python3 -m t212bot advise                  # withdrawal recommendation (never acts)
python3 -m t212bot email-check             # email configuration check
python3 -m t212bot email-status            # latest delivery, re-checked with the provider
python3 -m t212bot verify-report           # independent report-vs-raw-API verification
```

Requires `T212_API_KEY`, `T212_API_SECRET` and `T212_ENV=demo`, plus Python 3.11+, pandas and numpy.

## Layout

```
config/strategy.json   live strategy (only changed via research/PROMOTION_GATE.md)
t212bot/client.py      demo-locked API client, rate limits, order-safety semantics
t212bot/market.py      reference quotes (Yahoo), FX, market hours from T212 schedules
t212bot/planner.py     pure rebalancing logic (fully unit-tested)
t212bot/executor.py    run orchestration: preflight → plan → sells → re-plan → buys → reconcile
t212bot/journal.py     append-only events.jsonl, snapshots.csv, state.json
t212bot/shadow.py      shadow portfolios at daily closes
t212bot/report.py      PERFORMANCE.md
t212bot/readonly.py    read-only facade (reporting/adviser cannot reach order methods)
t212bot/performance.py contribution-adjusted returns, fees, HWM/drawdown, reconciliation R1-R5
t212bot/adviser.py     withdrawal adviser (pure, recommendation-only) + notification de-dup
t212bot/wrappers.py    ISA/GIA notes, kept apart from the investment maths
t212bot/intel.py       daily intelligence report: collect -> compute -> render -> store
t212bot/emailer.py     Resend/SMTP/outbox delivery, retries, ledger, lock, DST-aware schedule gate
t212bot/daily.py       orchestration + exit codes for schedulers
t212bot/research_feed.py experiment registry / agenda / log reader
t212bot/verify.py      independent report-vs-account verifier (separate code path)
reports/               dated reports, metrics JSON, delivery log, adviser state
journal/               committed history of every decision, order and fill
ops_run.sh             what the scheduled routine runs
tests/                 fake T212 server + safety, planner, executor, report tests
```

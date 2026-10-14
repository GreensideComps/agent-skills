> **EXAMPLE DATA - this sample report uses synthetic numbers to show the format. It is not your account.**

# Daily intelligence report - SAMPLE

Generated 2026-10-13 14:22 BST (2026-10-13T13:22:28+00:00 UTC). Strategy `momentum_tilt_v1`.
Environment: **PRACTICE (demo) account - demo.trading212.com; live trading is disabled in code**.

**Status: all data sources responded, the account reconciles, and every health check passed.**

Labels: [EXAMPLE] Trading 212 API, read now · [EXAMPLE] bot records · [EXAMPLE] shadow portfolios at public closing prices · [ESTIMATE] model output · [BACKTEST] historical research

## 1. Account [EXAMPLE]

| Total value | Cash available | Reserved | In pies | Invested |
|---|---|---|---|---|
| **£140.99** | £1.55 | £0.00 | £0.00 | £139.44 |

| Holding | Quantity | Price | Value | Weight | Unrealised P&L |
|---|---|---|---|---|---|
| VWRPl_EQ (Vanguard FTSE All-World (Acc)) | 0.4612 | 151.2 GBP | £69.73 | 49.5% | £4.63 |
| IWMOl_EQ (iShares Edge MSCI World Momentum (Acc)) | 0.735 | 125.6 USD | £69.71 | 49.4% | £5.41 |

## 2. Money in/out and performance [EXAMPLE]

| Deposits | Withdrawals | Net contributions | Investment gain | Realised P&L | Unrealised P&L | Trading fees | Dividends | Interest |
|---|---|---|---|---|---|---|---|---|
| £150.00 | £20.00 | £130.00 | **£10.99** | £0.72 | £10.04 | £0.12 | £0.35 | £0.00 |

Fees by type: CURRENCY_CONVERSION_FEE £0.12.
Contribution-adjusted (time-weighted) return since 2026-06-14T10:00:00+00:00: **+7.75%** over 7 snapshot interval(s). Drawdown from high-water mark -0.64%; worst -4.35%. (Snapshot values are verified API reads stored in the journal.)

## 3. Orders [EXAMPLE] and bot attempts [EXAMPLE]

Verified orders in the last 24h: **1**; last 7 days: 1; all time: 5.
Pending orders now: none.

| Created (UTC) | Ticker | Side | Status | Qty | Fill price | Fees | Net value | Source |
|---|---|---|---|---|---|---|---|---|
| 2026-10-13T08:00:00Z | IWMOl_EQ | SELL | FILLED | -0.1 | 125.1 | £0.01 | £9.48 | API |
| 2026-09-03T09:00:00Z | VWRPl_EQ | BUY | FILLED | 0.1212 | 145.0 | £0.00 | £17.57 | API |
| 2026-09-03T09:00:00Z | IWMOl_EQ | BUY | FILLED | 0.275 | 120.0 | £0.04 | £24.94 | API |
| 2026-06-15T09:00:00Z | VWRPl_EQ | BUY | FILLED | 0.34 | 140.0 | £0.00 | £47.60 | API |
| 2026-06-15T09:00:00Z | IWMOl_EQ | BUY | FILLED | 0.56 | 112.0 | £0.07 | £48.17 | API |

Bot decisions and attempts in the last 24h:

- 2026-10-13T08:00:00+00:00 **plan**   - IWMOl_EQ drift +5.6% beyond ±5% band
- 2026-10-13T08:00:00+00:00 **order_rejected** VWRPl_EQ 0.07 - insufficient-free-for-stocks-buy (retried with fresh cash)
- 2026-10-13T08:00:00+00:00 **order_placed** IWMOl_EQ -0.1 - reduce to target

## 4. Benchmarks and strategy [SIMULATED vs VERIFIED]

Since inception 2026-06-14 with £100.00:

| Portfolio | Value | Return | Price as of (latest daily bar; intraday if the market is open) |
|---|---|---|---|
| **Real account [EXAMPLE]** | £140.99 | +7.75% (TWR) | now |
| A_benchmark_vwrp [EXAMPLE] | £108.10 | +8.10% | 2026-10-12 |
| C_gem12 [EXAMPLE] | £106.70 | +6.70% | 2026-10-12 |
| B_live_rules_at_close [EXAMPLE] | £109.30 | +9.30% | 2026-10-12 |

Short periods are dominated by noise; differences of this size are not evidence of skill (see research section).

## 5. Risk

- Concentration [EXAMPLE]: largest position VWRPl_EQ 49.5%; HHI 0.4891; ≈2.04 effective positions; cash 1.1%.
- Listing-currency weights [EXAMPLE]: {'GBP': 0.4946, 'USD': 0.4944} (underlying holdings are global equities either way).
- Volatility [ESTIMATE]: ≈14.2%/yr; one-day 95% VaR ≈ 1.47% (≈£2.07). Basis: EXAMPLE values.
- Drawdown from high-water mark [EXAMPLE]: -0.64%.
- Material changes: Value £141.90 → £140.99 (-0.64%) since the 2026-10-12 report.

## 6. Research [BACKTEST - historical, not live performance]

Experiment registry: 7 records (INSURANCE_ONLY 1, MOMENTUM_SUPPORTED 1, PENDING_RERUN 2, PROMOTED 1, REJECTED 2); cumulative configurations tested (for multiple-testing correction): 53.

| ID | Experiment | Decision | Key out-of-sample evidence | Main limitation |
|---|---|---|---|---|
| E001 | Asset-allocation timing: trend, dual momentum, rotation, risk parity, vol targeting | **REJECTED** | No family beat world equity significantly OOS; GEM-12 +1.2%/yr p=0.15 kept as shadow portfolio C only. | OOS period mostly a bull market |
| E002 | Trend following on the US market, 1928-2026 | **INSURANCE_ONLY** | Roughly halves max drawdown; does not raise long-run CAGR. | USD, gross index, US only |
| E003 | Persistence of factor premia (momentum, value, profitability) | **MOMENTUM_SUPPORTED** | Developed momentum still t≈2.1 after 2010; value premium ≈0. | long-short and gross: not what a £100 long-only account can hold |
| E004 | Tradeable MSCI World factor UCITS ETFs vs MSCI World | **PROMOTED** | Momentum chosen as the 50% tilt in champion momentum_tilt_v1 (not statistically proven; p=0.09). | 12 years only |
| E005 | Short-term mean reversion (RSI-2, down-day streaks) | **REJECTED** | Test CAGR 4-5%/yr vs 16.4% buy-and-hold; in cash 85-95% of the time. | Yahoo daily data; no intraday spreads |
| E006 | Volatility-managed momentum sleeve | **PENDING_RERUN** | A test run on 2026-10-13 reported rejection (DSR 0.86-0.90) but its code and outputs were never pushed (git 403), so they are unverified; to | A test run on 2026-10-13 reported rejection (DSR 0.86-0.90) but its code and outputs were  |
| E007 | Momentum sleeve with trend filter | **PENDING_RERUN** | A test run on 2026-10-13 reported rejection (lower OOS CAGR) but its code and outputs were never pushed (git 403), so they are unverified; t | A test run on 2026-10-13 reported rejection (lower OOS CAGR) but its code and outputs were |

Promoted to live (demo) trading: E004 Tradeable MSCI World factor UCITS ETFs vs MSCI World.
Latest research log entry (2026-10-13, Round 1): No strategy beats world equity significantly OOS. Momentum ETF +2.6%/yr (p=0.09). → Champion = momentum_tilt_v1 (50/50 VWRP/IWMO). GEM-12 → shadow.
Controls: pre-registered parameter grids, in-sample/out-of-sample split, survivorship-free index data where available, costs and a one-day lag included, bootstrap tests and a deflated Sharpe ratio using the cumulative trial count. Strategies change only through research/PROMOTION_GATE.md (at most one change per quarter).

## 7. Withdrawal adviser (recommendation only - never acts)

**Your portfolio has increased by £10.99 after adjusting for deposits and withdrawals. I recommend withdrawing £0 because none of your configured reasons for taking money out applies, and a rise in value alone is not a reason (the expected cost to future compounding outweighs the benefit: taking the whole £10.99 gain would forgo about £8.69 of growth over 10 years in the base case).**

- No configured reason applies (no planned expense due, no capital cap exceeded, profit-lock not enabled or not triggered). A rise in value alone is not a reason to withdraw.
- Calculation: Total value £140.99 − net contributions £130.00 = investment gain £+10.99.
- Calculation: Time-weighted return since inception +7.75% (deposits/withdrawals excluded).

| Withdraw now | Remaining now | conservative portfolio in 10y | base portfolio in 10y | adverse portfolio in 10y | Loss avoided on withdrawn £ in a shock |
|---|---|---|---|---|---|
| £0.00 | £140.99 | £189.48 | £252.49 | £127.51 | £0.00 |
| £2.00 | £138.99 | £186.79 | £248.91 | £125.70 | £0.80 |
| £5.00 | £135.99 | £182.76 | £243.54 | £122.99 | £2.00 |
| £10.00 | £130.99 | £176.04 | £234.58 | £118.47 | £4.00 |

- Assumption: Scenario annual returns are assumptions, not forecasts: conservative 3%, base 6%, adverse -1% for 10 years; shock = immediate -40% fall. Assumptions, not forecasts. Base sits below the research's measured long-run nominal equity CAGRs (world equity in GBP: 8.1%/yr 1992-2010, 11.1%/yr 2011-2026; US market 1927-2026 about 10%/yr in USD). Adverse is a lost decade (US 2000-2009 was about -1%/yr). The shock row is a 40% fall, comparable to 2008-09 in GBP terms.
- Assumption: Withdrawn money is assumed to be spent or held outside the portfolio, so it earns nothing further in these figures.
- Assumption: Selling costs assumed 0.10% (GBP lines) / 0.25% (non-GBP, incl. FX fee).
- Uncertainty: The scenario figures show sensitivity to assumed returns, not predictions. Future returns may be far outside this range in either direction, and past returns do not guarantee future results.
- Events: new investment-gain high (£10.99), recommendation basis changed to NO_DEFENSIBLE_REASON. Notification: not sent (£0 recommendation - reported in the daily report only).

## 8. Data quality, reconciliation and system health

| Check | Status | Detail |
|---|---|---|
| R1 total = cash + investments | PASS | total value: expected £140.99, actual £140.99, diff £+0.00 (tol £0.07) |
| R2 investments = Σ positions | PASS | investments value: expected £139.44, actual £139.44, diff £+0.00 (tol £0.07) |
| R3 cash ledger | PASS | cash from transaction history: expected £1.55, actual £1.55, diff £+0.00 (tol £0.07) |
| R4 gain = P&L components | PASS | investment gain: expected £10.99, actual £10.99, diff £+0.00 (tol £0.07) |
| R5 holdings = Σ fills | PASS | all position quantities match filled orders |
| API summary | PASS | read at 2026-10-13T13:22:28+00:00 |
| API positions | PASS | read at 2026-10-13T13:22:28+00:00 |
| API pending | PASS | read at 2026-10-13T13:22:28+00:00 |
| API orders | PASS | read at 2026-10-13T13:22:28+00:00 |
| API transactions | PASS | read at 2026-10-13T13:22:28+00:00 |
| API dividends | PASS | read at 2026-10-13T13:22:28+00:00 |
| Reconciliation | PASS | 5 passed, 0 failed, 0 skipped |
| Trading bot last run | PASS | 2026-10-13T08:00:00+00:00 (0d 5h ago); events: plan, run_end |
| Bot failures (7 days) | PASS | 0 failure event(s) |
| Research loop activity | PASS | last LOG.md entry 2026-10-13 (0 day(s) ago) |
| Experiment registry | PASS | 7 records valid |
| Market data freshness | PASS | latest close 2026-10-12 (1d old) |
| Previous email delivery | PASS | 2026-10-12: sent via resend accepted by provider |

## 9. Recommended priorities and unresolved issues

1. [RESEARCH] Next agenda item: P1 Volatility-managed momentum sleeve
2. [RESEARCH] 2 experiment(s) awaiting a verifiable re-run: E006 Volatility-managed momentum sleeve, E007 Momentum sleeve with trend filter

---
_Generated by `python -m t212bot daily-report`. Practice account only. Nothing in this report is financial advice; recommendations are produced by documented rules and never executed automatically._

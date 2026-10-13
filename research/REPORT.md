# Trading 212 Practice account: strategy research report (round 1)

Data pulled 2026-10-13. Last complete month used: 2026-09. No orders were placed, changed or cancelled. Only the demo server was used, and only for reads.

## Verdict

**No strategy tested shows a statistically demonstrable edge over a passive global equity fund after costs and out-of-sample testing.** Two candidates have a plausible economic rationale and positive, but not significant, out-of-sample results. They are worth paper trading against the benchmark:

| Portfolio (paper) | What | Out-of-sample evidence | Status |
|---|---|---|---|
| **A. Benchmark** | 100% `VWRPl_EQ` (FTSE All-World, GBP) | — | Default |
| **B. Momentum tilt** (lead candidate) | 50% `VWRPl_EQ` + 50% `IWMOl_EQ` (MSCI World Momentum, USD line) | Factor ETF beat MSCI World by +2.6%/yr, 2014-11 to 2026-09; p=0.09; alpha t=1.2 | Paper-trade |
| **C. Dual momentum (GEM, 12-month)** | US (`VUAGl_EQ`) vs ex-US (`VXUSl_EQ`) vs bonds (`VAGSl_EQ`), monthly | +1.2%/yr vs world equity, 2011–2026; p=0.15 | Paper-trade as a crash-insurance variant |

Rejected: trend-following / time-series momentum as a return enhancer, cross-asset rotation, inverse-volatility risk parity, volatility targeting, value, minimum volatility, short-term mean reversion (RSI-2, consecutive down days).

Not testable with the data available here: post-earnings-announcement drift, and concentrated stock-level momentum. See "Blockers".

## 1. Environment inspected

- **Account:** Practice (demo) account 51806610, GBP, £100.00 free cash, no positions, no pending orders. API reads returned HTTP 200.
- **API capabilities used:** account summary, positions, pending orders, instrument metadata. The API has **no price-quote or historical-price endpoint**, and orders must be sized by quantity; ordering by value isn't supported. Prices therefore come from outside sources, and fill quality can only be checked after an approved execution test, using `/history/orders`.
- **Universe:** 18,473 instruments: 12,168 stocks, 6,283 ETFs and 22 warrants. **Only 2 US-domiciled ETFs** are available (PRIIPs rules), so ETFs mean UCITS ETFs; about 3,000 are on the LSE and 1,581 are priced in GBP/GBX.
- **Costs assumed:** 0% commission. 0.15% FX fee per trade on non-GBP instruments (confirmed by several independent reviews; Trading 212's own terms page returned 403). 0.5% stamp duty on buying UK shares, with ETFs exempt. Bid/ask spread of 0.05–0.25% one-way by asset, stress-tested ×3 and ×5.

## 2. Data (all public, cached under `data/`, reproducible)

| Series | Source | Notes |
|---|---|---|
| UCITS ETFs: VWRL, VUSA, SGLN, VAGS, ERNS, IWFM/IWMO, IWFV, IWFQ, MINV, SWDA | Yahoo Finance chart API, adjusted close | Cleaned automatically: Yahoo LSE histories contain one-day GBP/USD unit flips (−38%/+62% pairs) and bad prints just after listing |
| Long-history proxies: VFINX, VGTSX, VEIEX, VFITX/VBMFX, gold futures | Yahoo | Mutual-fund NAVs are net of fees. Gold available from 2000-09 only |
| Global/regional equity indices and factor returns | Ken French Data Library (CRSP-based, **survivorship-free**) | Gross index returns; 0.2–0.3%/yr fee haircut applied |
| GBP/USD, UK 3-month interbank rate | FRED (DEXUSUK, IR3TIB01GBM156N) | |

Proxy validation against the real ETFs over 2012–2026: world-equity correlation 0.97, US 0.96, gold 0.98. Bonds are weaker at 0.78, so GBP-hedged bond history before 2019 is approximate. **XSTR was rejected** as a cash proxy because Yahoo omits its distributions; ERNS is used from 2013-11 instead.

## 3. Method

- Monthly rebalancing. Signals use only data through month-end *t* and earn month *t+1* (no look-ahead). Trading costs are charged on turnover after weights drift. Long-only, no leverage.
- **In-sample** 1992–2010 (dot-com bust and the 2008 financial crisis). **Out-of-sample** 2011-01 to 2026-09.
- **36 pre-declared variants** across 6 families. The winner of each family was picked **only on in-sample Sharpe** and then frozen.
- Significance: paired stationary block bootstrap (5,000 draws, 12-month blocks) of the Sharpe and CAGR differences against the benchmark. Deflated Sharpe ratio across all trials.
- Robustness: costs ×3 and ×5, a one-day execution lag, an 8-regime breakdown, and a 1927–2026 US check.

## 4. Results

### 4a. Asset-allocation timing (GBP, net of costs)

| Strategy (best in-sample of family) | IS CAGR / Sharpe / max DD | OOS CAGR / Sharpe / max DD | OOS vs world: ΔCAGR (p) |
|---|---|---|---|
| World equity buy & hold | 8.1% / 0.24 / −47.7% | **11.1% / 0.86 / −15.5%** | — |
| 60/40 world/bonds | 8.7% / 0.37 / −22.3% | 7.4% / 0.81 / −10.9% | −3.7% (1.00) |
| Trend: 10-month SMA → bonds | 12.5% / 0.62 / −16.9% | 8.1% / 0.67 / −19.3% | −3.0% (0.99) |
| Time-series momentum, 8-month | 12.2% / 0.62 / −15.8% | 7.6% / 0.62 / −16.8% | −3.6% (1.00) |
| **GEM dual momentum, 12-month** | 13.3% / 0.62 / −22.1% | **12.3% / 0.92 / −13.2%** | **+1.2% (0.15)** |
| Rotation, top-1 of 5, 12-month | 17.1% / 0.72 / −21.7% | 8.1% / 0.48 / −27.7% | −3.0% (0.80) |
| Inverse-vol world/bonds/gold | 9.7% / 0.73 / −6.0% | 4.9% / 0.65 / −9.8% | −6.2% (1.00) |
| Volatility target 15% | 7.5% / 0.21 / −42.6% | 10.6% / 0.83 / −15.5% | −0.5% (0.95) |

**Takeaway:** every family looked strong in-sample because 1992–2010 contained two roughly 50% crashes. Out-of-sample, all but GEM lost to buy-and-hold, by 3–6%/yr in most cases. The in-sample "winner" with the best deflated Sharpe (rotation, DSR 0.955) had one of the worst out-of-sample results. That is a textbook overfitting signature.

**100-year US check (1927–2026, survivorship-free):** a 10-month trend filter cut the worst drawdown from −84% to −43%, but changed CAGR by −0.65%/yr (p=0.65) and Sharpe by +0.09 (p=0.18). Trend-following is **insurance, not alpha**. It also hurt in 2022 (−19% vs −8%).

GEM is robust to costs ×5 (OOS CAGR 10.7%) and to a one-day execution lag (12.7%). It lagged a pure US benchmark out-of-sample (12.4% vs 14.8%).

### 4b. Systematic stock selection: factor premia

Long-short, gross, annualised mean (t-stat):

| Factor | 1927–1989 | 1990–2010 | 2011–2026 |
|---|---|---|---|
| US momentum | +8.5% (4.1) | +7.2% (1.8) | +2.8% (0.8) |
| US value | +5.6% (3.4) | +3.6% (1.5) | −0.4% (−0.1) |
| Developed-markets momentum | — | +7.5% (2.3) | **+5.3% (2.1)** |
| Developed-markets value | — | +5.3% (2.8) | +0.4% (0.2) |
| Developed-markets profitability | — | +4.4% (3.7) | +2.6% (2.0) |

Tradeable MSCI World factor ETFs vs MSCI World (SWDA), 2014-11 to 2026-09, GBP, net of fund fees:

| ETF | CAGR | Sharpe | max DD | ΔCAGR vs world (p) |
|---|---|---|---|---|
| MSCI World (SWDA) | 13.0% | 0.95 | −15.0% | — |
| **Momentum (IWFM/IWMO)** | **15.6%** | 0.97 | −15.1% | **+2.6% (0.09)** |
| Quality | 12.8% | 0.95 | −13.7% | −0.2% (0.61) |
| Value | 12.1% | 0.80 | −21.3% | −0.9% (0.60) |
| Minimum volatility | 9.1% | 0.73 | −13.2% | −3.9% (0.94) |

Momentum ETF CAPM regression against SWDA: alpha +2.3%/yr (t=1.21), beta 1.03. **Fragile:** removing its 6 best relative months leaves −0.2%/yr. Yearly relative returns ranged from −11.7% (2023) to +11.9% (2020).

**Economic rationale for momentum:** investors under-react to news and then herd (Jegadeesh & Titman 1993; Daniel, Hirshleifer & Subrahmanyam 1998; Hong & Stein 1999), and arbitrage is limited. It is the only premium here that persisted after publication across 100 years and in developed markets out-of-sample. Known risk: sharp "momentum crashes" in rebounds (2009).

### 4c. Short-term mean reversion (daily)

Trained on the S&P 500 total return index 1990–2010; tested on VUSA.L 2013–2026.

| Rule | Train Sharpe | Test CAGR / Sharpe | Buy & hold test CAGR / Sharpe |
|---|---|---|---|
| RSI(2)<10, exit above 5-day MA (next-close exec) | 0.72 | 5.4% / 0.59 | **16.4% / 0.95** |
| RSI(2)<5 | 0.48 | 5.1% / 0.72 | |
| 4 down days, hold 5 | 0.58 | 3.9% / 0.34 | |

**Rejected.** These rules sit in cash 85–95% of the time and can't keep up in a rising market.

## 5. Risk for a £100 account

Bootstrap (10,000 paths, 12-month blocks) of £100:

| Series | P(below £100 after 1y) | P(below £80 after 3y) | P(drawdown >50% within 10y) |
|---|---|---|---|
| World equity, GBP 1992–2026 | 21.7% | 3.6% | 2.4% |
| **US market, USD 1927–2026** (most realistic tail) | 25.4% | 7.5% | **19.7%** |
| **US top momentum decile, 1927–2026** | 23.7% | 5.9% | **24.5%** |
| 50/50 world + momentum ETF, 2014–2026 | 10.1% | 0.0% | 0.0% ← **misleading: short, bull-market sample** |

- **Losing most of the account (−50%)** with unleveraged diversified ETFs needs a 1929- or 2008-style crash. Over 10 years, the century of US data puts the chance of seeing a drawdown that deep at about **20–25%**, but the chance of *ending* below £50 at only about **1%**.
- **Costs at £100:** for the momentum-tilt portfolio, about £0.08 in FX fees on entry and again on exit (the IWMO leg), pennies on annual rebalances, plus spread. For GEM (≈1.5 switches a year) about £0.20–£0.40 a year. Neither is material. With fractional shares, position-size granularity isn't a problem.
- **Statistical power:** the momentum ETF's tracking error is 7.5%/yr. Confirming a 2%/yr edge at t=2 would take about **56 years** of data, and a 3%/yr edge about 25 years. **No paper-trading period can prove an edge.** It can only check implementation: signals, fills, costs, operational errors.

## 6. Paper trading (Phase 4)

`signals.py` writes `output/signals_latest.json` and appends intended trades to `output/paper_ledger.csv`. Signal as of 2026-09-30, reference prices from Yahoo 2026-10-13 closes:

| Portfolio | Intended (NOT placed) | Reason |
|---|---|---|
| A | £100 `VWRPl_EQ` @ £146.40 → 0.6830 sh | Benchmark |
| B | £50 `VWRPl_EQ` (0.3415 sh) + £50 `IWMOl_EQ` @ $116.95 (0.5650 sh, ≈£0.075 FX fee) | Static momentum tilt |
| C | £100 `VXUSl_EQ` @ £3.677 → 27.196 sh | GEM: ex-US 12m +19.9% > US +18.6% > cash +4.2% |

Trend filter state: world equity is 7.2% above its 10-month average (risk-on).

## 7. Weaknesses and caveats

- Out-of-sample 2011–2026 was mostly a strong bull market. Defensive strategies were bound to look bad in it. Bear-market evidence comes mostly from the in-sample period and the US century data.
- About 50 configurations were tried in total. At that count, a p=0.09 or p=0.15 result is the kind expected by chance.
- Pre-2012 data uses proxies (US mutual funds, Ken French indices, a synthetic hedged-bond series). The bond proxy is the weakest (correlation 0.78).
- Month-end sampling understates intra-month drawdowns.
- GEM's GBP 12-month signal was very close this month (19.9% vs 18.6%), and **VXUS only started trading on 2026-08-18**: its spreads are unknown and probably wider than assumed.
- `IWMOl_EQ` is the USD-quoted line, so every trade pays the 0.15% FX fee. The quote currency doesn't change the underlying currency exposure. **Correction (2026-10-13):** the GBX line of the same fund *is* on Trading 212 as `IWFM_EQ` (same ISIN IE00BP3QZ825); the first search missed it because it doesn't use the `l_EQ` suffix. Switching the existing holding doesn't pay at £100 (about £0.10–0.15 of spread vs about £0.01/yr of FX saved), but any future full rebalance should use `IWFM_EQ`. See AGENDA P3.
- The demo account may fill more favourably than live trading would.

## 8. Blockers

- **Post-earnings-announcement drift:** needs point-in-time earnings and consensus-surprise history. None was available. LSEG/Daloopa connectors need authorising, and SEC EDGAR returned 403. The academic literature also reports large post-2000 decay in large caps.
- **Concentrated stock-level momentum (5–20 names):** Yahoo only has currently listed stocks, so any backtest would carry survivorship bias. Survivorship-free CRSP deciles (above) were used instead. A 5–10 stock version would add large idiosyncratic risk, plus the 0.15% FX fee on every US trade.

## 9. Next actions

1. **Paper-track A vs B vs C monthly** (first trading day, after the month-end signal) by re-running `signals.py`. Log reference prices and compare against Trading 212 fill prices once an execution test is approved.
2. **Approve, or decline, a separate demo execution test.** For example: buy £50 `VWRPl_EQ` + £50 `IWMOl_EQ` with limit orders, to measure real spread and FX cost against Yahoo reference prices.
3. Authorise the LSEG connector (point-in-time fundamentals and earnings) to unblock earnings-drift testing and longer MSCI factor-index history (MSCI World Momentum back to 1994) for an independent momentum-tilt test.
4. Re-run the full battery yearly. Promote B or C over A only if live-tracked evidence and longer index history both still support it.

## Reproduce

```bash
cd research
pip install pandas numpy scipy statsmodels
python3 dataset.py           # downloads + cleans data, builds monthly GBP returns
python3 run_allocation.py    # 36 allocation variants: IS selection -> OOS
python3 run_regimes.py       # regime table, cost stress, 1927-2026 US trend check
python3 run_factors.py       # factor premia + UCITS factor ETFs
python3 run_meanrev.py       # daily mean-reversion tests
python3 run_exec_lag.py      # one-day execution-lag robustness
python3 run_risk.py          # loss probabilities + statistical power
python3 signals.py           # current signals -> paper ledger (no orders)
```

Outputs land in `output/*.csv`. Raw data are cached in `data/` (git-ignored; Yahoo data isn't redistributable).

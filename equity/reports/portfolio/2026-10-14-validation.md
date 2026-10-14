# Pre-trade validation of the 14 October 2026 portfolio plan (demo account)

Prepared 14 October 2026, 15:05 to 15:40 UTC. **No orders were placed, drafted or queued. No pie, position, setting or
trigger was changed.** The original plan is unchanged at [`2026-10-14-review.md`](2026-10-14-review.md); this report
replaces its recommendations, not its record.

## Verdict in one paragraph

The original plan should **not** be approved as written. Three exits (Intel, Bloom Energy, Tempus AI) rest on hard
financial evidence. The rest of it does not. The other sells and trims rest on a valuation model that rates almost
every holding as overvalued (Costco too, which the plan buys), on screen scores the backtest cannot vouch for in
large-cap tech, or on concentration alone. The 600-company backtest reproduces exactly, but it gives no usable
evidence about large technology companies, and the plan described its result too favourably. The plan's
concentration cut is real but modest: 5-year volatility falls from 31.6% to 27.3%, against 12.8% for a global index
fund. How much AI and semiconductor risk to carry is your choice, not a finding. The pie-unlock step in the original
plan was also described wrongly: deleting a pie is not the way to keep shares.

## Data used, with timestamps and provenance

| Data | Source | Retrieved | File |
|---|---|---|---|
| Holdings, cash, pie quantities, pending orders | Trading 212 **demo** API, GET only (account summary, positions, orders) | 2026-10-14 15:05:38 UTC | [`audit/api_snapshot.json`](audit/api_snapshot.json) |
| Financial statements | SEC XBRL company facts, **annual 10-K/20-F only** (no quarterly data) | Research DB, latest ingest 14 Oct | [`audit/evidence.json`](audit/evidence.json), [`audit/fcf_history.json`](audit/fcf_history.json) |
| Screen scores, gates, reverse DCF | Research DB, screen run of 14 Oct (screen-1.0, val-1.0) | 14 Oct | `evidence.json` |
| Daily prices, 5 years | Yahoo Finance chart API (unofficial, dividend-adjusted), GBPUSD from Yahoo | 2026-10-14 ~15:20 UTC | [`audit/prices_5y_daily.json`](audit/prices_5y_daily.json) |
| VWRP country, sector and top-10 holdings | Vanguard factsheet, data as at 31 Aug 2026 | 14 Oct | [`audit/vanguard_vwrp_factsheet_2026-08-31.pdf`](audit/vanguard_vwrp_factsheet_2026-08-31.pdf) |
| Backtest rows (original and re-run) | `equity/research/output/screen_backtest_rows*.jsonl` | original 14:53 UTC; re-run 15:05 to 15:35 UTC | [`audit/backtest_audit_original.json`](audit/backtest_audit_original.json), [`audit/backtest_audit_rerun.json`](audit/backtest_audit_rerun.json) |
| Risk comparison | Computed from the price file | 14 Oct | [`audit/risk_comparison.json`](audit/risk_comparison.json) |
| Pie behaviour | Trading 212 official API spec (committed `trading/spec/t212_openapi.yaml`), Help Centre, community forum | 14 Oct | cited in section 5 |

### Checks that failed or need care
- **1-year correlations look abnormal.** The average pairwise correlation of the holdings is 0.26 over 1 year
  against 0.40 over 5 years. Apple and the Nasdaq-100 have a −0.1 rolling correlation since June 2026. Yahoo's SPY
  and QQQ series agree with each other (0.93), so this may be a real market regime. I could not verify it against a
  second source. **Decisions here use 5-year figures.**
- **Daily data understates co-movement with VWRP.** VWRP closes in London hours before New York, so daily figures
  understate it. Benchmark beta, correlation and tracking error below use weekly returns. VWRP's betas to the
  semiconductor and Nasdaq indices are also understated for the same reason.
- **TSMC fundamentals are stale.** The database's latest year is FY2024 (the FY2025 20-F is not ingested), its data
  confidence is "low", and it has no valuation because the ADR ratio is unknown.
- **ASML has no valuation.** It reports in euros and the ADR ratio is unknown.
- **SpaceX has no research data.** It is 5.4% of the portfolio, traded only since 12 June 2026, and its SEC match is
  low.
- **No bear case exists for any company.** The research ledger is empty. The system's own rule (`equity/research.py`)
  lets a company become a candidate only with a recorded bear case. **None of the proposed additions qualifies
  yet.**
- **Tempus AI's dilution figure is overstated.** The +40%/yr includes its 2024 IPO and preferred-share conversion,
  not only ongoing issuance.

## 1. Current portfolio, verified

From the live API read at 15:05:38 UTC:
- **Holdings:** 22 positions, identical in quantity to the snapshot behind the report (14:59 UTC).
- **Value:** £1,294.95 total, £0 cash, no pending orders. The report's "£1,298" came from an earlier read; the
  difference is market movement.
- **Pie status:** every position has `quantityInPies` equal to `quantity`, and `quantityAvailableForTrading` = 0.
  Nothing is tradeable until the shares leave the pies.
- **Currency:** every instrument is priced in USD, including IBTA (iShares $ Treasury 1-3yr, LSE). The account
  currency is GBP.
- **Identifiers:** ISINs match the security master. Two exceptions: IBTA is an ETF, which the master does not
  hold, and SpaceX (US84615Q1031) is matched with low confidence.
- **Cost basis:** £1,298.05 across the 22 positions (positions created 14:46 to 14:49 UTC). These are the copy
  prices, not your ISA's real averages.

| Holding | Weight | Holding | Weight |
|---|---|---|---|
| Nvidia | 12.9% | Vertiv | 3.1% |
| Alphabet | 10.9% | AMD | 3.1% |
| Broadcom | 10.9% | Bloom Energy | 2.3% |
| Microsoft | 10.0% | Palo Alto Networks | 1.6% |
| Amazon | 8.8% | Vistra | 1.4% |
| Meta | 6.2% | Intel | 1.4% |
| TSMC | 6.1% | CrowdStrike | 1.2% |
| ASML | 6.1% | Tempus AI | 0.9% |
| SpaceX | 5.4% | Apple | 0.7% |
| Palantir | 5.4% | Tesla | 0.7% |
| | | Uber, IBTA | 0.5% each |

**Discrepancy with the report:** it put semiconductors at 34%. That used SEC industry codes, which file ASML under
machinery. Counting chip-equipment makers (ASML) as semiconductors, the figure is **40.6%**. On that definition
the plan takes it to **28%**, not 23%.

## 2. Backtest audit

### What was run
- **Code:** `equity/equity/backtest.py`, run via `python -m equity backtest --n 600 --seed 7`. Pre-registered in
  `equity/research/screen_backtest_prereg.md` (commit 51c9031, 14:39 UTC), before the run (commit 290510e,
  14:53 UTC).
- **Universe:** a random 600 of the 5,472 companies the security master links to SEC with high confidence
  (seed 7).
- **Decision dates:** each April month-end, 2012 to 2025. Each holding period runs to the following April.
- **Inputs at each date:** every XBRL fact filed on or before the decision date (`pit_facts`), scored by the
  unchanged live screen (`screener.score_company`). The market cap uses the price as it traded then: the
  split-adjusted close times later split ratios.
- **Returns:** Yahoo monthly dividend-adjusted closes (total return).
- **Benchmarks:** SPY, and the equal-weighted average of all scored companies.
- **Weights were fixed before the results were seen.** `config/screener.json` was committed once, at 14:21 UTC
  (blob `e1c30aa`), unchanged since. The screener and fundamentals code has not changed since 14:25 UTC. They
  were not tuned on this test. Caveat: I set them the same day without any historical test, so they are untested
  judgement, not fitted parameters.

### Reproduction
- **From the stored rows,** the same code gives mean IC +0.0771, **t = 1.918**, and the ranked basket ahead in
  11 of 14 years. The reported figures reproduce exactly.
- **A full re-run from scratch** (new SEC and Yahoo downloads, 15:05 to 15:35 UTC) gives identical scores and ICs.
  The return differences are under 0.0000001.
- **Errors:** 9 SEC 404s, and 59 companies with no scorable year. Both are the same in the re-run.

### What the t-statistic tests
It is a one-sample t-test of whether the average yearly rank correlation (score vs next-12-month return) differs
from zero. It treats the 14 yearly ICs as independent draws (13 degrees of freedom).
- **Result:** t = 1.92 gives a one-sided p of about 0.04 and a two-sided p of about 0.08.
- **Bootstrap 95% interval for the mean IC:** −0.004 to +0.149, which includes zero.
- **Sensitivity:** the result depends on which years are included. Dropping 2012 alone lifts t to 3.19; dropping
  2017 drops it to 1.52.
- **Individual years:** only 2 of 14 yearly ICs (2017 and 2024) are individually distinguishable from zero.

### Why "11 of 14 years" is weak evidence
- **The headline count:** the "ranked basket" won 11 of 14 years. Against a coin flip, 11 or more wins has a
  probability of 2.9% (one-sided binomial).
- **The basket is not "top picks", as the report implied.** It is every scored company that passes the gates,
  about **70% of the scored set**. So it is compared with a group it mostly overlaps.
- **The average margin is tiny and not significant:** +0.5 percentage points a year, median +1.8, t = 0.51.
- **One bad year cancels most of the wins.** 2021 lost 11.4 points, which undoes most of the small gains in other
  years.
- **The years are not fully independent.** Fundamentals persist from year to year and the basket's membership
  turns over only about 24% a year.
- **Top-minus-bottom quintile:** +4.1 points a year on average, t = 1.27, positive in 9 of 14 years.

### Biases and limitations
| Issue | Status |
|---|---|
| Look-ahead in financial data | Controlled: facts filtered by filing date. Restated values are seen as first filed. |
| Look-ahead in industry classification | **Not controlled.** The SIC code and industry template are today's, not as of each date. |
| Survivorship | **Present.** Only companies listed on Trading 212 today. Delisted and bankrupt firms are missing, so absolute returns are overstated. The effect on rank correlation is unknown in direction. |
| Universe construction | **Effectively small.** Of 4,113 company-years with a price, only 1,037 (25%) received a total score. Banks, insurers, REITs and companies with incomplete data are unscored. Scored companies per year: 32 to 96. |
| Rebalancing and turnover | Annual, April. About 24% of the basket is new each year. |
| Costs, FX, dividends | No trading costs or FX. Dividends are included through adjusted prices. Returns in USD. |
| Benchmark | SPY, plus all-scored equal weight. No size or style matching. |
| Risk-adjusted | Basket 16.2% a year vs SPY 14.4% (both April 2012 to April 2026), but with **more than twice SPY's volatility of annual returns** (27% vs 13%). Return per unit of volatility: **0.68 vs 1.18 for SPY**. Excess over SPY: +3.7 points a year, t = 0.86. |
| Market regimes | No April-to-April window had a falling SPY, so a bear market was never tested. In weak years (SPY 0 to 10%) the basket trailed the scored average by 1.2 points. |
| **Company size** | Median scored company about $3 to 5bn. Only 11 to 29 companies a year are above $10bn. Large-cap tercile IC +0.037, t = 0.64: **no evidence among large companies.** |
| **Sector** | Technology (SIC-defined): only 81 scored company-years in 14 years, and **no year with 10 or more**. The backtest says **nothing** about large-cap tech, which is three-quarters of this portfolio. |
| Sub-scores (post hoc, not pre-registered) | FCF per share IC t = 2.93; valuation t = 1.42; quality, growth and risk-fit near zero. Five tests were run after the fact, so treat this as a hypothesis for a new pre-registered test, not a finding. |

**Conclusion:** the test reproduces, and was run honestly against a pre-set bar, which it failed. It is weak
evidence the score ranks small and mid-cap US industrial companies slightly better than chance. It is **no evidence
for using the score to buy or sell large-cap technology stocks.** The original report's sentence, "its top picks
beat the rest in 11 of 14 years", overstated it.

## 3. Each proposed action, challenged

### Two cross-cutting problems with the evidence
- **The valuation model cannot support a sell on its own.** Its base case caps growth at 15% a year (bull case
  20%) and starts from a 3-year average of free cash flow. For a fast-growing company, a 3-year average understates
  current cash flow, which inflates the "growth the price implies". The result: it puts fair value 50 to 90% below
  the price for Nvidia, Microsoft, Alphabet, Amazon, Broadcom, AMD, Apple, CrowdStrike, Vertiv **and Costco**. A
  model that calls nearly everything overvalued cannot single out AMD and Tesla as sells.
- **The screen's evidence does not cover these companies.** See section 2: a low or high score here is not a
  validated signal.

Hard financial risk below means negative free cash flow, interest cover under 3x, or debt above 4x EBITDA. A
company's share count rising through issuance also counts. All figures are from annual SEC filings; the
fiscal-year end is shown where it matters.

### Exits

**Intel (1.4%, about £18): exit. Supported by evidence (hard financial risk).**
- **Evidence:** free cash flow −$14.3bn (FY2023), −$15.7bn (FY2024), −$4.9bn (FY2025). Interest cover −2x. Share
  count +3.2% a year. Debt $46.6bn against $14.3bn cash. Revenue fell from $79bn (FY2021) to $52.9bn.
- **No DCF:** it can't be run, because base cash flow is negative.
- **Bull case:** foundry turnaround, US government support, cash flow improving fast (−$15.7bn to −$4.9bn).
- **Base case:** losses narrow but returns on capital stay below the cost of capital for years.
- **Bear case:** foundry never reaches scale and dilution continues.
- **What the price needs:** a credible path to positive free cash flow within about 2 years.
- **Strongest argument against selling:** the worst cash burn may be behind it, and 1.4% is small enough to hold
  as an option.
- **What would invalidate the sell:** two consecutive quarters of positive free cash flow, or a major external
  foundry customer announced.

**Bloom Energy (2.3%, about £30): exit. Supported by evidence (hard financial risk).**
- **Evidence:** free cash flow positive in only 3 of 10 years (FY2025 +$0.1bn). Interest cover 1.4x. Share count
  +8.9% a year. Debt up from $1.1bn to $2.6bn in FY2025.
- **For the other side:** revenue +37% (FY2025), to $2.0bn.
- **Bull case:** fuel cells become a standard on-site power source for data centres.
- **Base case:** growth continues but is funded by dilution and debt.
- **Bear case:** a funding squeeze if growth stalls.
- **What the price needs:** sustained high growth *and* a step-change in margins.
- **Strongest argument against selling:** it is one of the few direct plays on the power constraint for AI, and
  FCF just turned positive.
- **What would invalidate the sell:** two years of positive FCF with a flat share count.

**Tempus AI (0.9%, about £12): exit. Supported by evidence (hard financial risk).**
- **Evidence:** free cash flow negative every reported year (−$0.24bn, FY2025). Interest cover −3.6x. Share count
  rising (the +40%/yr figure is inflated by the 2024 IPO).
- **For the other side:** revenue +83% (FY2025), to $1.27bn.
- **Strongest argument against selling:** fast growth in AI diagnostics, and a 0.9% position limits the risk.
- **What would invalidate the sell:** positive operating cash flow.

**Tesla (0.7%, about £9): exit. Potentially reasonable, needs more evidence; immaterial either way.**
- **No hard financial risk:** net cash ($16.5bn cash vs $6.6bn debt) and FCF +$6.2bn.
- **But the fundamentals are deteriorating:** revenue −3% (FY2025), net income down from $15.0bn (FY2023) to
  $3.8bn.
- **Valuation:** the price needs about 61% a year FCF growth on our (flawed, see above) model. P/E 341.
- **Bull case:** the value is in autonomy and robots, which the model cannot see.
- **Strongest argument against selling:** the business case is not visible in historical cash flows, so the model
  is the wrong tool.
- **What would invalidate the sell:** revenue and margins growing again.

**Uber (0.5%, about £6): exit. Not supported.**
- **The evidence points the other way.** FCF rose from $3.4bn (FY2023) to $6.9bn to $9.8bn (FY2025). FCF yield
  6.9%. The price implies about 8% a year growth, below its history. Our own model's base value is **47% above**
  the price; its bear case is 11% above.
- **Why the plan sold it:** the only failed gate is FCF consistency, because of loss years before 2022, plus
  "too small to matter".
- **Better options:** keep it, or bring it up to a meaningful size.

**AMD (3.1%, about £40): exit. Potentially reasonable as part of a semiconductor cap; not supported as a
stock-specific sell.**
- **No hard risk:** net cash. FCF rose from $1.1bn to $2.4bn to $6.7bn. Revenue +34% (FY2025). Share count
  +1.4%/yr.
- **The case against rests on the valuation model:** the price implies 59% a year, and P/E 220. GAAP earnings are
  likely depressed by acquisition amortisation (inferred, not verified here).
- **Strongest argument against selling:** fundamentals are improving fast, and AMD is the second AI-accelerator
  supplier.
- **What would invalidate the sell:** it holds or gains AI accelerator share while FCF keeps growing.

### Trims

**Nvidia 12.9% to 11% (sell about £25): potentially reasonable, as concentration control only.**
- **The strongest company on every measure:** revenue +65% (FY2026), FCF $96.7bn, ROIC 94%, net cash, share count
  falling. Screen rank 2.
- **No position limit is breached:** the monitor's limit is 15%. The trim exists only to lower semiconductor
  weight.
- **What the price needs:** about 35% a year FCF growth for 5 years on our model.
- **Strongest argument against trimming:** it trims the best business.
- **What would make a trim unnecessary:** your choosing a higher semiconductor limit.

**Broadcom 10.9% to 7% (sell about £50): not supported as a stock call; potentially reasonable for
concentration.**
- **The failed dilution gate is mostly a one-off.** Shares rose from 4.27bn to 4.78bn when it paid for VMware in
  shares (FY2024), and were 4.85bn in FY2025.
- **Ongoing costs are real:** stock-based pay is 11.8% of revenue. Debt $67bn, about 2x EBITDA (under the 4x
  gate).
- **Cash generation is strong:** FCF rose from $19.4bn to $26.9bn.
- **Strongest argument against trimming:** custom AI chips plus VMware give two growing cash streams.

**Amazon 8.8% to 7% (sell about £23): not supported.**
- **The low score (45, rank 17) comes from FCF falling to $7.7bn in FY2025,** because capex rose to $131.8bn. That
  is a spending choice, not a financial risk: net cash, and operating cash flow is growing.
- **Strongest argument against trimming:** the capex is the AI cloud build-out the rest of the portfolio is betting
  on.

**TSMC 6.1% to 5% (about £14): blocked by missing data** (see "Checks that failed" above). A trim can only be
justified on concentration. FY2024 figures are strong: TWD 870bn FCF, no debt problem.

**ASML 6.1% to 5% (about £14): blocked by missing data** for valuation. Fundamentals are strong: FCF €11.1bn
(FY2025), ROIC 87%, net cash. The case is concentration only.

**Palantir 5.4% to 4% (sell about £18): potentially reasonable.**
- **Real dilution:** shares rose from 2.30bn to 2.57bn in 2 years. Stock-based pay $0.7bn on $4.5bn revenue.
- **Valuation is extreme on any method:** FCF yield 0.4%, P/E 329.
- **For the other side:** revenue +56% (FY2025), FCF tripled to $2.1bn, net cash.
- **What would invalidate the trim:** growth staying above 40% while dilution falls.

### Additions

None of these has a recorded bear case, which the system's own rules require before a company becomes a
candidate.

**Adobe 4% (about £52): potentially reasonable, needs more evidence.**
- **The cheapest high-quality name on our numbers:** FCF $9.9bn and rising. FCF yield 10.6%. P/E 14. Share count
  falling 3.2% a year. ROIC 62%. Screen rank 1.
- **The price assumes slow decline:** about −3.5% a year FCF.
- **Margin of safety:** a no-growth value (FCF ÷ 9% discount rate ÷ 0.43bn shares) is about **$256**, against a
  price of $238. **A price at or below about $205 would give a 20% margin** even if cash flow never grows.
- **The bear case is the reason it is cheap:** generative AI could erode seat-based pricing for creative
  software. It must be written up and evidenced before buying.
- **Why Adobe rather than an alternative:** among eligible names it is the only one priced below a no-growth
  value.

**Costco 4%: not supported as a value pick; potentially reasonable as a diversifier.**
- **Our model calls it expensive:** P/E 47, the price implies 24% a year FCF growth against 12% history, and the
  base value is 56% below the price. Buying it contradicts the logic used to sell AMD.
- **Its real role would be low AI sensitivity:** 5-year beta to the semiconductor index 0.21, and to the
  Nasdaq-100 0.53, the lowest of the candidates.
- If that is the goal, say so and size it as such.

**MSCI 4%: potentially reasonable, needs more evidence.**
- **Strengths:** recurring index and data revenue, FCF margin 49%. The price implies 16% a year against 17%
  history.
- **Weaknesses:** leverage 3.3x EBITDA, debt up from $4.5bn to $6.2bn in FY2025, FCF flat at $1.5bn.
- **Diversification:** adds financial-sector exposure.

**Ralph Lauren 3%: potentially reasonable, needs more evidence.**
- **Strengths:** P/E 25, base value 25% above price, revenue +15% (FY2026).
- **Weaknesses:** FCF fell from $1.0bn to $0.7bn in FY2026. It is a cyclical consumer and tariff-exposed name.

**Agilent 2%: not supported.**
- **The weakest candidate:** score 57, rank 15. Revenue flat over 4 years ($6.3bn to $6.9bn). FCF fell from $1.5bn
  to $1.2bn. Base value 49% below price.
- **No reason was given** for choosing it over other eligible names.

**VWRP 3%: not supported at this size.**
- **It barely changes the risk.** Nine of VWRP's top 10 holdings are already held (all but Micron); its top 10 make up 24.8% of the
  fund. A 3% position adds about 1.1 points of non-US exposure.
- **A global core is a separate decision** about core and satellite, which you asked to keep apart. It is shown
  below only as the benchmark.

## 4. Portfolio risk: keep vs alternatives

### Method
- **Returns:** daily, dividend-adjusted, converted to GBP. VWRP.L is GBP-priced.
- **Weights:** constant, rebalanced daily (an idealisation). On dates where a name had no price yet (SpaceX before
  June 2026, Tempus before June 2024), it is dropped and the rest are rescaled. Names with full 5-year history
  cover at least 94% of each portfolio.
- **Benchmark-relative figures:** weekly returns.
- **Scenarios:** a linear beta shock, using each name's 5-year beta. This ignores idiosyncratic moves and
  non-linearity.
- **Hindsight warning:** every past return below is inflated by hindsight. These holdings were chosen knowing how
  the last few years went. Use the risk numbers, not the returns.

### The portfolios
- **A** is the current portfolio.
- **B** makes only the independently supported changes: exit Intel, Bloom Energy and Tempus AI, with the money
  spread pro rata.
- **C** is the original proposed plan.
- **B2** is for information: B, plus semiconductors capped at 25%, with the freed weight put into the existing
  non-AI holdings.
- **VWRP** is the diversified global benchmark.

| Measure | A keep | B hard-risk exits | C proposed | B2 (info) | VWRP |
|---|---|---|---|---|---|
| Holdings / effective number | 22 / 12.7 | 19 / 11.7 | 22 / 15.2 | 19 / 14.5 | 3,784 |
| Semiconductors incl. ASML | 40.6% | 41.1% | 28.0% | 25.0% | ≥9.1% (top-10 only) |
| AI-linked total (my grouping) | 89.5% | 89.0% | 70.6% | 72.9% | not computed |
| Technology (SIC-based) | 74% | 76% | 67% | 73% | 34% (ICB) |
| Country: US / Taiwan / Netherlands | 87 / 6 / 6% | 87 / 6 / 6% | 88 / 5 / 5% | 90 / 4 / 4% | 62% US, 38% elsewhere |
| Underlying currency USD | 100% | 100% | 99% | 100% | about 62% |
| Largest / top 5 | 12.9% / 54% | 13.6% / 56% | 11.2% / 46% | 11.4% / 46% | 4.8% / 18% |
| Volatility, 5y | 31.6% | 31.4% | 27.3% | 29.4% | 12.8% |
| Max drawdown, 5y | −35.5% | −35.9% | −31.8% | −35.8% | −17.6% |
| Worst 21 days, 5y | −19.1% | −19.6% | −17.9% | −19.2% | −10.8% |
| Calendar 2022 return | −31.1% | −31.9% | −26.9% | −31.5% | −8.3% |
| Weekly beta to VWRP, 5y | 1.77 | 1.74 | 1.57 | 1.65 | 1.00 |
| Tracking error vs VWRP, 5y | 21.4% | 21.5% | 17.6% | 19.9% | 0 |
| Scenario: semiconductor index −40% | −28% | −28% | −23% | −25% | −6%* |
| Scenario: Nasdaq-100 −30% | −40% | −39% | −35% | −37% | −8%* |

\*VWRP's scenario figures are understated by the London/New York timing; use its actual 2022 result as the
better guide.

How the AI-linked grouping works (my classification, not a data field):
- **Compute and semiconductors:** Nvidia, Broadcom, TSMC, ASML, AMD, Intel.
- **Infrastructure and power:** Vertiv, Vistra, Bloom Energy.
- **Hyperscalers:** Microsoft, Alphabet, Meta, Amazon.
- **AI software:** Palantir, Tempus AI.

**Liquidity:** all positions are large-cap stocks or a large ETF, and the largest is about £167, so liquidity is not
a constraint. The real constraint is the bot's limit of 10 orders per run.

### Does cutting semiconductors from 34% to 23% (41% to 28% on the wider definition) materially improve diversification?

**Partly, not materially.**

What improves:
- **Effective holdings:** rises from 12.7 to 15.2.
- **AI-linked weight:** falls from 90% to 71%.
- **Five-year volatility:** falls from 31.6% to 27.3%.
- **Drawdown:** improves by about 4 points.
- **Semiconductor-crash loss:** falls by about 5 points.

What doesn't change:
- **Volatility is still more than twice the global index's** (2.1x).
- **The portfolio is 88% US and about 100% USD.** Its beta to the global market is still about 1.6, and about 70%
  is tied to one economic driver: AI capital spending.

Where the improvement comes from:
- About half comes from the new non-tech stocks, not from the semiconductor cut. B2, which only caps
  semiconductors, gets volatility to 29.4% and leaves drawdown unchanged.
- Hyperscalers stay at 34% in every version. They are the *buyers* of AI chips, so they fall in the same scenario.

Materially lower risk would need a much larger diversified core, which is a decision about how much risk you want
to take, not one the evidence makes for you.

### Costs
- **Plan C:** about £260 sold and £260 bought. Trading 212's 0.15% FX fee on the roughly £480 of USD trades comes to
  about **£0.70**. Spreads are not known for the demo account. It needs 18 orders, so two bot runs (the 10-order
  limit stays).
- **Option B:** about £60 sold, roughly £0.10 FX, 3 orders.
- **Tax:** none in the real ISA.

## 5. Making pie shares tradeable: what is documented

### What the sources say

**Official API spec** (`trading/spec/t212_openapi.yaml`, Trading 212's published OpenAPI):
- **All pie endpoints are tagged "Pies (Deprecated)":** list, create, get, update, duplicate and delete.
- **Delete pie** (`DELETE /api/v0/equity/pies/{id}`, 1 request per 5s) has the description "Deletes a pie by given
  id" and **does not say what happens to the shares inside**.
- **There is no endpoint to export holdings from a pie.**
- **Update pie** takes only target weights (`instrumentShares`), name, goal, icon and dividend action. Changing
  weights is a rebalance instruction, which can lead to sales.
- **Positions report two fields:** `quantityInPies` ("Quantity of shares currently used in pie") and
  `quantityAvailableForTrading`.
- **The developer docs** ([docs.trading212.com/api](https://docs.trading212.com/api)) list Pies as deprecated with
  no replacement or explanation.

**Trading 212 Help Centre,**
[Deleting a Pie](https://helpcentre.trading212.com/hc/en-us/articles/360009575897-Deleting-a-Pie) (undated):
- **A pie must be empty before it can be deleted:** value 0, no investments, no pie cash.
- **There are two ways to empty it:**
  - **Withdraw funds**, which **sells** all investments in the pie.
  - **Export investments**, which moves the shares you want to keep outside the pie.
- Delete is in the three-dot menu, and "Deleting a Pie is permanent and cannot be undone."

**Community forum, 2020, so it may be out of date**
([thread](https://community.trading212.com/t/how-to-delete-a-share-from-a-pie-without-selling-it/21418)):
- **Export is reached by** "Pie > Holdings > More Action > Export investments", on the phone app (not the web app).
- **Removing a holding through "Edit pie" does not remove it.** It leaves the holding in the pie, marked "to be sold
  with priority during the next rebalancing or withdrawal".

### Conclusions
- **The original plan was wrong** to say deleting the pies keeps the shares. Deleting needs an empty pie, and the
  keep-the-shares route is **Export investments**.
- **This is a manual action in the app.** No current, non-deprecated API call does it.
- **Not tested.** I have not tested any of this, cannot see the app, and did not call any pie endpoint, including the
  read-only ones.
- **A successful response does not prove the right outcome.** The only acceptable proof is the positions read-out
  below.

### Safe procedure (demo only, one pie at a time)

0. **Before anything:** the trading routines are still off (the hourly trader and the daily ops run have been
   disabled since 15:03 UTC). The research loop and portfolio monitor are read-only. I take a fresh read-only
   snapshot as the baseline.
1. **In the mobile app, export one small pie first:** open the pie, then Holdings, then the "More" or ⋯ menu, then
   **Export investments**, and select all.
   - **Before confirming,** read the confirmation screen. If it says anything about selling, rebalancing or
     withdrawing, cancel.
   - **Never use** Withdraw funds, Edit pie (to remove a holding), or Delete on a pie that still holds value.
2. **Tell me it's done.** I read positions again and check, for each exported holding:
   - the quantity is unchanged;
   - `quantityInPies` is 0;
   - `quantityAvailableForTrading` equals the quantity;
   - there are no new orders or history entries;
   - the total value has moved only with the market.
3. **If all of step 2 passes,** repeat for the other pies. If anything fails, stop.
4. **Leave the empty pies in place** until there is a reason to delete them. Deleting is permanent and not needed
   for trading.

**Risks:**
- A wrong tap on Withdraw sells everything in that pie.
- Edit-pie removals queue sales.
- The export screens may have changed since 2020.
- Whether exported shares can be imported back is mentioned on the forum but not verified, so treat the export as
  not cleanly reversible.

**Manual confirmations needed from you:**
- you choose the export option yourself;
- you read the confirmation screen before tapping;
- you tell me after each pie, so I can check.

## 6. Revised decisions

### Portfolio-risk decisions (yours to make)

| Decision | Classification | Evidence | Main counterargument |
|---|---|---|---|
| Reduce AI and semiconductor concentration at all | **Your choice; the risk is measured, the answer is preference** | 40.6% semis, about 90% AI-linked, 2.5x global volatility, 2022 −31% vs −8% | That concentration is the bet you chose in your ISA, and it has paid (with hindsight) |
| Plan C's specific cut to 28% (wider definition) | Potentially reasonable, modest effect | Volatility 31.6% to 27.3%, drawdown −35.5% to −31.8%; still 1.6x global beta | Half the effect comes from the new stocks, which aren't yet evidenced |
| Add a global core (VWRP) | **Separate decision**, not part of this plan | 3% changes almost nothing; a meaningful core would | Keeps core and satellite apart, as you asked |
| Exit tiny positions just for tidiness | Not supported | Under 1% positions don't move portfolio risk | |

### Individual-stock decisions

| Action | Classification | Estimated cost | Main counterargument |
|---|---|---|---|
| Exit Intel | **Supported by evidence** | under £0.05 | Turnaround already under way |
| Exit Bloom Energy | **Supported by evidence** | under £0.05 | Direct AI power play, FCF just turned positive |
| Exit Tempus AI | **Supported by evidence** | under £0.05 | +83% revenue growth |
| Exit Tesla | Potentially reasonable, needs more evidence (immaterial) | under £0.05 | The value isn't in historical cash flow |
| Exit Uber | **Not supported** | | Our own data says it is undervalued and improving |
| Exit AMD | Potentially reasonable only as a semis cap | about £0.06 | Fundamentals improving fast |
| Trim Nvidia | Potentially reasonable only as a semis cap | about £0.04 | Trims the best business; no limit breached |
| Trim Broadcom | Not supported as a stock call (gate artefact); potentially reasonable as a cap | about £0.08 | Dilution was a one-off acquisition |
| Trim Amazon | **Not supported** | | Low score reflects capex, not risk |
| Trim TSMC | **Blocked by missing or unreliable data** | | |
| Trim ASML | **Blocked by missing or unreliable data** (valuation) | | |
| Trim Palantir | Potentially reasonable | about £0.03 | Exceptional growth |
| Add Adobe | Potentially reasonable, needs more evidence (bear case) | about £0.08 | AI disruption is exactly why it's cheap |
| Add Costco | Not supported as value; potentially reasonable as a diversifier | | Our model calls it expensive |
| Add MSCI | Potentially reasonable, needs more evidence | | Leverage 3.3x |
| Add Ralph Lauren | Potentially reasonable, needs more evidence | | FCF fell in FY2026; cyclical |
| Add Agilent | **Not supported** | | |
| Add VWRP 3% | Not supported at this size | | |

## Revised proposed plan (nothing trades until you say so)

1. **Now:**
   - Unlock the pies using the export procedure in section 5. Exporting moves nothing economically.
   - Meanwhile I fix the data gaps: TSMC's FY2025 filing, ADR ratios for ASML and TSMC, SpaceX coverage, and the
     1-year correlation check.
2. **First trade, if you approve it:**
   - Exit Intel, Bloom Energy and Tempus AI: 3 orders, about £60, about £0.10 in fees.
   - Hold the proceeds as cash until step 3.
   - This is the only change the evidence supports on its own.
3. **Your call on concentration.** Pick a semiconductor limit (for example 25% or 30%) and an AI-linked limit, or
   none. Trims then follow mechanically from your limit, not from screen scores. Whether to add a global core is a
   separate question.
4. **Additions only after a written bear case** from a different author than the bull case, per the system's own
   rule:
   - Adobe first, then MSCI and Ralph Lauren.
   - Agilent dropped. Costco only if you want a deliberate low-AI diversifier.
5. **Uber and Amazon stay.** Tesla is your call (0.7%).
6. **New pre-registered backtest** limited to large companies (over $10bn), and a separate test of the FCF-per-share
   sub-score, before the screen is used to trade large-cap names.

## Unresolved issues

1. The pie export behaviour hasn't been seen in the current app; it rests on the Help Centre plus 2020 forum posts.
2. API `DELETE /pies/{id}` on a non-empty pie: behaviour undocumented. It won't be used.
3. The 1-year correlation anomaly hasn't been verified against a second price source.
4. TSMC fundamentals are stale (FY2024), and TSMC and ASML have no valuations (ADR ratio, currency).
5. SpaceX (5.4%) has no fundamentals or valuation; it is unscored and unclassified by sector.
6. No bear cases exist for any company; this blocks every addition under the system's own rule.
7. The valuation model's growth caps and 3-year average base make it unfit as a sell signal for fast growers. It
   needs a methodology change, which is your decision.
8. The backtest has no large-cap or tech evidence; it has survivorship bias; its SIC codes are not point-in-time.
9. The demo copy uses copy-date cost prices, so profit and loss here don't reflect your ISA.
10. The original approve/change card is still open. This report recommends not approving the original plan as
    written.

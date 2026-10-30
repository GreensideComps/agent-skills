# Regime-conditioned research track: pre-registration (draft 1, 26 Oct 2026)

Written before any regime-conditioned result has been computed by anyone. Decision C7 in
research/office/DECISION_REGISTER.md. Owner idea (26 Oct 13:13Z): instead of one edge, keep a set of methods that
switch on and off with market conditions or the time of year.

## Question
Do any of the 15 Stage 2 signals (all failed unconditionally), or a few well-known seasonal effects, earn a net
excess return over VWRP when used only in a regime defined in advance?

## Data and period
- Exploration only: 2015-01 to 2022-11 large caps (Stage 2 universe, survivor bias as stated there).
- The 2023-2026 holdout is NOT touched. Survivors go to forward paper tracking, not to the holdout.
- Daily seasonal tests use research-data/edge (prices, benchmarks and NYSE calendar to 2022).

## Regimes (fixed now, each known at the decision date, using data lagged one month)
| Dimension | State ON | State OFF |
|---|---|---|
| R1 Trend | S&P 500 / VWRP proxy above its 10-month moving average | below |
| R2 Volatility | 1-month realised index vol below its trailing 60-month median | above |
| R3 Calendar | Nov-Apr | May-Oct |

## Trials (all count toward the deflated-Sharpe trial total)
- A. Conditional signals: 15 Stage 2 signals x 3 dimensions x 2 states = **90 trials**. The signal is held in that
  state and VWRP is held otherwise. Same long-short decile construction and costs as Stage 2.
- B. Seasonal timing on the index vs buy-and-hold, long-only (stocks, or cash/T-bills when out):
  B1 Nov-Apr only (sell in May), B2 turn of month (last trading day to day +3), B3 pre-holiday day,
  B4 January large-cap reversal (prior-year losers in January) = **4 trials**.
- New N = 102 + 94 = **196**. Any later regime, signal or threshold is a new trial and raises N.

## Pass rule (all required)
1. Net of 2x costs, t >= 3 on the conditional excess return, Holm-adjusted across the 94.
2. Deflated Sharpe >= 0.9 with N = 196.
3. Same sign in 2 of 3 sub-periods (2015-17, 2018-20, 2021-22).
4. At least 30 months (A) or 200 events (B) in the ON state, else INCONCLUSIVE.
5. The FF5+UMD alpha keeps its sign.

## Honest prior
About 47 months per state gives weak power. Most likely outcome: 0 to 2 passes. With 94 tries at t >= 3 and Holm,
a false pass is unlikely but possible.

## What a pass earns
Forward-only paper tracking in the market agent's journal, tagged by strategy, for at least 6 months or 30 trades.
Only after that does it get real weight in the 20% satellite, under the C6 rules (2% per trade, kill after 30 trades
if net <= VWRP). The 8-K test (STAGE4_8K_PREREG_DRAFT.md) runs alongside it.

## Execution
Run once, after the weekly usage reset on Fri 30 Oct 04:00Z. One code module plus a report, results appended as a
new registry batch. Results are never rewritten.

## Addendum 1 (30 Oct 2026, before any result was computed): how the ambiguous parts are implemented

Fixed in code (`research/regime.py`) and committed before the run:
- **Market index** for regimes and seasonal tests: Ken French market (Mkt-RF + RF), daily and monthly, cut at
  2022-12-31 before anything is computed. Cash is RF.
- **Lag:** R1 and R2 at decision month-end t use only data up to month-end t-1. R1: index level at t-1 above the mean
  of month-end levels t-10..t-1. R2: daily realised vol in month t-1 below the median of the monthly vols for
  t-60..t-1. R3 depends only on the calendar: ON when the return month (t+1) is Nov-Apr.
- **A series:** the investable Stage 2 series, top quintile minus universe (large caps), held in ON months and 0
  (VWRP / universe) in OFF months. "Net of 2x costs" = twice the Stage 2 cost: 2 x 2 x 0.30% x turnover. Turnover is
  1.0 in the first ON month after an OFF month, plus an exit turnover of 1.0 in the last ON month before an OFF month.
  The decile long-short d10-d1 in ON months is reported as information only.
- **t:** Newey-West (3 lags) t of the monthly series over all months. Holm uses one-sided p = 1 - Phi(t) over the
  94 trials at alpha 0.05.
- **DSR:** Bailey-Lopez de Prado with N = 196 and the cross-trial variance of the 94 monthly Sharpe ratios.
- **Sub-periods:** mean monthly return of the series within 2015-17, 2018-20, 2021-22 > 0 in at least 2 of 3.
- **Alpha:** FF5 + UMD alpha of the series must be > 0.
- **B tests** (daily, 2015-01-02 to 2022-12-30): the strategy holds the market on ON days and RF otherwise; the
  series is strategy minus the market, summed to months, net of 2 x 0.30% per one-way switch. B1 ON = Nov-Apr
  trading days. B2 ON = last trading day of a month to the 3rd trading day of the next. B3 ON = the trading day
  before a weekday NYSE holiday. B4 = the bottom decile of large caps by 12-month return at each December
  month-end, held in January, minus the large-cap universe, net of 2x costs. Events: B1-B3 = ON days,
  B4 = stock-Januaries.
- **Registry:** `research/edge/trials.jsonl` is whole-file pinned (D33/D34), so results go to
  `research/output/regime/` and the report instead. They are never rewritten.

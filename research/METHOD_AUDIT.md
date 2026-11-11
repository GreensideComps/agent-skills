# Audit of the research method (11 Nov 2026)

Question: 486 ideas tested, none passed. Is that because nothing works, or because the test is wrong? This audit
checks for errors in both directions. It changes no past result, registers no trial and reads no return after
December 2022. Every number below comes from `python3 research/method_audit.py`.

## Verdict in four lines

1. **The pass bar could not have passed a realistic edge.** A deflated Sharpe of 0.95 after 486 trials needs a
   t-statistic of 4.69. An idea worth a real 3% a year, tested on the 8 years most trials used, has a 0.0% chance of
   reaching it and would need about 340 years of data. So "0 of 486" was certain in advance and is not evidence
   that nothing works.
2. **A fairer test finds nothing either.** Judged by the false-discovery rate instead (the right error rate for an
   exploratory search feeding a forward test), 5 of the 103 results with enough recorded detail stand out. On
   inspection none is a tradable edge (table below). The conclusion "no proven edge, hold VWRP" survives.
3. **Four things made results look better than they were.** A copied formula, trades counted as independent when
   they were not, a kill rule that scored VWRP as 0% when its price was missing, and data with no failed or
   acquired companies. All four are fixed or measured here.
4. **More results lose than win.** 16 results are significantly negative against 8 significantly positive. After
   costs, the typical idea is a reliable way to trail the index.

## 1. Too strict: the bar is out of reach

| True edge a year | Years of data | Expected t | Chance of t >= 2 | Chance of clearing the bar | Years needed for an 80% chance |
|---|---|---|---|---|---|
| 2% | 8 | 0.57 | 8% | 0.0% | 765 |
| 3% | 8 | 0.85 | 12% | 0.0% | 340 |
| 3% | 30 | 1.64 | 36% | 0.1% | 340 |
| 5% | 8 | 1.41 | 28% | 0.1% | 122 |
| 5% | 30 | 2.74 | 77% | 2.6% | 122 |
| 5% | 95 | 4.87 | 100% | 57.3% | 122 |

(Tracking error 10% a year. 140 of the 246 results that recorded their length used 10 years or less.)

The count of trials is not the main cause: the bar is 3.22 after 10 trials, 4.18 after 100 and 4.69 after 486. Short
histories are. The improvement track's rule T5 (long-history data first) already points the right way.

What changes: nothing is loosened. The deflated-Sharpe gate and the go-live rule stand. From now on each result
should also report its false-discovery standing (`stats.bh_fdr`) and its power before it is run
(`stats.power`, `stats.months_needed`), so a failed test says whether it could have passed.

## 2. A fairer lens: the false-discovery rate

103 of 354 results recorded both a monthly Sharpe and a length. Their t-statistics have mean -0.11 and spread 1.80
(pure luck gives 0 and 1), so the results are not pure noise, on either side:

| t at least | Results above | Results below the negative | Expected by luck, each side |
|---|---|---|---|
| 1.645 | 16 | 17 | 5.1 |
| 2.0 | 8 | 16 | 2.3 |
| 2.5 | 5 | 11 | 0.6 |
| 3.0 | 3 | 9 | 0.1 |

Benjamini-Hochberg at a 10% false-discovery rate keeps five (two if the tests may be arbitrarily dependent):

| t | Trial | What it is | Tradable edge? |
|---|---|---|---|
| 5.45 | AO-Q230 | published factors (profitability, value, momentum), US 1963-2022 | No: +0.55% a year since 2007 (t 0.54). Real historically, gone since publication. |
| 3.77 | AO-Q206 | buybacks in cheap stocks | No: the recorded Sharpe came from a smoothed series; rebuilt from real monthly holdings (Q207) it is 0.09, t about 0.9. |
| 3.03 | AO-Q229c | 75% VWRP + 25% 3x US | No: leverage and a US tilt, not skill; -61% drawdown. |
| 2.69 | AO-Q229a | 2x US | No: same. |
| 2.61 | AO-Q228b | Nasdaq-100 as core | No: a sector bet that fell 81% once. |

So the honest reading is unchanged, and now it rests on a test that could have said otherwise.

Registry gap found on the way: only 103 of 354 results carry enough to recompute a t-statistic, and at least one
(Q206) stores a figure the loop itself later corrected in prose. New results should record `sr_monthly`,
`n_months`, skew and kurtosis from the real monthly series (`stats.deflated_sharpe_of` returns all of them).

## 3. Too lenient: four errors that flattered results

| Error | Where | Effect | Fix |
|---|---|---|---|
| Deflated Sharpe re-typed in at least 7 research scripts with the cross-trial spread fixed at its minimum (1/T) and, in 6 of them, no skew or fat-tail term | `research/always_on/q2*.py` | The recorded spread of Sharpes across trials is 2.6x that minimum, so the luck allowance was about 1.6x too small: those scripts overstated DSR. No verdict flips (all failed anyway). | `research/stats.py`: one implementation, checked against the registry's pinned formula and scipy. New scripts import it. |
| Trades opened on the same days counted as independent | per-trade t in results (Q206 "t 4.4") and go-live check 4 | Thirty trades from one fortnight passed as thirty bets. In the test suite such a burst clears the plain test three times over with only two independent weeks behind it. | `stats.cluster_t`; go-live Amendment 2 requires the week-clustered t as well. |
| Kill rule scored VWRP as 0% when its price was missing at either end of a trade | `agent/market_agent/active.py` | A strategy trailing VWRP could survive its 30-trade review. | Compared like with like on trades that have both prices (agent-1.23, tested). |
| No failed or acquired companies in the price data | `research-data/prices_monthly.csv.gz` | See below. | Measured here; prices for the missing names are backlog item S11 (blocked on the free data cap until December). |

### Survivorship, measured

| January | Companies with $1bn+ revenue in SEC filings | With a price in the backtest file | Stopped filing within 3 years | Of those, priced |
|---|---|---|---|---|
| 2013 | 1426 | 736 | 158 | 0 |
| 2014 | 1460 | 769 | 183 | 0 |
| 2015 | 1514 | 815 | 215 | 0 |
| 2016 | 1557 | 859 | 246 | 0 |
| 2017 | 1530 | 880 | 241 | 0 |
| 2018 | 1536 | 942 | 224 | 1 |
| 2019 | 1638 | 1009 | 217 | 2 |

Each year 11% to 16% of large companies stop filing within three years (taken over, merged or failed), and the
backtests saw essentially none of them (3 of 1,484). The direction of the error depends on the strategy: takeovers
usually pay a premium (their absence hurts a backtest), failures lose everything (their absence flatters it). It
flatters most the ideas that buy weak or fallen companies: drop_rebound, gap_rebound, news_shock, cheap-crash screens.
Treat every stock-level result on this panel as an upper bound for those, and re-run them first when S11 lands.
(The unpriced remainder also includes foreign and debt-only filers with no US share listing.)

## 4. What was already right

- Pre-registration with hashes, a counted registry, and a holdout touched once. Nothing here reopens the holdout.
- The registry's own deflated Sharpe (`edge_registry.deflated_sharpe`) is correct and pinned by tests.
- The loop caught the Q200-Q206 smoothing error itself (Q207) and corrected the prose.
- Failed ideas that run on the demo are labelled unproven, sized at 2%, and each counts in the go-live adjustment.

## 5. What is now in place

| Thing | Where |
|---|---|
| One tested statistics module (t, cluster-robust t, Newey-West, deflated Sharpe, FDR, power) | `research/stats.py`, `research/tests/test_stats.py` (74 checks against scipy and statsmodels) |
| Scoreboard under version control, tested, run by the hosted agent | `research/always_on/scoreboard.py`, `research/tests/test_scoreboard.py` |
| Go-live Amendment 2 (tightening only): week-clustered t | `research/always_on/GO_LIVE_RULE.md` |
| This audit, reproducible | `python3 research/method_audit.py` |

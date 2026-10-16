# B5 real-data implementation hand-check (fixed in advance)

Written 2026-10-16, before any real-data run of the programme's portfolio settings. Registered as `B5-HANDCHECK`
(diagnostic, not counted in N).

**Purpose:** confirm, on real 2015-2022 data, that the engine implements the frozen rules in
`B5_PREREGISTRATION.md` correctly: eligibility, ranking, weights, sector caps, turnover, costs, FX and benchmark.
It validates implementation only. **It cannot select or change a parameter**, and it is built so it reveals
nothing about how H1 or S2a performed.

## 1. How performance stays hidden

- **Portfolio arithmetic is checked with a placebo score:** `score = −(sha256("B5-HANDCHECK" + cik) as a
  fraction)`, fixed now. It carries no information about returns. The placebo runs both frozen configurations:
  quarterly (H1's rules, 3 tranches) and 12-month (S2a's rules, 12 tranches). Its NAV is shown; it is not a trial.
- **H1 and S2a scores are checked on their own,** with no return attached: the score value, eligibility and rank
  at the check dates, and the 20 names that would be bought. Holdings at a date reveal nothing about later returns,
  and no NAV, excess or return of either trial is computed.

## 2. Fixed check dates (chosen by rule, not by outcome)

| Date (decision) | Why it is in the sample |
|---|---|
| 2015-01-31 | First evaluated decision: portfolio built from cash (full turnover) |
| 2015-04-30 | First quarterly rebalance after it: buffer and turnover from an existing portfolio |
| 2019-07-31 | Benchmark segment boundary: the following period is the first "actual VWRP" period |
| 2020-03-31 | The window's largest one-month market move (chosen on the market, not on any strategy) |
| 2022-11-30 | Last decision: its execution must fall in December 2022, and nothing later may be read |

For the 12-month configuration, the tranche whose rebalance falls on each date is checked.

## 3. Fixed companies at each date

At each date and for each configuration, a script picks by rule, not by hand:

1. rank 1, rank 20 and rank 21;
2. the highest-ranked holding kept by the buffer (ranked 21-40), if any;
3. the highest-ranked name passed over by the sector cap, if any;
4. the highest-ranked name passed over for a missing execution price, if any;
5. one name excluded by each rule, if any: quality flag, price under $1, below $10bn, financial, stale TTM, and
   (H1) the 3x share-change guard.

That is about 8 to 12 companies per date and configuration.

## 4. What is checked

Each item is recomputed by a separate script written for this check, reading the raw files directly (cut at
2022-12-31) and not importing `edge_backtest`, plus a manual check against the SEC filing for two companies per
date.

| Area | Recomputed independently |
|---|---|
| Eligibility | Market cap = share count × `close_raw`, band, $1, quality flag, financial, freshness, lags present |
| Scores | H1 steps 1-6 and S2a from the raw XBRL fields. For two companies per date: free cash flow, share count, total assets and gross profit read by hand from the 10-K/10-Q on EDGAR. |
| Ranking | Order by score then CIK; S2a percentile within SIC group |
| Selection | Buffer kept names, sector cap of 4 per group, skips for missing execution prices |
| Weights | 1/20 at each rebalance; drifted weights between rebalances from execution prices |
| Turnover | Σ\|Δweight\| / 2 against the drifted pre-trade weights |
| Costs | Σ\|Δweight\| × 0.30% (and 0.60% at 2x) |
| Execution | Execution date = first NYSE trading day after the month-end (calendar file); price = that day's close |
| Missing prices | Any exit in the window: last valid price less 30% |
| FX | GBPUSD on or before each execution date, within 7 days; GBP NAV from USD NAV |
| Benchmark | VWRP/VWRL prices on or before each valuation date, within 5 days; the period's label |
| Tranches | Combined return = mean of the tranche returns for each period |
| Holdout | No row, execution or benchmark date after 2022-12-31 is read |

## 5. Pass rule

- Every recomputed number matches the engine to 1e-9 (arithmetic) or exactly (dates, names, labels, counts).
- Every hand-read SEC value matches the dataset value, or the difference is explained by a later restatement
  that the point-in-time rules handle correctly.
- **Any mismatch:** stop, find the cause, fix the code (never a frozen definition), rerun the whole hand-check and
  report the fix. A data error in a filing is documented, not patched.

## 6. Output

`equity/reports/research/edge/b5_handcheck.md`, with each check, the values on both sides and the verdict, plus
the placebo NAV. It contains no H1 or S2a return.

# Survivorship bias in the stock panel: measured and bounded (11 Nov 2026)

Code: `research/always_on/survivorship_coverage.py` (coverage), `research/always_on/exit_classes.py` (exit routes and
the bound), tests in `research/tests/test_exit_classes.py`. Cache of SEC metadata:
`/mnt/project-files/research-data/sec_exits.json`. Only SEC filing metadata and the presence of a price were read, never
a return, and nothing from 2023 on.

## The problem

The 2011-2022 stock panel (`prices_monthly.csv.gz`) has prices for almost none of the companies that stopped filing
with the SEC: 3 of 1,484 big companies that vanished within three years were priced (METHOD_AUDIT.md). Every
stock-panel backtest therefore picks only from companies that survived to 2022.

## How the missing companies left

571 companies with $1bn+ trailing revenue stopped filing between 2011 and 2019. Each one's SEC filing history was read
and its exit classified from the filings near the end:

| Route | Companies | Share | Effect of leaving them out |
|---|---|---|---|
| Acquired (merger proxy, tender response, change of control) | 412 | 72% | survivor-only data looks WORSE: it misses the takeover premium |
| Distressed (8-K item 1.03 bankruptcy, or delisting notice then deregistration) | 51 | 9% | survivor-only data looks BETTER: it misses the losses |
| Other (going private by other routes, subsidiaries and LPs that file for their debt, unclassified) | 108 | 19% | unknown; counted as failures in the worst case |

Per year (exit year, the share of that year's $1bn+ universe that left by each route) the bias of an equal-weighted
long-only backtest on survivors:

| Exit year | $1bn+ universe | Acquired | Distressed | Other | Bias, central (pp/yr) | Bias, worst (pp/yr) |
|---|---|---|---|---|---|---|
| 2013 | 1550 | 30 | 3 | 12 | -0.16 | +0.97 |
| 2014 | 1616 | 45 | 3 | 11 | -0.30 | +0.81 |
| 2015 | 1660 | 41 | 5 | 18 | -0.17 | +1.40 |
| 2016 | 1668 | 73 | 5 | 13 | -0.46 | +0.97 |
| 2017 | 1661 | 72 | 10 | 17 | -0.26 | +1.57 |
| 2018 | 1758 | 72 | 13 | 17 | -0.13 | +1.67 |
| 2019 | 1844 | 57 | 9 | 17 | -0.15 | +1.40 |
| mean 2011-2019 | | | | | **-0.19** | **+1.03** |

Central case: distressed exits lose 55%, takeovers pay 25% (Shumway 1997; Beaver, McNichols and Price 2007), survivors
make 10% a year. Worst case: every "other" exit was a failure, every failure went to zero, takeovers paid only 15%.

## Weak companies are more exposed

Strategies that buy financially weak companies (negative free cash flow or falling revenue; gap_rebound's health gate
selects exactly these) are more exposed: in 2013-2019 such companies left through distress at 0.75% a year against
0.16% for healthy ones (4.7 times), and by an unclassified route at 0.98% against 0.80%. Their worst-case bias is about
+1.7 percentage points a year.

## What it means

1. For a broad long-only stock strategy the bias is small and, in the central case, works AGAINST the strategy: the
   missing takeovers outweigh the missing failures. Survivorship does not explain away a large result.
2. It can explain a small one. A stock-panel edge under about 1 point a year (1.7 for weak-company strategies) cannot
   be told apart from survivorship. Research gate v3 now requires a stock-panel batch to clear that bound on its
   confirmation window (`gate.SURVIVORSHIP_PP`, GATE_V3.md stage 2).
3. Past verdicts are unchanged. Every stock-panel strategy now on the demo was benched or labelled unproven, so none
   relied on a margin this small being real.
4. The real fix is survivor-free prices for the vanished companies (improvement backlog S11). Yahoo has no history for
   most delisted tickers, so this needs another free source; until then the bound above is the honest correction.

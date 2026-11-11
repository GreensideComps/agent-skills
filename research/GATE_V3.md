# Research gate v3 (pre-registered 11 Nov 2026, effective for trials registered from 12 Nov 2026)

Written before any trial has been judged by it. It changes how NEW ideas are judged. It does not re-judge any
earlier result, does not touch the 2023-26 holdout, and does not change the go-live rule for real money.
Code: `research/gate.py` (tests: `research/tests/test_gate.py`). Background: `research/METHOD_AUDIT.md`.

## Why the old gate goes

The old gate passed an idea only if its backtest's deflated Sharpe reached 0.95 against every trial ever run. At
N = 486 that needs a t-statistic of 4.69, and the bar rises with every new idea. It answers the question "could even
one of all our results be luck?", which is the right question for the final step before real money, and the wrong one
for deciding which ideas deserve a forward test. Its chance of passing a real edge (10% tracking error):

| True edge a year | Data | Old gate | Gate v3 (k = number of configurations in the batch) |
|---|---|---|---|
| 3% | 59 years (US, Ken French) | 0.9% | 21% (k = 3) |
| 5% | 59 years | 20% | 68% (k = 3) |
| 3% | 30 years | 0.1% | 13% (k = 1) |
| 5% | 30 years | 2.6% | 39% (k = 1) |
| 5% | 8 years (stock panel) | 0.1% | 5% (k = 3): still not worth a trial |

The last row is deliberate: no honest gate can find a modest edge in 8 years of data. Gate v3 says so before the
trial is run (the power check), instead of after.

## The gate

1. **Declare a batch before reading data.** One idea = one batch of 1 to 10 configurations, written in the
   pre-registration with two fixed windows: a discovery window and a later, non-overlapping confirmation window,
   each at least 36 months, both ending by 2022-12. Every configuration declared is scored; none may be dropped.
   Each configuration is still appended to the trial registry and counts in N.
2. **Power check.** `gate.power_line(edge, te, discovery_months, confirmation_months, k)` goes in the
   pre-registration. If it says REDESIGN (chance of passing a plausible edge under 25%), redesign the test before
   spending a trial: longer data, fewer configurations, or a stronger signal.
3. **Stage 1, discovery.** On the discovery window only: one-sided p-value of each configuration's mean monthly
   excess return (Newey-West t), then Benjamini-Hochberg at q = 0.10 across the batch.
4. **Stage 2, confirmation.** Each configuration stage 1 kept is tested once on the confirmation window at one-sided
   alpha = 0.05 / (number kept), and must also stay positive there with costs doubled and with a one-month lag.
   Configurations stage 1 dropped are never scored on the confirmation window.
   A stock-panel batch (`data="panel"`, or `"panel_weak"` when it selects companies with negative free cash flow or
   falling revenue) must also beat the worst-case survivorship bias on the confirmation window: a mean excess above
   1.0 (panel) or 1.7 (panel_weak) percentage points a year (`research/SURVIVORSHIP.md`). Added 11 Nov 2026, before
   the gate took effect.
5. **Pass** = stage 2 holds. A pass goes to the office thread as a labelled demo forward test (2% a trade, the
   30-trade kill rule). Real money still needs every check in GO_LIVE_RULE.md, which is unchanged.
6. **Still reported, no longer the gate:** the deflated Sharpe at the current N, the post-2007 sign, the six robustness
   views (`improve/harness.py`), the trade-level gross-vs-cost check. A reader can still see all of them.

A configuration with no edge passes with probability at most 0.10 / k x 0.05 (0.17% for k = 3; a simulation of 6,000
noise configurations is in the tests). A real edge's chance depends only on its size and the length of its data, not
on how many other ideas the project has tried.

## Choosing windows

- Long-history ideas (Ken French, Shiller, FRED, AQR): discovery 1963-07 to 1999-12, confirmation 2000-01 to 2022-12,
  unless the pre-registration gives a reason for another split. The confirmation period is then also the
  post-publication era for most published factors, which is the decay test the old 2007+ rule was after.
- Stock-panel ideas (2011-2022): discovery 2011-2016, confirmation 2017-2022. The power check will usually say
  REDESIGN; that is the point.
- A window that was already used to choose the idea (for example a result seen in an earlier trial) is not a
  confirmation window for it. Say in the pre-registration which data the idea came from.

## What does not change

Pre-registration, the hash-chained registry, counting every configuration in N, the holdout (one confirmation batch
ever, never reused), the forward-test labels, the go-live rule, the kill rule, and never rewriting a past result.

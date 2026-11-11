# Q201 pick-1 with continuous hard-break exits: FAIL, worse than yearly (3 Nov 2026)

Selling a held name as soon as a new filing broke a gate, or when it fell 25% below entry, traded ~37 names a
year and turned the yearly screen's +3.43%/yr into -0.73%/yr vs the universe (t -0.20). Gate exits alone (no
crash guard) gave +0.86%/yr; a 35% guard -0.36%. Gates flip often near their thresholds (debt ratio, share
count), and the crash guard sells at lows that later recover. Every interim-exit rule tested (Q200, Q201) did
worse than holding to the January rebalance.

AMENDMENT (3 Nov 15:20Z, after seeing the result, logged openly): the prereg fallback said live exits would be
gate fails + delistings. The test's own view shows gate-fail exits cost ~2.6%/yr vs yearly, so live exits are
limited to: delisting / merger, and 8-K red-flag items 1.03 (bankruptcy), 3.01 (delisting notice), 4.01
(auditor change), 4.02 (non-reliance on financials). Everything else (new filing re-score, gate breaks,
-25% drawdowns) is checked continuously and reported as an alert, not traded.

```
Q201 pick-1 + continuous hard-break exits (exploration 2015-22, N=420)
vs EW universe: -0.73%/yr after costs, t -0.20 (yearly Q199: +3.43%)
gate exits only +0.86; guard 35% -0.36; costs x2 -1.47; lag1 -2.68; large-only +2.50
~37 names traded/yr
verdict: FAIL. Live: continuous monitoring + alerts; exits only on delisting or 8-K red flags
```

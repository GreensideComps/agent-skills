"""Robustness: execute monthly signals at the close of the FIRST trading day of
the next month (one-day lag) instead of the signal month-end close."""
import numpy as np, pandas as pd
from dataset import build, _tr_daily_gbp
from engine import run, metrics, compare
from strategies import gem, bench, trend_sma

R = build()
daily = {"US": _tr_daily_gbp("VFINX"), "INTL": _tr_daily_gbp("VGTSX")}
# WORLD daily: spliced UCITS VWRL.L from 2012-06, VTSMX/VGTSX 50/50 proxy before (daily world index unavailable)
lagged = R.copy()
for k, px in daily.items():
    first = px.groupby(px.index.to_period("M")).head(1)          # first trading day close of each month
    first.index = first.index.to_period("M").to_timestamp("M")   # label with the month it starts
    r_lag = first.pct_change().shift(-1)                         # return from day-1 of month m to day-1 of month m+1
    # month m+1 holding (decided at end of m) earns first(m+1)->first(m+2): label it as month m+1
    lagged[k] = r_lag.reindex(R.index)
lagged = lagged[lagged.index <= "2026-08-31"]
cash = R["CASH"]
for nm, fn, cols in (("US b&h", bench("US"), None), ("GEM L=12", gem(12, "US", "INTL", "BOND"), None)):
    for lab, D in (("month-end exec", R[R.index <= "2026-08-31"]), ("next-day exec", lagged)):
        # signals must still be computed on month-end data: build weights from R, returns from D
        def wrapped(h, fn=fn):
            return fn(R.loc[h.index])
        res = run(nm, D, wrapped, start="1997-06-30")
        for per, (a, b) in {"1997-2010": ("1997", "2010-12-31"), "2011-2026": ("2011", "2026-12-31")}.items():
            x = res.returns[(res.returns.index >= a) & (res.returns.index <= b)]
            m = metrics(x, cash, res.turnover)
            print(f"{nm:9s} {lab:15s} {per}: CAGR {m['CAGR']:.2%} Sharpe {m['Sharpe']:.2f} maxDD {m['maxDD']:.1%}")

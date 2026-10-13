"""Short-term mean reversion on an equity index ETF (daily data).

Train: S&P 500 total return index (^SP500TR, USD) 1990-2010.
Test:  VUSA.L (Vanguard S&P 500 UCITS, GBP line on Trading 212) 2012-06..2026-09.
Signals use the close of day d. Two execution assumptions:
  'same-close' (optimistic: trade in the closing auction at the signal price)
  'next-close' (realistic for a once-a-day job: trade at the next day's close)
Cost: 0.10% one-way per entry/exit. Cash earns the risk-free rate when flat.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data_sources import DATA, french, yahoo
from dataset import build, clean_prices

OUT = DATA.parent / "output"


def rsi(px: pd.Series, n: int) -> pd.Series:
    d = px.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def signal_rsi(px, thr, n=2, trend=200, exit_ma=5):
    """Long when RSI(n)<thr and price>SMA(trend); exit when close>SMA(exit_ma)."""
    r = rsi(px, n)
    sma_t = px.rolling(trend).mean()
    sma_x = px.rolling(exit_ma).mean()
    pos = np.zeros(len(px))
    inpos = False
    for i in range(len(px)):
        if not inpos and r.iloc[i] < thr and px.iloc[i] > sma_t.iloc[i]:
            inpos = True
        elif inpos and px.iloc[i] > sma_x.iloc[i]:
            inpos = False
        pos[i] = 1.0 if inpos else 0.0
    return pd.Series(pos, index=px.index)


def signal_downdays(px, n=3, hold=5):
    down = (px.diff() < 0).astype(int)
    streak = down.groupby((down == 0).cumsum()).cumsum()
    pos = np.zeros(len(px))
    left = 0
    for i in range(len(px)):
        if left > 0:
            left -= 1
        if streak.iloc[i] >= n and left == 0:
            left = hold
        pos[i] = 1.0 if left > 0 else 0.0
    return pd.Series(pos, index=px.index)


def backtest(px, rf_daily, pos_sig, lag, cost=0.001):
    ret = px.pct_change().fillna(0)
    pos = pos_sig.shift(1 + lag).fillna(0)  # position held over day d+1 (+lag)
    trades = pos.diff().abs().fillna(pos.iloc[0])
    r = pos * ret + (1 - pos) * rf_daily.reindex(px.index).fillna(0) - trades * cost
    return r, pos


def stats(r, rf):
    rf = rf.reindex(r.index).fillna(0)
    eq = (1 + r).cumprod()
    yrs = len(r) / 252
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    ex = r - rf
    sh = ex.mean() / ex.std() * np.sqrt(252)
    mdd = (eq / eq.cummax() - 1).min()
    return cagr, sh, mdd


train_px = clean_prices(yahoo("^SP500TR")["adjclose"])
train_px = train_px[(train_px.index >= "1989-01-01") & (train_px.index <= "2010-12-31")]
kf_rf = french("F-F_Research_Data_Factors")["RF"]
rf_us = (kf_rf.resample("D").bfill() / 21).reindex(train_px.index, method="ffill")

test_px = clean_prices(yahoo("VUSA.L")["adjclose"])
test_px = test_px[(test_px.index >= "2012-06-01") & (test_px.index <= "2026-09-30")]
cash_m = build()["CASH"]
rf_uk = (cash_m.resample("D").bfill() / 21).reindex(test_px.index, method="ffill")

configs = {f"RSI2<{t}": (lambda p, t=t: signal_rsi(p, t)) for t in (5, 10, 20)}
configs.update({f"{n} down days, hold 5": (lambda p, n=n: signal_downdays(p, n, 5)) for n in (3, 4)})

rows = []
for name, sig in configs.items():
    for per, px, rf in (("TRAIN 1990-2010", train_px, rf_us), ("TEST 2012-2026", test_px, rf_uk)):
        s = sig(px)
        for lag, lab in ((0, "same-close"), (1, "next-close")):
            r, pos = backtest(px, rf, s, lag)
            r = r[r.index >= ("1990-01-01" if per.startswith("TRAIN") else "2013-01-01")]
            c, sh, mdd = stats(r, rf)
            rows.append({"strategy": name, "period": per, "exec": lab, "CAGR": c, "Sharpe": sh, "maxDD": mdd,
                         "time_in_mkt": pos.reindex(r.index).mean(), "trades_pa": pos.reindex(r.index).diff().abs().sum() / (len(r) / 252)})
    # buy & hold rows
for per, px, rf in (("TRAIN 1990-2010", train_px, rf_us), ("TEST 2012-2026", test_px, rf_uk)):
    r = px.pct_change().dropna()
    r = r[r.index >= ("1990-01-01" if per.startswith("TRAIN") else "2013-01-01")]
    c, sh, mdd = stats(r, rf)
    rows.append({"strategy": "BUY & HOLD", "period": per, "exec": "-", "CAGR": c, "Sharpe": sh, "maxDD": mdd, "time_in_mkt": 1.0, "trades_pa": 0})
T = pd.DataFrame(rows)
T.to_csv(OUT / "mean_reversion.csv", index=False)
print(T.to_string(index=False, formatters={"CAGR": "{:.2%}".format, "Sharpe": "{:.2f}".format, "maxDD": "{:.1%}".format,
                                           "time_in_mkt": "{:.0%}".format, "trades_pa": "{:.0f}".format}))

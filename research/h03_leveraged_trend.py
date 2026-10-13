"""H03 (E009): 3x Nasdaq-100 with a trend filter, vs holding 1x or 3x.

Rule (fixed before running): at each US close, if the Nasdaq-100 is above its N-day simple
moving average, hold the 3x daily-leveraged Nasdaq-100 ETP; otherwise hold cash. The signal
is computed at day t's close and acted on at day t+1's close (one-day lag, realistic for a
bot that runs once a day in London). Pre-registered grid N in {100, 150, 200}.

Synthetic 3x series (the ETP only exists since 2012):
    r3 = 3 * r_index - 2 * (rf + 0.5%/yr financing spread) / 252 - 0.75%/yr OCF / 252
r_index: QQQ adjusted close (total return, net of its 0.20% fee) from 1999-03-11, ^NDX price
index before that (no dividends: slightly conservative). rf: Ken French monthly T-bill rate
spread evenly over the month's trading days. Each switch costs 0.15% (spread) on the traded side.
Validated against the real QQQ3.L (USD line of WisdomTree 3x Nasdaq-100) 2013-2026.

Splits: in-sample 1986-2005 (includes the 2000-02 crash), out-of-sample 2006-2026 (includes 2008,
2020, 2022). Currency: USD (the GBX line adds GBP/USD moves for a UK holder).
Run: python3 h03_leveraged_trend.py   (writes research/output/h03_*.csv)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data_sources import DATA, french, yahoo

OUT = DATA.parent / "output"
OCF, SPREAD_FIN, SWITCH_COST = 0.0075, 0.005, 0.0015
IS = ("1986-01-01", "2005-12-31")
OOS = ("2006-01-01", "2026-10-12")


def index_returns() -> pd.Series:
    ndx = yahoo("^NDX")["close"].pct_change()
    qqq = yahoo("QQQ")["adjclose"].pct_change()
    r = qqq[qqq.index >= "1999-03-11"].combine_first(ndx[ndx.index < "1999-03-11"])
    return r.dropna().rename("r1")


def daily_rf(idx: pd.DatetimeIndex) -> pd.Series:
    rf_m = french("F-F_Research_Data_Factors")["RF"]
    month = idx.to_period("M")
    n = pd.Series(1, index=idx).groupby(month).transform("count")
    m = rf_m.copy()
    m.index = m.index.to_period("M")
    rf = pd.Series(month.map(m).values, index=idx).ffill() / n
    return rf.fillna(rf.ffill().iloc[-1] if rf.notna().any() else 0.0)


def leveraged(r1: pd.Series, rf: pd.Series, k=3) -> pd.Series:
    return k * r1 - (k - 1) * (rf + SPREAD_FIN / 252) - OCF / 252


def strategy(r1, r3, rf, level, N):
    sma = level.rolling(N).mean()
    on = (level > sma).astype(float)
    pos = on.shift(2)  # signal at close t, executed at close t+1, earns t+2 onward
    pos = pos.dropna()
    ret = pos * r3.reindex(pos.index) + (1 - pos) * rf.reindex(pos.index)
    switches = pos.diff().abs().fillna(0)
    ret = ret - switches * SWITCH_COST
    return ret, pos


def stats(r: pd.Series, rf: pd.Series, pos: pd.Series | None = None) -> dict:
    r = r.dropna()
    eq = (1 + r).cumprod()
    yrs = len(r) / 252
    ex = r - rf.reindex(r.index)
    yearly = (1 + r).groupby(r.index.year).prod() - 1
    out = {"start": str(r.index[0].date()), "end": str(r.index[-1].date()), "CAGR": eq.iloc[-1] ** (1 / yrs) - 1,
           "vol": r.std() * np.sqrt(252), "Sharpe": ex.mean() / ex.std() * np.sqrt(252),
           "maxDD": (eq / eq.cummax() - 1).min(), "worst_year": yearly.min(), "best_year": yearly.max(),
           "pct_years_down": (yearly < 0).mean(), "growth_of_100": 100 * eq.iloc[-1]}
    if pos is not None:
        p = pos.reindex(r.index)
        out["time_in_market"] = p.mean()
        out["switches_per_year"] = p.diff().abs().sum() / yrs
    return out


def main():
    r1 = index_returns()
    rf = daily_rf(r1.index)
    r3 = leveraged(r1, rf)
    level = (1 + r1).cumprod()
    rows = []
    for per, (a, b) in {"IS": IS, "OOS": OOS, "FULL": (IS[0], OOS[1])}.items():
        sl = lambda s: s[(s.index >= a) & (s.index <= b)]
        rows.append({"config": "Nasdaq-100 1x hold", "period": per, **stats(sl(r1), rf)})
        rows.append({"config": "3x hold", "period": per, **stats(sl(r3), rf)})
        r1t, p1 = strategy(r1, r1, rf, level, 200)
        rows.append({"config": "1x + SMA200 filter", "period": per, **stats(sl(r1t), rf, p1)})
        for N in (100, 150, 200):
            rt, pos = strategy(r1, r3, rf, level, N)
            rows.append({"config": f"3x + SMA{N} filter", "period": per, **stats(sl(rt), rf, pos)})
    T = pd.DataFrame(rows)
    T.to_csv(OUT / "h03_leveraged_trend.csv", index=False)

    # validation of the synthetic 3x against the real ETP (USD line)
    real = yahoo("QQQ3.L")["adjclose"].pct_change().dropna()
    real = real[(real.abs() < 0.5) & (real.index >= "2013-01-01")]
    j = pd.concat([real, r3], axis=1, keys=["real", "synthetic"]).dropna()
    v = {"days": len(j), "corr": j.real.corr(j.synthetic),
         "real_CAGR": (1 + j.real).prod() ** (252 / len(j)) - 1, "synthetic_CAGR": (1 + j.synthetic).prod() ** (252 / len(j)) - 1}
    pd.DataFrame([v]).to_csv(OUT / "h03_validation.csv", index=False)

    # yearly returns of the main candidates (what a holder would have lived through)
    rt, _ = strategy(r1, r3, rf, level, 200)
    Y = pd.DataFrame({"Nasdaq 1x": r1, "3x hold": r3, "3x + SMA200": rt}).dropna()
    Y = (1 + Y).groupby(Y.index.year).prod() - 1
    Y.to_csv(OUT / "h03_yearly.csv")

    pd.set_option("display.width", 250)
    cols = ["config", "period", "start", "CAGR", "Sharpe", "maxDD", "worst_year", "best_year", "growth_of_100", "time_in_market", "switches_per_year"]
    print(T[cols].round(3).to_string(index=False))
    print("validation:", {k: round(x, 4) if isinstance(x, float) else x for k, x in v.items()})
    print(Y.round(3).tail(22).to_string())


if __name__ == "__main__":
    main()

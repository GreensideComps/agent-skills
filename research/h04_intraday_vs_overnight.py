"""H04 (E010): does LQQ3 earn its return while London is open, or overnight?

Splits each day's LQQ3.L return into open->close (London session) and close->next open
(overnight, which includes the US afternoon). Owner asked for a flat-at-every-close system;
this measures what that rule gives up. Costs: 0.15% per side on each daily round trip.
Data: Yahoo daily OHLC for LQQ3.L 2013-2026 (days with |move| > 35% dropped as feed glitches),
QQQ adjusted close for the 100-day trend signal (known before the London open).
Run: python3 h04_intraday_vs_overnight.py   (writes research/output/h04_intraday_vs_overnight.csv)
"""
import pandas as pd

from data_sources import DATA, yahoo

COST = 0.0015
d = yahoo("LQQ3.L")
d = d[d.index >= "2013-01-01"].copy()
for c in ("open", "close"):
    d[c] = d[c].where(d[c] > 0)
d = d.dropna(subset=["open", "close"])
oc, co = d.close / d.open - 1, d.open / d.close.shift(1) - 1
ok = (oc.abs() < 0.35) & (co.abs() < 0.35)
oc, co = oc[ok], co[ok]
q = yahoo("QQQ")["adjclose"]
on = (q > q.rolling(100).mean()).reindex(d.index, method="ffill").shift(1).fillna(False).astype(bool).reindex(oc.index)


def cagr(r):
    r = r.dropna()
    return (1 + r).prod() ** (252 / len(r)) - 1


def mdd(r):
    e = (1 + r.dropna()).cumprod()
    return (e / e.cummax() - 1).min()


rows = {"open_to_close_every_day": oc - 2 * COST, "open_to_close_trend_on_only": (oc - 2 * COST).where(on, 0.0),
        "open_to_close_no_costs": oc, "overnight_only": co, "close_to_close_hold": d.close.pct_change()[ok]}
out = pd.DataFrame([{"rule": k, "CAGR": cagr(r), "maxDD": mdd(r), "avg_daily": r.mean(), "days": int(r.notna().sum()),
                     "start": str(oc.index[0].date()), "end": str(oc.index[-1].date())} for k, r in rows.items()])
out.to_csv(DATA.parent / "output" / "h04_intraday_vs_overnight.csv", index=False)
print(out.round(4).to_string(index=False))

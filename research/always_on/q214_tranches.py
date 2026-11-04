"""Q214: pick1 screener in 12 overlapping monthly sleeves. Prereg prereg/Q214.md."""
import sys, math, statistics
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stock_screener"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pick1 as P

df = P.load(); df = df[df["month"] <= "2022-12-31"]
months = sorted(pd.Timestamp(m) for m in df["month"].unique())
by = {m: g for m, g in df.groupby("month")}

def picks(min_cap):
    out = {}
    for m in months:
        if m < pd.Timestamp("2014-12-31") or m > pd.Timestamp("2021-12-31"): continue
        u = P.universe(by[m], min_cap)
        if len(u) < 50: continue
        out[m] = list(P.pick(u)["cik"])
    return out

def run(PK, hold=12, cost=P.COST, lag=0, start="2015-01-31", min_cap=2e9):
    rows = []
    form = sorted(PK)
    for m in months:
        nxt = m + pd.offsets.MonthEnd(1)
        if nxt < pd.Timestamp(start) or nxt > pd.Timestamp("2022-12-31"): continue
        g = by[m]
        # active sleeves: formed at f with f+lag <= m < f+lag+hold (months)
        act = [f for f in form if 0 <= (m.year*12+m.month) - (f.year*12+f.month) - lag < hold]
        if not act: continue
        r = g.set_index("cik")["ret_next"]
        sr = [r.reindex(PK[f]).fillna(0).mean() for f in act]
        port = float(np.mean(sr))
        # turnover: sleeve entering this month vs sleeve leaving
        ent = [f for f in act if (m.year*12+m.month)-(f.year*12+f.month)-lag == 0]
        turn = 0.0
        if ent:
            new = set(PK[ent[0]])
            old_f = [f for f in form if (m.year*12+m.month)-(f.year*12+f.month)-lag == hold]
            old = set(PK[old_f[0]]) if old_f else set()
            turn = (len(new - old) / len(new)) * (len(act) and 1/len(act) if not old else 1/hold) if new else 0
        ur = P.universe(g, 2e9)["ret_next"].dropna().mean()
        rows.append({"month": nxt, "ex": port - 2*cost*turn - ur, "gross": port - ur, "n": len(act)})
    return pd.DataFrame(rows).set_index("month")

def st(x, N=427):
    s = P.stats(x); s["dsr"] = P.dsr(s, N); return s

PK = picks(2e9)
T1 = run(PK)
full = T1[T1["n"] == 12]["ex"]
print("T1 all", {k: round(v, 4) for k, v in st(T1["ex"]).items()})
print("T1 full-12", {k: round(v, 4) for k, v in st(full).items()})
x = T1["ex"]; th = np.array_split(x, 3); print("T2 thirds", [round(t.mean()*12, 4) for t in th])
ur = pd.Series({m + pd.offsets.MonthEnd(1): P.universe(by[m], 2e9)["ret_next"].dropna().mean() for m in months})
bull = ur.reindex(x.index) > 0
print("T3 bull/bear", round(x[bull].mean()*12, 4), round(x[~bull].mean()*12, 4))
print("T4 6m", round(run(PK, hold=6)["ex"].mean()*12, 4))
PK5 = picks(5e9); print("T5 5bn", round(run(PK5, min_cap=5e9)["ex"].mean()*12, 4))
print("T6 costx2", round(run(PK, cost=2*P.COST)["ex"].mean()*12, 4), "lag1", round(run(PK, lag=1)["ex"].mean()*12, 4))
print("avg monthly turnover-cost drag/yr", round((T1["gross"]-T1["ex"]).mean()*12, 4))

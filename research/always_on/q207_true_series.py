"""Q207 diagnostic: rebuild Q206 with real monthly holdings (no smoothing). Not a new trial; Q206 verdict stays FAIL."""
import sys, math, runpy
from pathlib import Path
import numpy as np, pandas as pd
sys.argv = [sys.argv[0]]
src = open(Path(__file__).with_name("q206_buyback_cheap.py")).read().split("T1 = report(")[0]
ns = {"__file__": str(Path(__file__).with_name("q206_buyback_cheap.py"))}; exec(compile(src, "q206", "exec"), ns)
df, dsr = ns["df"], ns["dsr"]
COST = 0.003
def series(min_cap=2e9, hold=6, cost=COST, lag=0):
    months = sorted(df["month"].unique())
    U = {}  # month -> (universe ciks, EW next-month return)
    sels = {}
    for t in months:
        if t < pd.Timestamp("2014-12-01") or t > pd.Timestamp("2022-11-30"): continue
        m = df[(df["month"] == t) & df["ok_l1"]]
        sic = m["sic"].fillna(0)
        u = m[(m["mcap_l1"] >= min_cap) & (m["close_raw"] >= 5) & ~sic.between(6000, 6799) & ~sic.between(4900, 4999)].dropna(subset=["f1"])
        if len(u) < 50: continue
        U[t] = (u.set_index("cik")["f1"], u["f1"].mean())
        uu = u.dropna(subset=["fcf_ev", "bby"])
        good = (uu["fcf"] > 0) & (uu["ttm_operating_income"] > 0) & (uu["fcf_ev"] >= uu["fcf_ev"].quantile(0.7)) & (uu["nd_ebitda"] < 3) & (uu["sh_chg"] < 0)
        sels[t] = list(uu[(uu["bby"] >= uu["bby"].quantile(0.9)) & good]["cik"])
    ms = sorted(U)
    out = {}
    for j, t in enumerate(ms):
        pos = []
        for k in range(lag, hold + lag):
            if j - k >= 0: pos += [(c, k == lag, k == hold + lag - 1) for c in sels.get(ms[j - k], [])]
        if not pos: out[t] = 0.0; continue
        r, ew = U[t]
        ex = [(r.get(c, np.nan) - ew) - (cost if first else 0) - (cost if last else 0) for c, first, last in pos]
        ex = [x for x in ex if not np.isnan(x)]
        out[t] = float(np.mean(ex)) if ex else 0.0
    return pd.Series(out)
for name, kw in [("T1 full", {}), ("costs x2", {"cost": 2 * COST}), ("lag 1m", {"lag": 1}), (">=10bn", {"min_cap": 1e10})]:
    s = series(**kw); sr, d = dsr(s, 423)
    th = [round(x.mean() * 1200, 2) for x in np.array_split(s, 3)]
    print(f"{name}: {s.mean()*1200:+.2f}%/yr  vol {s.std()*math.sqrt(12)*100:.1f}%  SRm {sr:.3f}  DSR {d:.4f}  thirds {th}")

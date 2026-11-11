"""Q175 region minimum variance. Prereg: /mnt/project-files/research/always-on/prereg/Q175.md."""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from q08_fomc import tstat
from q44_q48_timing import section, summ
END = pd.Period("2022-12", "M")

def mkt(f):
    s = section(f); return (s["Mkt-RF"] + s["RF"])
R = pd.DataFrame({"us": mkt("F-F_Research_Data_Factors.csv"), "eu": mkt("Europe_3_Factors.csv"), "jp": mkt("Japan_3_Factors.csv"),
                  "ap": mkt("Asia_Pacific_ex_Japan_3_Factors.csv"), "em": mkt("Emerging_5_Factors.csv")}).dropna()
R = R[R.index <= END]
dv = mkt("Developed_ex_US_3_Factors.csv").reindex(R.index)

def minvar(S, it=3000):
    n = len(S); w = np.ones(n) / n; lr = 0.5 / np.max(np.linalg.eigvalsh(S))
    for _ in range(it):
        w = w - lr * 2 * S @ w
        u = np.sort(w)[::-1]; c = np.cumsum(u) - 1; k = np.nonzero(u - c / np.arange(1, n + 1) > 0)[0][-1]
        w = np.maximum(w - c[k] / (k + 1), 0)
    return w

def run(win=36, lag=0, cost=0.001):
    out, prev, W = [], None, None
    for t in R.index:
        if t.month == 1:
            hist = R[R.index < t - 12 * lag].tail(win)
            if len(hist) == win:
                W = minvar(np.cov(hist.values.T))
                turn = 1.0 if prev is None else np.abs(W - prev).sum() / 2
                prev = W
            else:
                turn = 0
        else:
            turn = 0
        if W is not None:
            out.append((t, float(R.loc[t].values @ W) - turn * cost, float(R.loc[t].mean()), float(0.6 * R.loc[t, "us"] + 0.3 * dv.loc[t] + 0.1 * R.loc[t, "em"])))
    d = pd.DataFrame(out, columns=["t", "mv", "ew", "p60"]).set_index("t")
    return d

d = run(); ex = d["mv"] - d["ew"]
r = summ(ex, d["ew"])
since = ex[ex.index >= pd.Period("2007-01", "M")]
dd = lambda x: float(((1 + x).cumprod() / (1 + x).cumprod().cummax() - 1).min())
r.update(since2007=float(since.mean()*12), t_since2007=tstat(since),
         lag1y=float((run(lag=1)["mv"] - run(lag=1)["ew"]).mean()*12), cost2=float((run(cost=0.002)["mv"] - d["ew"]).mean()*12),
         win60=float((run(win=60)["mv"] - run(win=60)["ew"]).mean()*12),
         vs6030=float((d["mv"] - d["p60"]).mean()*12), vol_mv=float(d["mv"].std()*12**.5), vol_ew=float(d["ew"].std()*12**.5),
         vol_6030=float(d["p60"].std()*12**.5), dd_mv=dd(d["mv"]), dd_ew=dd(d["ew"]), dd_6030=dd(d["p60"]),
         cagr_mv=float((1+d["mv"]).prod()**(12/len(d))-1), cagr_ew=float((1+d["ew"]).prod()**(12/len(d))-1), cagr_6030=float((1+d["p60"]).prod()**(12/len(d))-1))
r["pass"] = bool(r["t"] >= 3.5 and r["ex_ann"] > 0 and min(r["halves"]) > 0 and r["since2007"] > 0 and r["t_since2007"] >= 2.5)
print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
Path(sys.argv[1]).write_text(json.dumps({"Q175a": r}, indent=1))

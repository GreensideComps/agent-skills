"""Q157 industry 1-month reversal. Pre-registration: /mnt/project-files/research/always-on/prereg/Q157.md."""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from q08_fomc import tstat
from q44_q48_timing import COST, section, summ
from q81_q83 import pick_top
END = pd.Period("2022-12", "M")

def run(name, k, lag=0, cost=COST, every=1):
    ind = section(name); ind = ind[ind.index <= END].where(ind > -0.99)
    ew = ind.mean(axis=1)
    s = pick_top(-ind.shift(lag), ind, k, cost, every)
    return (s - ew.reindex(s.index)).dropna(), ew

ex, ew = run("49_Industry_Portfolios.csv", 5)
r = summ(ex, ew)
since = ex[ex.index >= pd.Period("2007-01", "M")]
r.update(since2007=float(since.mean()*12), t_since2007=tstat(since),
         lag1=float(run("49_Industry_Portfolios.csv", 5, lag=1)[0].mean()*12),
         cost2=float(run("49_Industry_Portfolios.csv", 5, cost=2*COST)[0].mean()*12),
         quarterly=float(run("49_Industry_Portfolios.csv", 5, every=3)[0].mean()*12),
         ind12=float(run("12_Industry_Portfolios.csv", 2)[0].mean()*12))
r["pass"] = bool(r["t"] >= 3.5 and r["ex_ann"] > 0 and min(r["halves"]) > 0 and r["since2007"] > 0 and r["t_since2007"] >= 2.5)
print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
Path(sys.argv[1]).write_text(json.dumps({"Q157a": r}, indent=1))

"""Q153 bond curve carry timing. Pre-registration: /mnt/project-files/research/always-on/prereg/Q153.md."""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from q44_q48_timing import summ, tstat
F = "/mnt/project-files/research-data/fred/"

def ld(n):
    d = pd.read_csv(F + n + ".csv"); d.index = pd.PeriodIndex(pd.to_datetime(d["observation_date"]), freq="M")
    return pd.to_numeric(d[n], errors="coerce")

y = ld("GS10") / 100; b = ld("TB3MS") / 100
df = pd.DataFrame({"y": y, "b": b}).dropna()
df = df[df.index <= pd.Period("2022-12", "M")]
y0 = df["y"].shift(1)
D = (1 - (1 + y0 / 2) ** -20) / y0
bond = y0 / 12 - D * (df["y"] - y0)
bill = df["b"].shift(1) / 12
spread = (df["y"] - df["b"]) * 100  # percentage points

def run(th, lag=0, cost=0.001):
    w = (spread > th).astype(float).shift(1 + lag)
    turn = w.diff().abs()
    r = w * bond + (1 - w) * bill - turn * cost
    return (r - bond).dropna()

res = {}
for tid, th in (("Q153a", 1.0), ("Q153b", 0.0)):
    ex = run(th); s = summ(ex, bond)
    since = ex[ex.index >= pd.Period("2007-01", "M")]
    s.update(since2007=float(since.mean() * 12), t_since2007=tstat(since),
             lag1=float(run(th, lag=1).mean() * 12), cost2=float(run(th, cost=0.002).mean() * 12),
             pct_bonds=float((spread > th).mean()))
    s["pass"] = bool(s["t"] >= 3.5 and s["ex_ann"] > 0 and min(s["halves"]) > 0 and s["since2007"] > 0 and s["t_since2007"] >= 2.5)
    res[tid] = s
    print(tid, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items()})
Path(sys.argv[1]).write_text(json.dumps(res, indent=1))

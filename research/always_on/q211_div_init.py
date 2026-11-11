"""Q211 dividend initiation. Prereg /mnt/project-files/research/always-on/prereg/Q211.md. Exploration only (<= 2022-12-31)."""
import sys, math
from pathlib import Path
from statistics import NormalDist
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stock_screener"))
import pick1
N = 426; COST = 0.003; ND = NormalDist()
df = pick1.load(); df = df[df["month"] <= "2022-12-31"].copy()
df = df.sort_values(["cik", "month"]).reset_index(drop=True)
g = df.groupby("cik"); df["mi"] = df["month"].dt.year * 12 + df["month"].dt.month
df["f1"] = (g["px"].shift(-1) / df["px"] - 1).where(g["mi"].shift(-1) - df["mi"] == 1)
sic = df["sic"].fillna(0)
univ = df[(df["mcap"] >= 2e9) & (df["close_raw"] >= 5) & ~sic.between(6000, 6799) & ~sic.between(4900, 4999)]
ew = univ.groupby("month")["f1"].mean()
dv = df["ttm_dividends_paid"].abs().fillna(0)
df["paid"] = dv > 0
df["zero24"] = g["paid"].transform(lambda x: x.shift(1).rolling(24, min_periods=24).sum()) == 0
df["init"] = df["paid"] & df["zero24"] & df["ttm_revenue"].notna()
R = df.set_index(["cik", "month"])["f1"]
def entries(k_month=1, min_cap=1e9):
    sc = df["sic"].fillna(0)
    e = df[df["init"] & (df["mcap"] >= min_cap) & (df["close_raw"] >= 5) & ~sc.between(6000, 6799) & ~sc.between(4900, 4999)
           & df["month"].between("2014-01-01", "2021-12-31")]
    return [(c, t + pd.offsets.MonthEnd(k_month - 1)) for c, t in zip(e.cik, e.month)]
def series(E, hold=12, cost=COST):
    months = ew.loc["2014-01-31":"2022-11-30"].index
    pos = {m: [] for m in months}
    for c, t in E:
        hm = [m for m in months if m >= t][:hold]
        for j, m in enumerate(hm): pos[m].append((c, j == 0, j == len(hm) - 1))
    s = {}
    for m in months:
        xs = []
        for c, first, last in pos[m]:
            r = R.get((c, m), np.nan)
            if np.isnan(r): continue
            xs.append(r - ew[m] - (cost if first else 0) - (cost if last else 0))
        s[m] = np.mean(xs) if xs else 0.0
    return pd.Series(s)
def trade(E, hold=12, cost=COST):
    out = []
    for c, t in E:
        hm = [m for m in ew.index if m >= t][:hold]
        if len(hm) < hold: continue
        r = [R.get((c, m), np.nan) for m in hm]
        if np.isnan(r).any(): r = [x for x in r if not np.isnan(x)]
        out.append((t, np.prod([1 + x for x in r]) - np.prod([1 + ew[m] for m in hm[:len(r)]]) - 2 * cost))
    return pd.DataFrame(out, columns=["t", "net"])
def dsr(x):
    T = len(x); sr = x.mean() / x.std(); g_ = 0.5772
    em = math.sqrt(1 / T) * ((1 - g_) * ND.inv_cdf(1 - 1 / N) + g_ * ND.inv_cdf(1 - 1 / (N * math.e)))
    return sr, ND.cdf((sr - em) * math.sqrt(T - 1))
def show(name, E, **kw):
    s = series(E, **kw); sr, d = dsr(s); tr = trade(E, **kw)
    th = [round(x.mean() * 1200, 1) for x in np.array_split(s, 3)]
    t = tr.net.mean() / tr.net.std() * math.sqrt(len(tr)) if len(tr) > 1 else float("nan")
    print(f"{name}: spinoffs {len(E)} trades {len(tr)} net/trade {tr.net.mean()*100:+.2f}% (t {t:.2f}) hit {(tr.net>0).mean()*100:.0f}% | port {s.mean()*1200:+.2f}%/yr SRm {sr:.3f} DSR {d:.4f} thirds {th}")
    return tr
E = entries(); print("initiations", len(E)); T1 = show("T1 full", E)
show("T4 6m hold", E, hold=6); show("T5 entry mcap>=5bn", entries(min_cap=5e9))
show("T6 costs x2", E, cost=2 * COST); show("T6 entry 1m later", entries(k_month=2))
lvl = (1 + ew.fillna(0)).cumprod(); bull = lvl > lvl.rolling(10).mean()
T1["bull"] = T1.t.map(bull)
for k, v in T1.groupby("bull"): print(f"T3 bull={k}: {len(v)} trades net {v.net.mean()*100:+.2f}%")
print("by entry year:", T1.groupby(T1.t.dt.year).net.agg(["count", "mean"]).round(3).to_dict("index"))

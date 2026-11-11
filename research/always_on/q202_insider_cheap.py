"""Q202 insider cluster buying in cheap names. Prereg /mnt/project-files/research/always-on/prereg/Q202.md. Exploration only."""
import sys, math
from pathlib import Path
from statistics import NormalDist
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stock_screener"))
import pick1
N = 421; COST = 0.003; ND = NormalDist()

df = pick1.load()
df = df[df["month"] <= "2022-12-31"].copy()
ins = pd.read_csv(pick1.DATA / "insider_trades.csv.gz", usecols=["issuer_cik", "filed", "owner_cik", "code"])
ins = ins[ins["code"] == "P"].copy(); ins["month"] = pd.to_datetime(ins["filed"]) + pd.offsets.MonthEnd(0)
ins = ins[ins["month"] <= "2022-12-31"]
cl = ins.groupby(["issuer_cik", "month"])["owner_cik"].nunique().rename("n_ins").reset_index().rename(columns={"issuer_cik": "cik"})
df = df.merge(cl, on=["cik", "month"], how="left"); df["n_ins"] = df["n_ins"].fillna(0)
df["near_low"] = df["n_ins"] >= 2
g = df.groupby("cik")
mi = df["month"].dt.year * 12 + df["month"].dt.month
df["mi"] = mi
df["r1"] = df["px"] / g["px"].shift(1) - 1
df["mcap_l1"] = g["mcap"].shift(1)
for h in (1, 2, 3, 4, 5, 6, 7):
    f = g["px"].shift(-h); fm = g["mi"].shift(-h)
    df[f"f{h}"] = (f / df["px"] - 1).where(fm - df["mi"] == h)
# lag entry: buy at t+1 close, hold 3m
df["lag6"] = (g["px"].shift(-7) / g["px"].shift(-1) - 1).where(g["mi"].shift(-7) - df["mi"] == 7)

df["ok_l1"] = (df["mi"] - g["mi"].shift(1)) == 1

def run(min_cap=2e9, hold=6, cost=COST, col=None, ctrl=False):
    col = col or f"f{hold}"
    trades, cohorts = [], {}
    months = sorted(df["month"].unique())
    for t in months:
        if t < pd.Timestamp("2014-12-01") or t > pd.Timestamp("2022-12-31") - pd.DateOffset(months=hold):
            continue
        m = df[(df["month"] == t) & df["ok_l1"]]
        sic = m["sic"].fillna(0)
        u = m[(m["mcap_l1"] >= min_cap) & (m["close_raw"] >= 5) & ~sic.between(6000, 6799) & ~sic.between(4900, 4999)]
        u = u.dropna(subset=[col])
        if len(u) < 50: continue
        bench = u[col].mean()
        thr = u["fcf_ev"].quantile(0.7)
        good = (u["fcf"] > 0) & (u["ttm_operating_income"] > 0) & (u["fcf_ev"] >= thr)
        sel = u[u["near_low"] & (~good if ctrl else good)]
        for _, r in sel.iterrows():
            trades.append((t, r[col] - bench - 2 * cost, r[col] - bench))
        if len(sel):
            cohorts[t] = (sel[col].mean() - bench - 2 * cost)
    tr = pd.DataFrame(trades, columns=["t", "net", "gross"])
    # monthly portfolio: each cohort spreads its excess evenly over its hold months, weight 1/hold
    idx = pd.date_range("2015-01-31", "2022-12-31", freq="ME")
    pm = pd.Series(0.0, index=idx)
    for t, x in cohorts.items():
        mr = (1 + x) ** (1 / hold) - 1
        for k in range(1, hold + 1):
            d = (pd.Timestamp(t) + pd.offsets.MonthEnd(k))
            if d in pm.index: pm[d] += mr / hold
    return tr, pm

def dsr(x, n=N):
    T = len(x); sr = x.mean() / x.std()
    g_ = 0.5772
    emax = math.sqrt(1 / T) * ((1 - g_) * ND.inv_cdf(1 - 1 / n) + g_ * ND.inv_cdf(1 - 1 / (n * math.e)))
    return sr, ND.cdf((sr - emax) * math.sqrt(T - 1))

def report(name, tr, pm):
    sr, d = dsr(pm)
    th = [pm.iloc[i * len(pm) // 3:(i + 1) * len(pm) // 3].mean() * 12 for i in range(3)]
    t = tr["net"].mean() / (tr["net"].std() / math.sqrt(len(tr))) if len(tr) > 1 else float("nan")
    print(f"{name}: trades {len(tr)}, trade gross {tr['gross'].mean()*100:+.2f}% net {tr['net'].mean()*100:+.2f}% (t {t:.2f}), "
          f"hit {(tr['net']>0).mean()*100:.0f}%, port {pm.mean()*1200:+.2f}%/yr SRm {sr:.3f} DSR {d:.4f}, thirds {[round(x*100,2) for x in th]}")
    return tr, pm

T1 = report("T1 full", *run())
report("control (cluster buy, not cheap)", *run(ctrl=True))
report("T4 3m hold", *run(hold=3))
report("T5 >=10bn", *run(min_cap=1e10))
report("T6 costs x2", *run(cost=2 * COST))
report("T6 lag entry", *run(col="lag6"))
# T3 bull/bear by universe trend
tr = T1[0].copy()
ew = df[(df["mcap"] >= 2e9)].groupby("month")["r1"].mean().sort_index()
lvl = (1 + ew.fillna(0)).cumprod(); bull = lvl > lvl.rolling(10).mean()
tr["bull"] = tr["t"].map(bull)
for k, v in tr.groupby("bull"): print(f"T3 bull={k}: trades {len(v)} net {v['net'].mean()*100:+.2f}%")
print("by year:", tr.groupby(tr["t"].dt.year)["net"].agg(["count", "mean"]).round(4).to_dict("index"))

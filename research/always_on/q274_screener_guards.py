"""Q274 peak-cycle guards for pick-1 (prereg research/always_on/prereg/Q274.md). Exploration 2015-2022 only."""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stock_screener'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
import pick1 as p1

def add_guards(df):
    df = df.sort_values(["cik", "month"]).copy()
    g = df.groupby("cik")
    df["om"] = (df["ttm_operating_income"] / df["ttm_revenue"]).where(df["ttm_revenue"] > 0)
    med = g["om"].transform(lambda s: s.shift(1).rolling(60, min_periods=24).median())
    df["G1"] = ~((df["om"] > 1.5 * med) & (med > 0)) & med.notna()
    oi = df["ttm_operating_income"]; o12 = g["ttm_operating_income"].shift(12); o24 = g["ttm_operating_income"].shift(24)
    trio = pd.concat([oi, o12, o24], axis=1)
    cv = trio.std(axis=1) / trio.mean(axis=1).abs()
    df["G2"] = (o12 > 0) & (o24 > 0) & (cv < 0.5)
    return df

ORIG_SCORE = p1.score
def make_score(use):
    def score(u):
        u = u.copy()
        if "G3" in use:
            cap = u["mom"].quantile(0.95)
            u = u[~(u["mom"] > cap)]
        for k in ("G1", "G2"):
            if k in use:
                u = u[u[k].fillna(False)]
        return ORIG_SCORE(u)
    return score

df = p1.load(); df = df[df["month"] <= "2022-12-31"]; df = add_guards(df)
res = {}
runs = {}
for name, use in {"base": (), "Q274a": ("G1", "G2", "G3"), "G1": ("G1",), "G2": ("G2",), "G3": ("G3",)}.items():
    p1.score = make_score(use)
    b = p1.backtest(df); runs[name] = b
p1.score = ORIG_SCORE
base = runs["base"]
def dd(x):
    idx = (1 + x).cumprod(); return float((idx / idx.cummax() - 1).min())
for name, b in runs.items():
    ex = b["port"] - b["univ"]
    d = (b["port"] - base["port"]).dropna()
    h1 = d[d.index < "2019-01-01"]; h2 = d[d.index >= "2019-01-01"]
    res[name] = {"ex_vs_univ_ann_pct": ex.mean() * 1200, "port_cagr_pct": ((1 + b["port"]).prod() ** (12 / len(b)) - 1) * 100,
                 "minus_base_ann_pct": d.mean() * 1200, "minus_base_t": d.mean() / d.std() * len(d) ** 0.5 if d.std() > 0 else 0,
                 "half1_pct": h1.mean() * 1200, "half2_pct": h2.mean() * 1200,
                 "maxdd_pct": dd(b["port"]) * 100, "worst12_vs_univ_pct": ((1 + b["port"]).rolling(12).apply(np.prod) - (1 + b["univ"]).rolling(12).apply(np.prod)).min() * 100,
                 "te_vs_base_pct": d.std() * 12 ** 0.5 * 100}
# names removed each rebalance and their next-12m return
rem = []
for y, g in base.groupby(base.index.year):
    bn = set(g["names"].iloc[0].split(",")); qn = set(runs["Q274a"].loc[runs["Q274a"].index.year == y, "names"].iloc[0].split(","))
    rem.append({"year": int(y), "dropped": sorted(bn - qn), "added": sorted(qn - bn)})
res["swaps"] = rem
a, b0 = res["Q274a"], res["base"]
res["adopt"] = bool(a["minus_base_ann_pct"] >= -0.5 and a["half1_pct"] >= -1 and a["half2_pct"] >= -1
                    and a["worst12_vs_univ_pct"] >= b0["worst12_vs_univ_pct"] and a["maxdd_pct"] >= b0["maxdd_pct"])
print(json.dumps(res, indent=1, default=float))
json.dump(res, open('/mnt/project-files/research/always-on/results/Q274.json', 'w'), indent=1, default=float)

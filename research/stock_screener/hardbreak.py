"""Q201: pick-1 yearly rebalance + interim hard-break exits. Prereg /mnt/project-files/research/always-on/prereg/Q201.md."""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pick1 as p1

STOP = 0.75


def gated(u):
    return set(u[(u["fcf"] > 0) & (u["ttm_operating_income"] > 0) & (u["nd_ebitda"] < 3)
                 & (u["sh_chg"] <= 0.02) & (u["equity"] > 0)]["cik"])


def backtest(df, start="2015-01-31", end="2022-12-31", min_cap=2e9, lag=0, cost=p1.COST, stop=STOP):
    months = [pd.Timestamp(m) for m in sorted(df["month"].unique())]
    by = {m: g for m, g in df.groupby("month")}
    rows, held, entry = [], [], {}
    reb = 12 if lag == 0 else 1
    for i, m in enumerate(months):
        if m < pd.Timestamp(start) - pd.offsets.MonthEnd(1) or m >= pd.Timestamp(end):
            continue
        g = by[m]; u = p1.universe(g, min_cap)
        px = dict(zip(g["cik"], g["adjclose"]))
        traded = 0
        if m.month == reb or not held:
            new = list(p1.pick(u)["cik"])
            traded = len(set(new) - set(held)) * (2 if held else 1)
            for c in new:
                if c not in held:
                    entry[c] = px.get(c)
            held = new
        else:
            gu = p1.universe(by[months[i - 1]], min_cap) if lag else u
            ok = gated(gu)
            out = [c for c in held if c not in ok or c not in px
                   or (entry.get(c) and px.get(c) and px[c] <= stop * entry[c])]
            if out:
                keep = [c for c in held if c not in out]
                s = p1.score(gu); per = {}
                for c in keep:
                    k = s.loc[s["cik"] == c, "sic2"]
                    if len(k): per[k.iloc[0]] = per.get(k.iloc[0], 0) + 1
                add = []
                for c, k in zip(s["cik"], s["sic2"]):
                    if len(keep) + len(add) >= p1.TOP: break
                    if c in keep or c in out or per.get(k, 0) >= p1.PER_SIC: continue
                    per[k] = per.get(k, 0) + 1; add.append(c); entry[c] = px.get(c)
                traded = len(out) + len(add); held = keep + add
        h = g[g["cik"].isin(held)]
        if not len(h): continue
        pr = h["ret_next"].fillna(0).mean(); ur = u["ret_next"].dropna().mean()
        rows.append({"month": m + pd.offsets.MonthEnd(1), "port": pr - cost * traded / p1.TOP, "port_gross": pr,
                     "univ": ur, "traded": traded})
    return pd.DataFrame(rows).set_index("month")


def run(out: Path):
    df = p1.load(); df = df[df["month"] <= "2022-12-31"]
    fx = p1.gbp_factor(); vw = p1.vwrp_monthly()
    gbp = lambda r: (1 + r) * fx.shift(1).reindex(r.index) / fx.reindex(r.index) - 1
    main = backtest(df); e1 = main["port"] - main["univ"]; e2 = gbp(main["port"]) - vw.reindex(main.index)
    n = p1.reg.n_trials(p1.reg.load()) + p1.N_EXTRA; s1 = p1.stats(e1)
    thirds = [float(c.mean() * 12) for c in np.array_split(e1, 3)]
    views = {k: p1.stats((lambda b: b["port"] - b["univ"])(backtest(df, **kw))) for k, kw in {
        "T5_large_only": dict(min_cap=10e9), "T6_cost2": dict(cost=2 * p1.COST), "T6_lag1": dict(lag=1),
        "no_crash_guard": dict(stop=0.0), "guard_35pct": dict(stop=0.65)}.items()}
    res = {"n_trials": n, "B1_vs_universe": s1, "dsr": p1.dsr(s1, n), "B2_vs_vwrp_gbp": p1.stats(e2),
           "portfolio_cagr_gbp": float((1 + gbp(main["port"])).prod() ** (12 / len(main)) - 1),
           "T2_thirds_ann": thirds, **views, "names_traded_per_year": float(main["traded"].mean() * 12),
           "gross_minus_univ_ann": float((main["port_gross"] - main["univ"]).mean() * 12)}
    res["use_live"] = bool(s1["ann"] >= 0.030 and views["T6_lag1"]["ann"] > 0)
    out.write_text(json.dumps(res, indent=1)); return res


if __name__ == "__main__":
    r = run(Path(sys.argv[1]))
    print({k: (round(v["ann"], 4), round(v["t_nw"] or 0, 2)) if isinstance(v, dict) else v for k, v in r.items()})

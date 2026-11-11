"""Q200: pick-1 with a monthly review and sell discipline. Prereg /mnt/project-files/research/always-on/prereg/Q200.md.
Usage: python review.py backtest OUT.json | python review.py live YYYY-MM HELD_TICKERS_CSV OUT.csv"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pick1 as p1

KEEP_PCT = 0.30


def review(u: pd.DataFrame, held: list) -> tuple[list, list, list]:
    """Returns (new_held, sold, bought) cik lists for one month."""
    s = p1.score(u)
    cut = max(int(len(s) * KEEP_PCT), p1.TOP)
    keep_ok = set(s["cik"].iloc[:cut])
    keep = [c for c in held if c in keep_ok]
    sold = [c for c in held if c not in keep_ok]
    sic = dict(zip(s["cik"], s["sic2"]))
    per = {}
    for c in keep:
        per[sic[c]] = per.get(sic[c], 0) + 1
    bought = []
    for c, k in zip(s["cik"], s["sic2"]):
        if len(keep) + len(bought) >= p1.TOP:
            break
        if c in keep or c in bought or per.get(k, 0) >= p1.PER_SIC:
            continue
        per[k] = per.get(k, 0) + 1
        bought.append(c)
    return keep + bought, sold, bought


def backtest(df, start="2015-01-31", end="2022-12-31", min_cap=2e9, lag=0, cost=p1.COST, every=1):
    months = [pd.Timestamp(m) for m in sorted(df["month"].unique())]
    by = {m: g for m, g in df.groupby("month")}
    rows, held = [], []
    for i, m in enumerate(months):
        if m < pd.Timestamp(start) - pd.offsets.MonthEnd(1) or m >= pd.Timestamp(end):
            continue
        g = by[m]
        u = p1.universe(g, min_cap)
        # lag: decide on last month's data
        ud = p1.universe(by[months[i - 1]], min_cap) if lag and i > 0 else u
        traded = 0
        if (i % every == 0 or not held) and len(ud) >= 50:
            new, sold, bought = review(ud, held)
            traded = len(bought) + len(sold)
            if not held:
                traded = len(new)
            held = new
        h = g[g["cik"].isin(held)]
        if not len(h):
            continue
        pr = h["ret_next"].fillna(0).mean()
        ur = u["ret_next"].dropna().mean()
        c = cost * traded / p1.TOP  # each traded name is 1/15 of the book, one leg each
        rows.append({"month": m + pd.offsets.MonthEnd(1), "port": pr - c, "port_gross": pr, "univ": ur,
                     "turn": traded / p1.TOP, "n": len(h)})
    return pd.DataFrame(rows).set_index("month")


def run_backtest(out: Path):
    df = p1.load(); df = df[df["month"] <= "2022-12-31"]
    fx = p1.gbp_factor(); vw = p1.vwrp_monthly()
    gbp = lambda r: (1 + r) * fx.shift(1).reindex(r.index) / fx.reindex(r.index) - 1
    main = backtest(df)
    e1 = main["port"] - main["univ"]; e2 = gbp(main["port"]) - vw.reindex(main.index)
    n = p1.reg.n_trials(p1.reg.load()) + p1.N_EXTRA
    s1 = p1.stats(e1)
    idx = (1 + main["univ"]).cumprod(); bull = (idx > idx.rolling(10).mean()).shift(1)
    thirds = [float(c.mean() * 12) for c in np.array_split(e1, 3)]
    views = {}
    for name, kw in {"T4_quarterly": dict(every=3), "T5_large_only": dict(min_cap=10e9),
                     "T6_cost2": dict(cost=2 * p1.COST), "T6_lag1": dict(lag=1)}.items():
        b = backtest(df, **kw); views[name] = p1.stats(b["port"] - b["univ"])
    res = {"n_trials": n, "B1_vs_universe": s1, "dsr": p1.dsr(s1, n), "B2_vs_vwrp_gbp": p1.stats(e2),
           "portfolio_cagr_gbp": float((1 + gbp(main["port"])).prod() ** (12 / len(main)) - 1),
           "vwrp_cagr_gbp": float((1 + vw.reindex(main.index)).prod() ** (12 / len(main)) - 1),
           "T2_thirds_ann": thirds, "T3_bull_ann": float(e1[bull == True].mean() * 12),
           "T3_bear_ann": float(e1[bull == False].mean() * 12), **views,
           "turnover_per_year": float(main["turn"].mean() * 12),
           "names_traded_per_year": float(main["turn"].mean() * 12 * p1.TOP),
           "gross_minus_univ_ann": float((main["port_gross"] - main["univ"]).mean() * 12),
           "cost_drag_ann": float((main["port_gross"] - main["port"]).mean() * 12)}
    res["pass"] = bool(res["dsr"] > 0.95 and sum(t > 0 for t in thirds) >= 2 and views["T6_cost2"]["ann"] > 0
                       and views["T6_lag1"]["ann"] > 0 and res["B2_vs_vwrp_gbp"]["ann"] > 0)
    res["switch_live"] = bool(s1["ann"] >= 0.0343 and views["T6_lag1"]["ann"] > 0)
    out.write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    if sys.argv[1] == "backtest":
        print(json.dumps(run_backtest(Path(sys.argv[2])), indent=1))
    else:
        df = p1.load(); m = df[df["month"] == pd.Timestamp(sys.argv[2]) + pd.offsets.MonthEnd(0)]
        u = p1.universe(m)
        held_t = [t.strip() for t in Path(sys.argv[3]).read_text().split(",") if t.strip()]
        held = list(u[u["ticker"].isin(held_t)]["cik"])
        new, sold, bought = review(u, held)
        t = dict(zip(m["cik"], m["ticker"]))
        print("SELL", [t[c] for c in sold]); print("BUY", [t[c] for c in bought])
        pd.DataFrame({"ticker": [t[c] for c in new]}).to_csv(sys.argv[4], index=False)

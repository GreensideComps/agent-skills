"""Q177 debt issuance, Q178 F-score. Prereg: /mnt/project-files/research/always-on/prereg/Q177_Q178.md."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xsection as xs
import q01_low_vol as q
from q164_composite import yearly

if __name__ == "__main__":
    df = q.features(xs.load()).sort_values(["cik", "month"])
    L = lambda c: df.groupby("cik")[c].shift(12)
    debt = df["debt_total"].fillna(0)
    df["di"] = (debt - debt.groupby(df["cik"]).shift(12)) / L("total_assets")
    ni, ocf, ta = df["ttm_net_income"], df["ttm_ocf"], df["total_assets"]
    roa = ni / ta; lev = df["debt_noncurrent"].fillna(0) / ta
    gm = df["ttm_gross_profit"] / df["ttm_revenue"]; at = df["ttm_revenue"] / ta
    g = lambda s: s.groupby(df["cik"]).shift(12)
    parts = [ni > 0, ocf > 0, roa > g(roa), ocf > ni, lev < g(lev), df["shares_out"] <= g(df["shares_out"]), gm > g(gm), at > g(at)]
    F = sum(p.astype(int) for p in parts)
    ok = g(ta).notna() & ni.notna() & ocf.notna()
    df["fscore7"] = np.where(ok & (F >= 7), 1.0, np.nan)
    q.portfolio = yearly
    r = q.main(Path(sys.argv[1]), trials=(("Q177a", "di"), ("Q178a", "fscore7")), df=df)
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s q %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull %.2f bear %.2f pass %s" % (
            100*v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"], [round(100*t, 2) for t in v["T2_thirds_ann"]],
            100*v["T4_quarterly"]["ann"], 100*v["T5_mid"]["ann"], 100*v["T6_cost2"]["ann"], 100*v["T6_lag1"]["ann"], 100*v["T3_bull_ann"], 100*v["T3_bear_ann"], v["pass"]))

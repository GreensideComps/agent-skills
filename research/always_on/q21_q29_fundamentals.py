"""Q21 margin inflection, Q23 low leverage, Q25 size within large caps, Q28/Q29 working-capital discipline,
always-on loop. Prereg: /mnt/project-files/research/always-on/prereg/Q21_Q29.md. `q01_low_vol.portfolio` buys the
lowest values."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import q01_low_vol as q  # noqa: E402

DATA = Path("/mnt/project-files/research-data")


def features() -> pd.DataFrame:
    df = q.features(q.xs.load()).sort_values(["cik", "month"])
    sic = pd.read_csv(DATA / "sec_companies.csv.gz", usecols=["cik", "sic"])
    df = df.merge(sic, on="cik", how="left")
    df = df[~df["sic"].between(6000, 6799)].copy()
    rev = df["ttm_revenue"].where(df["ttm_revenue"] > 0)
    gm, om = df["ttm_gross_profit"] / rev, df["ttm_operating_income"] / rev
    df["_gm"], df["_om"], df["_rev"] = gm, om, rev
    g = df.groupby("cik")
    dgm, dom = gm - g["_gm"].shift(12), om - g["_om"].shift(12)
    dom_prev = g["_om"].shift(12) - g["_om"].shift(24)
    df["m_gm"], df["m_om"] = -dgm, -dom
    df["m_turn"] = np.where((dom > 0) & (dom_prev < 0), 0.0, np.nan)
    assets = df["total_assets"].where(df["total_assets"] > 0)
    df["l_da"] = df["debt_total"].fillna(0).where(df["total_assets"].notna()) / assets
    ebit = df["ttm_operating_income"].where(df["ttm_operating_income"] > 0)
    df["l_nd"] = (df["debt_total"].fillna(0) - df["cash"].fillna(0)) / ebit
    df["s_small"], df["s_big"] = df["mcap"], -df["mcap"]
    rg = rev / g["_rev"].shift(12) - 1
    for c, src in [("inv", "inventory"), ("rec", "receivables")]:
        x = df[src].where(df[src] > 0)
        df["_" + c] = x
        x12 = df.groupby("cik")["_" + c].shift(12)
        df[c + "_gap"] = x / x12 - 1 - rg
        df[c + "_ratio"] = x / rev - x12 / df.groupby("cik")["_rev"].shift(12)
    return df


if __name__ == "__main__":
    trials = (("Q21a", "m_gm"), ("Q21b", "m_om"), ("Q21c", "m_turn"), ("Q23a", "l_da"), ("Q23b", "l_nd"),
              ("Q25a", "s_small"), ("Q25b", "s_big"), ("Q28a", "inv_gap"), ("Q28b", "inv_ratio"),
              ("Q29a", "rec_gap"), ("Q29b", "rec_ratio"))
    r = q.main(Path(sys.argv[1]), trials, features())
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f thirds %s qtr %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull/bear %.1f/%.1f pass %s" % (
            100 * v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0,
            [round(100 * t, 1) for t in v["T2_thirds_ann"]], 100 * v["T4_quarterly"]["ann"], 100 * v["T5_mid"]["ann"],
            100 * v["T6_cost2"]["ann"], 100 * v["T6_lag1"]["ann"], 100 * v["T3_bull_ann"], 100 * v["T3_bear_ann"], v["pass"]))

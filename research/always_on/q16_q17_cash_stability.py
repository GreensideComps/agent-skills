"""Q16 net cash and Q17 earnings stability, always-on loop.
Prereg: /mnt/project-files/research/always-on/prereg/Q16_Q17.md. `q01_low_vol.portfolio` buys the lowest values."""
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
    cash = df["cash"].fillna(0) + df["short_investments"].fillna(0)
    cash = cash.where(df["cash"].notna())
    net = cash - df["debt_total"].fillna(0)
    mcap = df["mcap"].where(df["mcap"] > 0)
    assets = df["total_assets"].where(df["total_assets"] > 0)
    df["c_net_mc"], df["c_mc"], df["c_net_at"] = -net / mcap, -cash / mcap, -net / assets
    g = df.groupby("cik")
    dni = (df["ttm_net_income"] - g["ttm_net_income"].shift(12)) / assets
    rg = df["ttm_revenue"] / g["ttm_revenue"].shift(12).where(lambda x: x > 0) - 1
    df["_dni"], df["_rg"] = dni, rg
    df["s_ni"] = df.groupby("cik")["_dni"].transform(lambda s: s.rolling(36, min_periods=30).std())
    df["s_rev"] = df.groupby("cik")["_rg"].transform(lambda s: s.rolling(36, min_periods=30).std())
    ni = df["ttm_net_income"]
    up3 = (ni > g["ttm_net_income"].shift(12)) & (g["ttm_net_income"].shift(12) > g["ttm_net_income"].shift(24)) \
        & (g["ttm_net_income"].shift(24) > g["ttm_net_income"].shift(36))
    df["up3"] = np.where(up3, 0.0, np.nan)
    return df


if __name__ == "__main__":
    trials = (("Q16a", "c_net_mc"), ("Q16b", "c_mc"), ("Q16c", "c_net_at"), ("Q17a", "s_ni"), ("Q17b", "s_rev"), ("Q17c", "up3"))
    r = q.main(Path(sys.argv[1]), trials, features())
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s qtr %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull/bear %.1f/%.1f pass %s" % (
            100 * v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"],
            [round(100 * t, 1) for t in v["T2_thirds_ann"]], 100 * v["T4_quarterly"]["ann"], 100 * v["T5_mid"]["ann"],
            100 * v["T6_cost2"]["ann"], 100 * v["T6_lag1"]["ann"], 100 * v["T3_bull_ann"], 100 * v["T3_bear_ann"], v["pass"]))

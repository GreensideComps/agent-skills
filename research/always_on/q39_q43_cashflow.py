"""Q39 FCF yield, Q40 SBC dilution, Q41 capex discipline, Q42 goodwill, Q43 interest cover, always-on loop.
Prereg: /mnt/project-files/research/always-on/prereg/Q39_Q43.md. `q01_low_vol.portfolio` buys the lowest values."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import q01_low_vol as q  # noqa: E402
from q33_q37_quality import DATA  # noqa: E402


def features() -> pd.DataFrame:
    df = q.features(q.xs.load()).sort_values(["cik", "month"])
    sic = pd.read_csv(DATA / "sec_companies.csv.gz", usecols=["cik", "sic"])
    df = df.merge(sic, on="cik", how="left")
    df = df[~df["sic"].between(6000, 6799)].copy()
    rev = df["ttm_revenue"].where(df["ttm_revenue"] > 0)
    capex = df["ttm_capex"].abs()
    df["_rev"], df["_cx"] = rev, capex.where(capex > 0)
    g = df.groupby("cik")
    df["fcf"] = -(df["ttm_ocf"] - capex) / df["mcap"]
    df["sbc"] = df["ttm_sbc"].fillna(0).where(rev.notna()) / rev
    df["cxg"] = (df["_cx"] / g["_cx"].shift(12)) - (rev / g["_rev"].shift(12))
    df["gw"] = df["goodwill"].fillna(0).where(df["total_assets"] > 0) / df["total_assets"]
    ie = df["ttm_interest_expense"].abs()
    cover = df["ttm_operating_income"] / ie.where(ie > 0)
    cover = cover.where(ie > 0, np.where(df["ttm_operating_income"] > 0, 1e6, np.nan))
    df["icov"] = -cover
    return df


if __name__ == "__main__":
    trials = (("Q39a", "fcf"), ("Q40a", "sbc"), ("Q41a", "cxg"), ("Q42a", "gw"), ("Q43a", "icov"))
    r = q.main(Path(sys.argv[1]), trials, features())
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s qtr %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull/bear %.1f/%.1f pass %s" % (
            100 * v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"],
            [round(100 * t, 1) for t in v["T2_thirds_ann"]], 100 * v["T4_quarterly"]["ann"], 100 * v["T5_mid"]["ann"],
            100 * v["T6_cost2"]["ann"], 100 * v["T6_lag1"]["ann"], 100 * v["T3_bull_ann"], 100 * v["T3_bear_ann"], v["pass"]))

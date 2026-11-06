"""Q32 conservative balance sheet + steady dividend growth, always-on loop.
Prereg: /mnt/project-files/research/always-on/prereg/Q32.md. `q01_low_vol.portfolio` buys the lowest values."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import q01_low_vol as q  # noqa: E402
import q06_dividends as q06  # noqa: E402

DATA = Path("/mnt/project-files/research-data")


def features() -> pd.DataFrame:
    df = q06.features()
    sic = pd.read_csv(DATA / "sec_companies.csv.gz", usecols=["cik", "sic"])
    df = df.merge(sic, on="cik", how="left")
    df = df[~df["sic"].between(6000, 6799)].copy()
    ebit = df["ttm_operating_income"].where(df["ttm_operating_income"] > 0)
    df["nd"] = (df["debt_total"].fillna(0) - df["cash"].fillna(0)) / ebit
    large = (df["band"] == "large") & df["nd"].notna()
    df["nd_pct"] = np.nan
    df.loc[large, "nd_pct"] = df[large].groupby("month")["nd"].rank(pct=True)
    df["c_and"] = np.where(df["d_grow"].notna() & (df["nd_pct"] <= 0.4), 0.0, np.nan)
    g = df.groupby("cik")["dps"]
    growth2 = df["dps"] / g.shift(24).where(lambda x: x > 0) - 1
    df["_g2"] = growth2
    df["g2_pct"] = np.nan
    ok = large & df["_g2"].notna()
    df.loc[ok, "g2_pct"] = df[ok].groupby("month")["_g2"].rank(pct=True)
    df["c_rank"] = -((1 - df["nd_pct"]) + df["g2_pct"]) / 2
    return df


if __name__ == "__main__":
    r = q.main(Path(sys.argv[1]), (("Q32a", "c_and"), ("Q32b", "c_rank")), features())
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s qtr %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull/bear %.1f/%.1f pass %s" % (
            100 * v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"],
            [round(100 * t, 1) for t in v["T2_thirds_ann"]], 100 * v["T4_quarterly"]["ann"], 100 * v["T5_mid"]["ann"],
            100 * v["T6_cost2"]["ann"], 100 * v["T6_lag1"]["ann"], 100 * v["T3_bull_ann"], 100 * v["T3_bear_ann"], v["pass"]))

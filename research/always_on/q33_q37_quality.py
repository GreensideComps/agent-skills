"""Q33 accruals, Q34 asset growth, Q35 net issuance, Q36 gross/cash profitability, Q37 52-week-high proximity,
always-on loop. Prereg: /mnt/project-files/research/always-on/prereg/Q33_Q37.md. `q01_low_vol.portfolio` buys the
lowest values, so "highest is good" signals are negated."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import q01_low_vol as q  # noqa: E402

DATA = Path("/mnt/project-files/research-data")


def features() -> pd.DataFrame:
    df = q.features(q.xs.load()).sort_values(["cik", "month"])
    sic = pd.read_csv(DATA / "sec_companies.csv.gz", usecols=["cik", "sic"])
    df = df.merge(sic, on="cik", how="left")
    df = df[~df["sic"].between(6000, 6799)].copy()
    assets = df["total_assets"].where(df["total_assets"] > 0)
    df["_a"], df["_sh"] = assets, df["shares_out"].where(df["shares_out"] > 0)
    g = df.groupby("cik")
    df["acc"] = (df["ttm_net_income"] - df["ttm_ocf"]) / assets
    df["agr"] = assets / g["_a"].shift(12) - 1
    df["iss"] = df["_sh"] / g["_sh"].shift(12) - 1
    df["gpa"] = -df["ttm_gross_profit"] / assets
    df["cpa"] = -df["ttm_ocf"] / assets
    df["hi52"] = -df["adjclose"] / g["adjclose"].transform(lambda s: s.rolling(12, min_periods=12).max())
    return df


if __name__ == "__main__":
    trials = (("Q33a", "acc"), ("Q34a", "agr"), ("Q35a", "iss"), ("Q36a", "gpa"), ("Q36b", "cpa"), ("Q37a", "hi52"))
    r = q.main(Path(sys.argv[1]), trials, features())
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s qtr %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull/bear %.1f/%.1f pass %s" % (
            100 * v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"],
            [round(100 * t, 1) for t in v["T2_thirds_ann"]], 100 * v["T4_quarterly"]["ann"], 100 * v["T5_mid"]["ann"],
            100 * v["T6_cost2"]["ann"], 100 * v["T6_lag1"]["ann"], 100 * v["T3_bull_ann"], 100 * v["T3_bear_ann"], v["pass"]))

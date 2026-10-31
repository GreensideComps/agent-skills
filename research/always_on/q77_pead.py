"""Q77 post-earnings drift (TTM EPS jump scaled by price, recent filers), always-on loop.
Prereg: /mnt/project-files/research/always-on/prereg/Q73_Q77.md. `q01_low_vol.portfolio` buys the lowest values."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import q01_low_vol as q  # noqa: E402
from q33_q37_quality import DATA  # noqa: E402


def features() -> pd.DataFrame:
    df = q.features(q.xs.load()).sort_values(["cik", "month"])
    sic = pd.read_csv(DATA / "sec_companies.csv.gz", usecols=["cik", "sic"])
    df = df.merge(sic, on="cik", how="left")
    df = df[~df["sic"].between(6000, 6799)].copy()
    eps12 = df.groupby("cik")["ttm_eps_diluted"].shift(12)
    sue = (df["ttm_eps_diluted"] - eps12) / df["close_raw"].where(df["close_raw"] > 0)
    age = (pd.to_datetime(df["month"]) - pd.to_datetime(df["last_filed"])).dt.days
    df["pead92"] = (-sue).where(age.between(0, 92))
    df["pead31"] = (-sue).where(age.between(0, 31))
    return df


if __name__ == "__main__":
    r = q.main(Path(sys.argv[1]), (("Q77a", "pead92"), ("Q77b", "pead31")), features())
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s qtr %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% pass %s" % (
            100 * v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"], [round(100 * t, 1) for t in v["T2_thirds_ann"]],
            100 * v["T4_quarterly"]["ann"], 100 * v["T5_mid"]["ann"], 100 * v["T6_cost2"]["ann"], 100 * v["T6_lag1"]["ann"], v["pass"]))

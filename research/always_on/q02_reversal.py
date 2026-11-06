"""Q02 short-term reversal, always-on loop. Pre-registration: /mnt/project-files/research/always-on/prereg/Q02.md.
Scores are stored as "risk" columns (lowest = best), so `q01_low_vol.portfolio` buys the lowest values."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import q01_low_vol as q  # noqa: E402

DATA = Path("/mnt/project-files/research-data")


def features() -> pd.DataFrame:
    df = q.features(q.xs.load())
    sic = pd.read_csv(DATA / "sec_companies.csv.gz", usecols=["cik", "sic"])
    df = df.merge(sic.assign(sic2=sic["sic"] // 100)[["cik", "sic2"]], on="cik", how="left")
    df["r1"] = df["ret"]  # last month's return (lowest = biggest loser = buy)
    df["r1_ind"] = df["ret"] - df.groupby(["month", "sic2"])["ret"].transform("mean")
    g = df.groupby("cik")["ret"]
    mom = g.transform(lambda s: (1 + s.shift(1)).rolling(11, min_periods=11).apply(lambda x: x.prod(), raw=True) - 1)
    df["r1_win"] = df["r1"].where(mom > 0)
    return df


if __name__ == "__main__":
    r = q.main(Path(sys.argv[1]), (("Q02a", "r1"), ("Q02b", "r1_ind"), ("Q02c", "r1_win")), features())
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s mid %.2f%% c2 %.2f%% lag %.2f%% bull/bear %.1f/%.1f pass %s" % (
            100 * v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"],
            [round(100 * t, 1) for t in v["T2_thirds_ann"]], 100 * v["T5_mid"]["ann"], 100 * v["T6_cost2"]["ann"],
            100 * v["T6_lag1"]["ann"], 100 * v["T3_bull_ann"], 100 * v["T3_bear_ann"], v["pass"]))

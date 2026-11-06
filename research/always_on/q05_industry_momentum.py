"""Q05 industry momentum, always-on loop. Prereg: /mnt/project-files/research/always-on/prereg/Q05.md.
Columns are negated scores: `q01_low_vol.portfolio` buys the lowest values."""
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
    lc = df[(df["band"] == "large") & (df["close_raw"] >= q.xs.MIN_PRICE) & df["ret"].notna() & df["sic2"].notna()]
    ind = lc.groupby(["sic2", "month"])["ret"].agg(["mean", "count"]).reset_index()
    ind.loc[ind["count"] < 3, "mean"] = float("nan")
    ind = ind.sort_values(["sic2", "month"])
    lr = ind.groupby("sic2")["mean"]
    comp = lambda k, skip=0: lr.transform(  # noqa: E731
        lambda s: (1 + s.shift(skip)).rolling(k, min_periods=k).apply(lambda x: x.prod(), raw=True) - 1)
    ind["i6"], ind["i12_2"], ind["i1"] = -comp(6), -comp(11, 1), -ind["mean"]
    return df.merge(ind[["sic2", "month", "i6", "i12_2", "i1"]], on=["sic2", "month"], how="left")


if __name__ == "__main__":
    r = q.main(Path(sys.argv[1]), (("Q05a", "i6"), ("Q05b", "i12_2"), ("Q05c", "i1")), features())
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s qtr %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull/bear %.1f/%.1f pass %s" % (
            100 * v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"],
            [round(100 * t, 1) for t in v["T2_thirds_ann"]], 100 * v["T4_quarterly"]["ann"], 100 * v["T5_mid"]["ann"],
            100 * v["T6_cost2"]["ann"], 100 * v["T6_lag1"]["ann"], 100 * v["T3_bull_ann"], 100 * v["T3_bear_ann"], v["pass"]))

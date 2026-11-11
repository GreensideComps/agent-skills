"""Q20 insider cluster buying, always-on loop. Prereg: /mnt/project-files/research/always-on/prereg/Q20.md.
Columns are membership flags (0 = hold, NaN = not held)."""
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
    t = pd.read_csv(DATA / "insider_trades.csv.gz", usecols=["issuer_cik", "filed", "owner_cik", "code"])
    t = t[t["code"] == "P"]
    t["month"] = pd.to_datetime(t["filed"]) + pd.offsets.MonthEnd(0)
    n = t.groupby(["issuer_cik", "month"])["owner_cik"].nunique().rename("buyers").reset_index()
    df = df.merge(n.rename(columns={"issuer_cik": "cik"}), on=["cik", "month"], how="left")
    df["buyers"] = df["buyers"].fillna(0)
    for col, k, h in [("ic3_6", 3, 6), ("ic2_6", 2, 6), ("ic3_12", 3, 12)]:
        ev = (df["buyers"] >= k).astype(float)
        held = ev.groupby(df["cik"]).transform(lambda s: s.rolling(h, min_periods=1).max())
        df[col] = np.where(held > 0, 0.0, np.nan)
    return df


if __name__ == "__main__":
    df = features()
    x = df[(df["month"] >= q.START) & (df["month"] <= q.END) & df["band"].notna()]
    print("avg names/month:", {c: round(x.groupby("month")[c].count().mean(), 1) for c in ["ic3_6", "ic2_6", "ic3_12"]})
    r = q.main(Path(sys.argv[1]), (("Q20a", "ic3_6"), ("Q20b", "ic2_6"), ("Q20c", "ic3_12")), df, band="all", band2="mid")
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f months %d thirds %s qtr %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull/bear %.1f/%.1f pass %s" % (
            100 * v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["T1_main"]["months"],
            [round(100 * t, 1) for t in v["T2_thirds_ann"]], 100 * v["T4_quarterly"]["ann"], 100 * v["T5_mid"]["ann"],
            100 * v["T6_cost2"]["ann"], 100 * v["T6_lag1"]["ann"], 100 * v["T3_bull_ann"], 100 * v["T3_bear_ann"], v["pass"]))

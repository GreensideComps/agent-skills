"""Q11/Q18 spin-offs, always-on loop. Prereg: /mnt/project-files/research/always-on/prereg/Q11.md, Q18.md (Q11 large-cap run was
inconclusive: too few names; this script now runs Q18, all sizes). Columns are membership flags (0 = hold, NaN = not held)."""
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
    f10 = pd.read_csv(DATA / "edgar_form10_first_filing_2012_2022.csv", parse_dates=["first_10_12b"])
    first_px = df[df["adjclose"].notna()].groupby("cik")["month"].min().rename("first_px")
    s = f10.set_index("cik").join(first_px, how="inner")
    s = s[s["first_px"] > s["first_10_12b"]]
    df = df.merge(s["first_px"], left_on="cik", right_index=True, how="left")
    age = (df["month"].dt.year - df["first_px"].dt.year) * 12 + df["month"].dt.month - df["first_px"].dt.month
    # decision at month-end `age` holds through month age+1; months 2..k after the first price
    for col, k in [("sp13", 13), ("sp7", 7), ("sp25", 25)]:
        df[col] = np.where((age >= 1) & (age <= k - 1), 0.0, np.nan)
    print("spin-offs matched:", len(s))
    return df


if __name__ == "__main__":
    df = features()
    lc = df[(df["month"] >= q.START) & (df["month"] <= q.END)]
    for b in ["large", "mid"]:
        x = lc[lc["band"] == b]
        print(b, "avg names/month:", {c: round(x.groupby("month")[c].count().mean(), 1) for c in ["sp13", "sp7", "sp25"]})
    r = q.main(Path(sys.argv[1]), (("Q18a", "sp13"), ("Q18b", "sp7"), ("Q18c", "sp25")), df, band="all", band2="mid")
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f months %d thirds %s mid %.2f%% (t %.2f) c2 %.2f%% lag %.2f%% bull/bear %.1f/%.1f pass %s" % (
            100 * v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["T1_main"]["months"],
            [round(100 * t, 1) for t in v["T2_thirds_ann"]], 100 * v["T5_mid"]["ann"], v["T5_mid"]["t_nw"] or 0,
            100 * v["T6_cost2"]["ann"], 100 * v["T6_lag1"]["ann"], 100 * v["T3_bull_ann"], 100 * v["T3_bear_ann"], v["pass"]))

"""Q06 dividend initiations and increases, always-on loop. Prereg: /mnt/project-files/research/always-on/prereg/Q06.md.
Columns are membership flags (0 = hold, NaN = not held)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import q01_low_vol as q  # noqa: E402


def features() -> pd.DataFrame:
    df = q.features(q.xs.load()).sort_values(["cik", "month"])
    df["div"] = df["ttm_dividends_paid"].abs()
    df["dps"] = df["div"] / df["shares_out"].where(df["shares_out"] > 0)
    g = df.groupby("cik")
    div12 = g["div"].shift(12)
    dps12, dps24 = g["dps"].shift(12), g["dps"].shift(24)
    init = (div12 == 0) & (df["div"] > 0)
    df["_init"] = init.astype(float)
    held = df.groupby("cik")["_init"].transform(lambda s: s.rolling(12, min_periods=1).max())
    flag = lambda m: pd.Series(np.where(m, 0.0, np.nan), index=df.index)  # noqa: E731
    df["d_init"] = flag(held > 0)
    df["d_raise"] = flag((dps12 > 0) & (df["dps"] >= 1.2 * dps12))
    df["d_grow"] = flag((dps24 > 0) & (df["dps"] >= 1.05 * dps12) & (dps12 >= 1.05 * dps24))
    return df


if __name__ == "__main__":
    df = features()
    lc = df[(df["band"] == "large") & (df["month"] >= q.START) & (df["month"] <= q.END)]
    print("avg names/month:", {c: round(lc.groupby("month")[c].count().mean(), 1) for c in ["d_init", "d_raise", "d_grow"]})
    r = q.main(Path(sys.argv[1]), (("Q06a", "d_init"), ("Q06b", "d_raise"), ("Q06c", "d_grow")), df)
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s mid %.2f%% c2 %.2f%% lag %.2f%% bull/bear %.1f/%.1f pass %s" % (
            100 * v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"],
            [round(100 * t, 1) for t in v["T2_thirds_ann"]], 100 * v["T5_mid"]["ann"], 100 * v["T6_cost2"]["ann"],
            100 * v["T6_lag1"]["ann"], 100 * v["T3_bull_ann"], 100 * v["T3_bear_ann"], v["pass"]))

"""Q03 same-calendar-month seasonality, always-on loop. Prereg: /mnt/project-files/research/always-on/prereg/Q03.md.
Columns are negated scores: `q01_low_vol.portfolio` buys the lowest values."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import q01_low_vol as q  # noqa: E402


def features() -> pd.DataFrame:
    df = q.features(q.xs.load()).sort_values(["cik", "month"])
    df["rn_month"] = (df["month"] + pd.offsets.MonthEnd(1)).dt.month  # calendar month being predicted
    df["beat"] = (df["ret_next"] > df.groupby("month")["ret_next"].transform("mean")).astype(float)
    df.loc[df["ret_next"].isna(), "beat"] = float("nan")
    # past same-month stats only: shift within (cik, calendar month) so the current year is excluded
    g = df.groupby(["cik", "rn_month"])
    cnt = g["ret_next"].transform(lambda s: s.shift(1).expanding().count())
    same = g["ret_next"].transform(lambda s: s.shift(1).expanding().mean())
    beat = g["beat"].transform(lambda s: s.shift(1).expanding().mean())
    # all-month mean of outcomes known at decision: returns up to and including this month (ret)
    allm = df.groupby("cik")["ret"].transform(lambda s: s.expanding().mean())
    ok = cnt >= 4
    df["s_same"] = (-same).where(ok)
    df["s_diff"] = (-(same - allm)).where(ok)
    df["s_beat"] = (-beat).where(ok)
    return df


if __name__ == "__main__":
    r = q.main(Path(sys.argv[1]), (("Q03a", "s_same"), ("Q03b", "s_diff"), ("Q03c", "s_beat")), features())
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s mid %.2f%% c2 %.2f%% lag %.2f%% bull/bear %.1f/%.1f pass %s" % (
            100 * v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"],
            [round(100 * t, 1) for t in v["T2_thirds_ann"]], 100 * v["T5_mid"]["ann"], 100 * v["T6_cost2"]["ann"],
            100 * v["T6_lag1"]["ann"], 100 * v["T3_bull_ann"], 100 * v["T3_bear_ann"], v["pass"]))

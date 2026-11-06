"""Q04 earnings announcement premium (monthly), always-on loop. Prereg: /mnt/project-files/research/always-on/prereg/Q04.md.
Columns are membership flags (0 = hold, NaN = not held); `q01_low_vol.portfolio` holds every flagged name.
T4 (quarterly) from the shared harness is reported but not meaningful here."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import q01_low_vol as q  # noqa: E402

DATA = Path("/mnt/project-files/research-data")


def features() -> pd.DataFrame:
    df = q.features(q.xs.load())
    f = pd.read_csv(DATA / "sec_facts_panel.csv.gz", usecols=["cik", "filed", "form"])
    f = f[f["form"].isin(["10-Q", "10-K"])].drop_duplicates(["cik", "filed"])
    f["fm"] = pd.to_datetime(f["filed"]) + pd.offsets.MonthEnd(0)
    filed = set(zip(f["cik"], f["fm"]))
    nxt = df["month"] + pd.offsets.MonthEnd(1)
    a = [(c, m) in filed for c, m in zip(df["cik"], nxt - pd.DateOffset(months=12) + pd.offsets.MonthEnd(0))]
    b = [(c, m) in filed for c, m in zip(df["cik"], nxt - pd.DateOffset(months=3) + pd.offsets.MonthEnd(0))]
    # only filings already made by the decision month-end count (both lookbacks are <= decision month)
    df["p12"] = pd.Series(a, index=df.index).map({True: 0.0, False: float("nan")})
    df["p3"] = pd.Series(b, index=df.index).map({True: 0.0, False: float("nan")})
    df["pboth"] = df["p12"].where(df["p3"].notna())
    return df


if __name__ == "__main__":
    r = q.main(Path(sys.argv[1]), (("Q04a", "p12"), ("Q04b", "p3"), ("Q04c", "pboth")), features())
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s mid %.2f%% c2 %.2f%% lag %.2f%% bull/bear %.1f/%.1f pass %s" % (
            100 * v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"],
            [round(100 * t, 1) for t in v["T2_thirds_ann"]], 100 * v["T5_mid"]["ann"], 100 * v["T6_cost2"]["ann"],
            100 * v["T6_lag1"]["ann"], 100 * v["T3_bull_ann"], 100 * v["T3_bear_ann"], v["pass"]))

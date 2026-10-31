"""Q147/Q148 8-K event volume. Pre-registration: /mnt/project-files/research/always-on/prereg/Q147_Q148.md."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xsection as xs
import q01_low_vol as q
ROUTINE = {"2.02", "9.01", "5.07", "7.01", "8.01"}

def build():
    df = q.features(xs.load())
    df["month"] = pd.to_datetime(df["month"])
    p = pd.read_csv("/mnt/project-files/research-data/8k_items_large_2013_2026.csv.gz", parse_dates=["date"])
    it = p["items"].str.split(",").apply(lambda v: {x.strip() for x in v})
    p["nonroutine"] = it.apply(lambda s: bool(s - ROUTINE)).astype(int)
    p["d502"] = it.apply(lambda s: "5.02" in s).astype(int)
    p["m"] = p["date"] + pd.offsets.MonthEnd(0)
    g = p.groupby(["cik", "m"])[["nonroutine", "d502"]].sum()
    have = set(p["cik"])
    months = pd.date_range("2013-01-31", "2022-12-31", freq="ME")
    out = []
    for c in have:
        s = g.loc[c].reindex(months, fill_value=0).rolling(12, min_periods=12).sum()
        s["cik"] = c; out.append(s)
    r = pd.concat(out).rename_axis("month").reset_index()
    df = df.merge(r, on=["cik", "month"], how="left")
    df["nr12"] = df["nonroutine"].astype(float)
    df["no502"] = np.where(df["d502"] == 0, 1.0, np.nan)
    return df

if __name__ == "__main__":
    df = build()
    r = q.main(Path(sys.argv[1]), trials=(("Q147a", "nr12"), ("Q148a", "no502")), df=df)
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s q %.2f%% c2 %.2f%% lag %.2f%% bull %.2f bear %.2f pass %s" % (
            100*v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"], [round(100*t, 2) for t in v["T2_thirds_ann"]],
            100*v["T4_quarterly"]["ann"], 100*v["T6_cost2"]["ann"], 100*v["T6_lag1"]["ann"], 100*v["T3_bull_ann"], 100*v["T3_bear_ann"], v["pass"]))

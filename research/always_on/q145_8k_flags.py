"""Q145/Q146 8-K red-flag avoidance. Pre-registration: /mnt/project-files/research/always-on/prereg/Q145_Q146.md."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xsection as xs
import q01_low_vol as q

def build():
    df = q.features(xs.load())
    df["month"] = pd.to_datetime(df["month"])
    p = pd.read_csv("/mnt/project-files/research-data/8k_items_large_2013_2026.csv.gz", parse_dates=["date"])
    have = set(p["cik"])
    m = df[["cik", "month"]].drop_duplicates()
    for col, item in (("no402", "4.02"), ("no401", "4.01")):
        e = p[p["items"].str.split(",").apply(lambda xs_: item in [x.strip() for x in xs_])].copy()
        e["m"] = e["date"] + pd.offsets.MonthEnd(0)
        j = m.merge(e[["cik", "m"]], on="cik")
        hit = j[(j["m"] <= j["month"]) & (j["m"] > j["month"] - pd.DateOffset(months=12))]
        bad = set(map(tuple, hit[["cik", "month"]].drop_duplicates().values))
        df[col] = [np.nan if (c not in have or (c, mo) in bad) else 1.0 for c, mo in zip(df["cik"], df["month"])]
        print(col, "excluded cik-months:", len(bad))
    return df

if __name__ == "__main__":
    df = build()
    r = q.main(Path(sys.argv[1]), trials=(("Q145a", "no402"), ("Q146a", "no401")), df=df)
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s q %.2f%% c2 %.2f%% lag %.2f%% bull %.2f bear %.2f pass %s" % (
            100*v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"], [round(100*t, 2) for t in v["T2_thirds_ann"]],
            100*v["T4_quarterly"]["ann"], 100*v["T6_cost2"]["ann"], 100*v["T6_lag1"]["ann"], 100*v["T3_bull_ann"], 100*v["T3_bear_ann"], v["pass"]))

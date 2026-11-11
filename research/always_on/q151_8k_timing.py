"""Q151/Q152 8-K timing. Pre-registration: /mnt/project-files/research/always-on/prereg/Q151_Q152.md."""
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
    have = set(p["cik"])
    # Q151 shift
    e = p[it.apply(lambda s: "2.02" in s)][["cik", "date"]].drop_duplicates().sort_values(["cik", "date"])
    sh = []
    for c, g in e.groupby("cik"):
        d = g["date"].values
        for x in d:
            prior = d[(d >= x - np.timedelta64(380, "D")) & (d <= x - np.timedelta64(350, "D"))]
            if len(prior):
                sh.append((c, x, (x - prior[-1]).astype("timedelta64[D]").astype(int) - 365))
    sh = pd.DataFrame(sh, columns=["cik", "date", "shift"]).sort_values("date")
    sh["m"] = sh["date"] + pd.offsets.MonthEnd(0)
    df = df.sort_values("month").reset_index(drop=True)
    j = pd.merge_asof(df[["cik", "month"]], sh.sort_values("m")[["cik", "m", "shift"]], left_on="month", right_on="m", by="cik", direction="backward")
    ok = (j["m"] > j["month"] - pd.DateOffset(months=4)) & (j["shift"] <= 5)
    df["early"] = np.where(ok.values, 1.0, np.nan)
    # Q152 Friday non-routine
    f = p[it.apply(lambda s: bool(s - ROUTINE)) & (p["date"].dt.dayofweek == 4)].copy()
    f["m"] = f["date"] + pd.offsets.MonthEnd(0)
    mm = df[["cik", "month"]].drop_duplicates().merge(f[["cik", "m"]], on="cik")
    hit = mm[(mm["m"] <= mm["month"]) & (mm["m"] > mm["month"] - pd.DateOffset(months=3))]
    bad = set(map(tuple, hit[["cik", "month"]].drop_duplicates().values))
    df["nofri"] = [np.nan if (c not in have or (c, mo) in bad) else 1.0 for c, mo in zip(df["cik"], df["month"])]
    print("early rows", int(df["early"].notna().sum()), "friday-bad", len(bad))
    return df

if __name__ == "__main__":
    df = build()
    r = q.main(Path(sys.argv[1]), trials=(("Q151a", "early"), ("Q152a", "nofri")), df=df)
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s q %.2f%% c2 %.2f%% lag %.2f%% bull %.2f bear %.2f pass %s" % (
            100*v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"], [round(100*t, 2) for t in v["T2_thirds_ann"]],
            100*v["T4_quarterly"]["ann"], 100*v["T6_cost2"]["ann"], 100*v["T6_lag1"]["ann"], 100*v["T3_bull_ann"], 100*v["T3_bear_ann"], v["pass"]))

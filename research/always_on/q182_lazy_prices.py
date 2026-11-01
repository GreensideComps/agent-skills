"""Q182 Lazy Prices. Prereg: /mnt/project-files/research/always-on/prereg/Q182.md."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xsection as xs
import q01_low_vol as q
from q164_composite import yearly

if __name__ == "__main__":
    df = q.features(xs.load())
    s = pd.read_csv("/mnt/project-files/research-data/10k_similarity_2014_2022.csv.gz", parse_dates=["date"])
    s["year"] = s["date"].dt.year
    s = s.sort_values("date").groupby(["cik", "year"]).tail(1)[["cik", "year", "sim"]]
    df["month"] = pd.to_datetime(df["month"]); df["sig_year"] = df["month"].dt.year - 1
    df = df.merge(s, left_on=["cik", "sig_year"], right_on=["cik", "year"], how="left")
    df["neg_sim"] = -df["sim"]
    lg = df[(df.band == "large") & (df.month >= "2015-01-31") & (df.month <= "2022-11-30")]
    print("large-cap coverage:", round(lg["sim"].notna().mean(), 3))
    q.portfolio = yearly
    r = q.main(Path(sys.argv[1]), trials=(("Q182a", "neg_sim"),), df=df)
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s q %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull %.2f bear %.2f pass %s" % (
            100*v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"], [round(100*t, 2) for t in v["T2_thirds_ann"]],
            100*v["T4_quarterly"]["ann"], 100*(v["T5_mid"]["ann"] or 0), 100*v["T6_cost2"]["ann"], 100*v["T6_lag1"]["ann"], 100*v["T3_bull_ann"], 100*v["T3_bear_ann"], v["pass"]))

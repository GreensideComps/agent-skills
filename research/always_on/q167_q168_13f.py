"""Q167 13F crowding, Q168 new money. Prereg: /mnt/project-files/research/always-on/prereg/Q167_Q168.md."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xsection as xs
import q01_low_vol as q
from q164_composite import yearly

def build():
    df = q.features(xs.load())
    c = pd.read_csv("/mnt/project-files/research-data/13f_conc_new_jun_2013_2022.csv.gz")
    c.loc[c["year"] > 2013, "newk"] = c.loc[c["year"] > 2013, "newk"].fillna(0)
    f = pd.read_json("/mnt/project-files/research-data/13f_cusip_figi.jsonl", lines=True).dropna(subset=["ticker"])
    f = f[f["type"].isin(["Common Stock", "REIT", "ADR"])]
    c = c.merge(f[["cusip", "ticker"]], left_on="CUSIP", right_on="cusip")
    c = c.groupby(["ticker", "year"])[["conc", "newk"]].mean().reset_index()  # multiple CUSIPs per ticker are rare
    df["month"] = pd.to_datetime(df["month"]); df["sig_year"] = df["month"].dt.year - 1
    df = df.merge(c, left_on=["ticker", "sig_year"], right_on=["ticker", "year"], how="left")
    df["neg_newk"] = -df["newk"]
    return df

if __name__ == "__main__":
    df = build()
    q.portfolio = yearly
    r = q.main(Path(sys.argv[1]), trials=(("Q167a", "conc"), ("Q168a", "neg_newk")), df=df)
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s q %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull %.2f bear %.2f pass %s" % (
            100*v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"], [round(100*t, 2) for t in v["T2_thirds_ann"]],
            100*v["T4_quarterly"]["ann"], 100*v["T5_mid"]["ann"], 100*v["T6_cost2"]["ann"], 100*v["T6_lag1"]["ann"], 100*v["T3_bull_ann"], 100*v["T3_bear_ann"], v["pass"]))

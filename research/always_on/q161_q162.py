"""Q161 sector-neutral low vol, Q162 earnings-yield change. Prereg: /mnt/project-files/research/always-on/prereg/Q161_Q162.md."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xsection as xs
import q01_low_vol as q

if __name__ == "__main__":
    df = q.features(xs.load())
    sic = pd.read_csv("/mnt/project-files/research-data/sec_companies.csv.gz", usecols=["cik", "sic"]).dropna()
    sic["sic2"] = (pd.to_numeric(sic["sic"], errors="coerce") // 100)
    df = df.merge(sic[["cik", "sic2"]], on="cik", how="left")
    med = df.groupby(["month", "sic2"])["vol12"].transform("median")
    cnt = df.groupby(["month", "sic2"])["vol12"].transform("count")
    allmed = df.groupby("month")["vol12"].transform("median")
    df["vol_sn"] = df["vol12"] - np.where(cnt >= 5, med, allmed)
    ep = df["ttm_net_income"] / df["mcap"]
    df["neg_dep"] = -(ep - ep.groupby(df["cik"]).shift(12))
    r = q.main(Path(sys.argv[1]), trials=(("Q161a", "vol_sn"), ("Q162a", "neg_dep")), df=df)
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s q %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull %.2f bear %.2f pass %s" % (
            100*v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"], [round(100*t, 2) for t in v["T2_thirds_ann"]],
            100*v["T4_quarterly"]["ann"], 100*v["T5_mid"]["ann"], 100*v["T6_cost2"]["ann"], 100*v["T6_lag1"]["ann"], 100*v["T3_bull_ann"], 100*v["T3_bear_ann"], v["pass"]))

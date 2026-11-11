"""Q149 non-December fiscal year-end. Pre-registration: /mnt/project-files/research/always-on/prereg/Q149.md."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xsection as xs
import q01_low_vol as q

if __name__ == "__main__":
    df = q.features(xs.load())
    c = pd.read_csv("/mnt/project-files/research-data/sec_companies.csv.gz", usecols=["cik", "fiscal_year_end"], dtype={"fiscal_year_end": str})
    fye = c.dropna().set_index("cik")["fiscal_year_end"].str.zfill(4)
    nd = fye[~fye.str.startswith("12")].index
    df["nondec"] = np.where(df["cik"].isin(nd), 1.0, np.nan)
    print("non-Dec share of large rows:", round(df.loc[df.band == "large", "nondec"].notna().mean(), 3))
    r = q.main(Path(sys.argv[1]), trials=(("Q149a", "nondec"),), df=df)
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s q %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull %.2f bear %.2f pass %s" % (
            100*v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"], [round(100*t, 2) for t in v["T2_thirds_ann"]],
            100*v["T4_quarterly"]["ann"], 100*v["T5_mid"]["ann"], 100*v["T6_cost2"]["ann"], 100*v["T6_lag1"]["ann"], 100*v["T3_bull_ann"], 100*v["T3_bear_ann"], v["pass"]))

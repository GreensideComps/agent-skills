"""Q143 10-K/A avoidance. Pre-registration: /mnt/project-files/research/always-on/prereg/Q143.md."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xsection as xs
import q01_low_vol as q

def build():
    df = q.features(xs.load())
    nt = pd.read_csv("/mnt/project-files/research-data/10ka_filings_2014_2022.csv.gz", parse_dates=["date"])
    df["month"] = pd.to_datetime(df["month"])
    m = df[["cik", "month"]].drop_duplicates()
    nt["m"] = nt["date"] + pd.offsets.MonthEnd(0)
    j = m.merge(nt[["cik", "m"]], on="cik", how="left")
    hit = j[(j["m"] <= j["month"]) & (j["m"] > j["month"] - pd.DateOffset(months=12))]
    bad = set(map(tuple, hit[["cik", "month"]].drop_duplicates().values))
    df["clean"] = [np.nan if (c, mo) in bad else 1.0 for c, mo in zip(df["cik"], df["month"])]
    print("flagged late-filer rows:", len(bad), "of", len(df))
    return df

if __name__ == "__main__":
    df = build()
    r = q.main(Path(sys.argv[1]), trials=(("Q143a", "clean"),), df=df)
    for k, v in r.items():
        print(k, {kk: (vv if not isinstance(vv, dict) else {a: b for a, b in vv.items() if a in ("ann", "t_nw", "months")}) for kk, vv in v.items()})

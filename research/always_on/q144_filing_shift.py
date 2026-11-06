"""Q144 10-K filing-delay shift. Pre-registration: /mnt/project-files/research/always-on/prereg/Q144.md."""
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
    k = pd.read_csv("/mnt/project-files/research-data/10k_shift_2014_2022.csv.gz", parse_dates=["date"])
    k["m"] = k["date"] + pd.offsets.MonthEnd(0)
    k = k.sort_values("m")
    df = df.sort_values("month")
    j = pd.merge_asof(df[["cik", "month"]].reset_index(), k[["cik", "m", "shift"]], left_on="month", right_on="m", by="cik", direction="backward")
    ok = (j["m"] > j["month"] - pd.DateOffset(months=12)) & (j["shift"] <= 10)
    flag = pd.Series(np.where(ok, 1.0, np.nan), index=j["index"])
    df["notlate"] = flag.reindex(df.index).values
    print("flagged rows:", int(df["notlate"].notna().sum()), "of", len(df))
    return df

if __name__ == "__main__":
    df = build()
    r = q.main(Path(sys.argv[1]), trials=(("Q144a", "notlate"),), df=df)
    for k, v in r.items():
        print(k, {kk: (vv if not isinstance(vv, dict) else {a: b for a, b in vv.items() if a in ("ann", "t_nw")}) for kk, vv in v.items()})

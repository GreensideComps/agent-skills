"""Q170/Q171 insider selling. Prereg: /mnt/project-files/research/always-on/prereg/Q170_Q171.md."""
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
    df["month"] = pd.to_datetime(df["month"])
    t = pd.read_csv("/mnt/project-files/research-data/insider_trades.csv.gz", parse_dates=["filed"])
    t = t[t["code"] == "S"].copy()
    t["v"] = t["shares"] * t["price"]
    t["m"] = t["filed"] + pd.offsets.MonthEnd(0)
    g = t.groupby(["issuer_cik", "m"])["v"].sum()
    months = pd.date_range("2012-01-31", "2022-12-31", freq="ME")
    rows = []
    for c in g.index.get_level_values(0).unique():
        s = g.loc[c].reindex(months, fill_value=0.0)
        r12 = s.rolling(12).sum()
        rows.append(pd.DataFrame({"cik": c, "month": months, "s12": r12, "p12": r12.shift(12)}))
    r = pd.concat(rows)
    df = df.merge(r, on=["cik", "month"], how="left")
    df[["s12", "p12"]] = df[["s12", "p12"]].fillna(0.0)
    df["sale_int"] = df["s12"] / df["mcap"]
    surge = (df["s12"] > 3 * df["p12"]) & (df["sale_int"] > 0.001)
    df["nosurge"] = np.where(surge, np.nan, 1.0)
    return df

if __name__ == "__main__":
    df = build()
    q.portfolio = yearly
    r = q.main(Path(sys.argv[1]), trials=(("Q170a", "sale_int"), ("Q171a", "nosurge")), df=df)
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s q %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull %.2f bear %.2f pass %s" % (
            100*v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"], [round(100*t, 2) for t in v["T2_thirds_ann"]],
            100*v["T4_quarterly"]["ann"], 100*v["T5_mid"]["ann"], 100*v["T6_cost2"]["ann"], 100*v["T6_lag1"]["ann"], 100*v["T3_bull_ann"], 100*v["T3_bear_ann"], v["pass"]))

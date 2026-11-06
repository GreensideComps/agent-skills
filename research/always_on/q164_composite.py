"""Q164 yearly quality/low-vol/value composite. Prereg: /mnt/project-files/research/always-on/prereg/Q164.md."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xsection as xs
import q01_low_vol as q

_orig = q.portfolio
def yearly(df, col, band="large", lag=0, every=12, cost=xs.COST_PER_TURNOVER):
    return _orig(df, col, band=band, lag=lag, every=every, cost=cost)

if __name__ == "__main__":
    df = q.features(xs.load())
    df["gpa"] = df["ttm_gross_profit"] / df["total_assets"]
    ev = df["mcap"] + df["debt_total"].fillna(0) - df["cash"].fillna(0)
    df["ebit_ev"] = (df["ttm_operating_income"] / ev).where(ev > 0)
    df["nvol"] = -df["vol12"]
    lg = df["band"] == "large"
    def z(c):
        g = df[lg].groupby("month")[c]
        out = (df[c] - df["month"].map(g.mean())) / df["month"].map(g.std())
        return out.clip(-3, 3)
    comp = (z("gpa") + z("nvol") + z("ebit_ev")) / 3
    df["neg_comp"] = -comp  # harness holds the lowest
    q.portfolio = yearly    # T1/T2/T3/T5/T6 yearly; T4 passes every=3 explicitly (faster view)
    r = q.main(Path(sys.argv[1]), trials=(("Q164a", "neg_comp"),), df=df)
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s q %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull %.2f bear %.2f pass %s" % (
            100*v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"], [round(100*t, 2) for t in v["T2_thirds_ann"]],
            100*v["T4_quarterly"]["ann"], 100*v["T5_mid"]["ann"], 100*v["T6_cost2"]["ann"], 100*v["T6_lag1"]["ann"], 100*v["T3_bull_ann"], 100*v["T3_bear_ann"], v["pass"]))

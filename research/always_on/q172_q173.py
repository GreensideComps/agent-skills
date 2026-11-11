"""Q172 non-acquirers, Q173 effective tax rate. Prereg: /mnt/project-files/research/always-on/prereg/Q172_Q173.md."""
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
    df["acq"] = df["ttm_acquisitions"].fillna(0).abs() / df["mcap"]
    etr = df["ttm_income_tax"] / df["ttm_pretax_income"]
    df["neg_etr"] = -etr.where((df["ttm_pretax_income"] > 0) & (etr >= 0) & (etr <= 0.6))
    q.portfolio = yearly
    r = q.main(Path(sys.argv[1]), trials=(("Q172a", "acq"), ("Q173a", "neg_etr")), df=df)
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s q %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull %.2f bear %.2f pass %s" % (
            100*v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"], [round(100*t, 2) for t in v["T2_thirds_ann"]],
            100*v["T4_quarterly"]["ann"], 100*v["T5_mid"]["ann"], 100*v["T6_cost2"]["ann"], 100*v["T6_lag1"]["ann"], 100*v["T3_bull_ann"], 100*v["T3_bear_ann"], v["pass"]))

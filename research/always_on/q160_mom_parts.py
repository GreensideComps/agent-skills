"""Q160 intermediate vs recent momentum. Pre-registration: /mnt/project-files/research/always-on/prereg/Q160.md."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xsection as xs
import q01_low_vol as q

if __name__ == "__main__":
    df = q.features(xs.load())
    lr = np.log1p(df["ret"])
    g = lr.groupby(df["cik"])
    # ret at row t = return over month ending t; months t-12..t-7 = shift(7) rolling 6; t-6..t-2 = shift(2) rolling 5
    df["neg_int"] = -g.transform(lambda s: s.shift(7).rolling(6, min_periods=6).sum())
    df["neg_rec"] = -g.transform(lambda s: s.shift(2).rolling(5, min_periods=5).sum())
    r = q.main(Path(sys.argv[1]), trials=(("Q160a", "neg_int"), ("Q160b", "neg_rec")), df=df)
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s q %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull %.2f bear %.2f pass %s" % (
            100*v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"], [round(100*t, 2) for t in v["T2_thirds_ann"]],
            100*v["T4_quarterly"]["ann"], 100*v["T5_mid"]["ann"], 100*v["T6_cost2"]["ann"], 100*v["T6_lag1"]["ann"], 100*v["T3_bull_ann"], 100*v["T3_bear_ann"], v["pass"]))

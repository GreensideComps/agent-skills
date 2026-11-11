"""Q12 buyback surges and Q19 shareholder yield, always-on loop.
Prereg: /mnt/project-files/research/always-on/prereg/Q12_Q19.md. `q01_low_vol.portfolio` buys the lowest values."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import q01_low_vol as q  # noqa: E402

DATA = Path("/mnt/project-files/research-data")


def features() -> pd.DataFrame:
    df = q.features(q.xs.load()).sort_values(["cik", "month"])
    sic = pd.read_csv(DATA / "sec_companies.csv.gz", usecols=["cik", "sic"])
    df = df.merge(sic, on="cik", how="left")
    df = df[~df["sic"].between(6000, 6799)].copy()
    mcap = df["mcap"].where(df["mcap"] > 0)
    bb = df["ttm_buybacks"].abs()
    dv = df["ttm_dividends_paid"].abs().fillna(0)
    g = df.groupby("cik")
    bby = bb / mcap
    bby12 = g["ttm_buybacks"].shift(12).abs() / g["mcap"].shift(12).where(lambda x: x > 0)
    df["b_surge"] = np.where((bby >= 0.02) & (bb >= 2 * g["ttm_buybacks"].shift(12).abs()), 0.0, np.nan)
    df["b_yield"] = -bby
    df["b_chg"] = -(bby - bby12)
    sy = (bb.fillna(0) + dv) / mcap
    sy = sy.where(bb.notna() | df["ttm_dividends_paid"].notna())
    issue = ((df["shares_out"] - g["shares_out"].shift(12)).clip(lower=0) * df["close_raw"]) / mcap
    mom = g["ret"].transform(lambda s: (1 + s.shift(1)).rolling(11, min_periods=11).apply(lambda x: x.prod(), raw=True) - 1)
    df["sy"], df["sy_net"], df["sy_mom"] = -sy, -(sy - issue.fillna(0)), (-sy).where(mom > 0)
    return df


if __name__ == "__main__":
    trials = (("Q12a", "b_surge"), ("Q12b", "b_yield"), ("Q12c", "b_chg"), ("Q19a", "sy"), ("Q19b", "sy_net"), ("Q19c", "sy_mom"))
    r = q.main(Path(sys.argv[1]), trials, features())
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s qtr %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull/bear %.1f/%.1f pass %s" % (
            100 * v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"],
            [round(100 * t, 1) for t in v["T2_thirds_ann"]], 100 * v["T4_quarterly"]["ann"], 100 * v["T5_mid"]["ann"],
            100 * v["T6_cost2"]["ann"], 100 * v["T6_lag1"]["ann"], 100 * v["T3_bull_ann"], 100 * v["T3_bear_ann"], v["pass"]))

"""Q08 pre-FOMC drift, always-on loop. Prereg: /mnt/project-files/research/always-on/prereg/Q08.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("/mnt/project-files/research-data")
COST = 0.0020


def load():
    kf = pd.read_csv(DATA / "french/F-F_Research_Data_Factors_daily.csv", skiprows=4, names=["d", "mkt", "smb", "hml", "rf"])
    kf = kf[kf["d"].astype(str).str.match(r"^\d{8}$")].copy()
    kf["d"] = pd.to_datetime(kf["d"].astype(str))
    for c in ["mkt", "rf"]:
        kf[c] = kf[c].astype(float) / 100
    kf = kf[(kf["d"] >= "1993-06-01") & (kf["d"] <= "2022-12-31")].set_index("d")
    return kf  # mkt is already in excess of rf


def windows(kf, dates, which):
    idx = kf.index
    rows = []
    for d in dates:
        pos = idx.searchsorted(d)
        if pos >= len(idx) or idx[pos] != d or pos < 2:
            continue
        days = {"a": [pos], "b": [pos - 1], "c": [pos - 1, pos]}[which]
        ex = np.prod(1 + kf["mkt"].iloc[days] + kf["rf"].iloc[days]) - np.prod(1 + kf["rf"].iloc[days])
        rows.append({"d": d, "ex": ex})
    return pd.DataFrame(rows).set_index("d")["ex"]


def tstat(x):
    x = x.dropna()
    return float(x.mean() / x.std() * np.sqrt(len(x))) if len(x) > 2 else None


def main(out):
    kf = load()
    dates = pd.to_datetime(pd.read_csv(DATA / "fomc_meeting_dates_1994_2022.csv")["date"])
    lvl = (1 + kf["mkt"] + kf["rf"]).cumprod()
    bull = (lvl > lvl.rolling(200).mean()).shift(1)
    vol = kf["mkt"].rolling(20).std().shift(1)
    hi = vol > vol.median()
    res = {}
    for tid, w in [("Q08a", "a"), ("Q08b", "b"), ("Q08c", "c")]:
        ex = windows(kf, dates, w)
        net = ex - COST
        post = net["2012":]
        h1, h2 = post[:"2016"], post["2017":]
        r = {"post_mean_net": float(post.mean()), "post_t": tstat(post), "post_n": len(post),
             "pre_mean_net": float(net[:"2011"].mean()), "pre_t": tstat(net[:"2011"]),
             "halves": [float(h1.mean()), float(h2.mean())],
             "bull": float(net[bull.reindex(net.index) == True].mean()), "bear": float(net[bull.reindex(net.index) == False].mean()),
             "hivol": float(net[hi.reindex(net.index) == True].mean()), "lovol": float(net[hi.reindex(net.index) == False].mean()),
             "cost2_post": float((ex - 2 * COST)["2012":].mean()),
             "gross_post_mean": float(ex["2012":].mean()),
             "ann_post_on_10pct_reserve": float(post.sum() / 11 * 0.10)}
        r["pass"] = bool((r["post_t"] or 0) >= 3.5 and r["post_mean_net"] > 0 and min(r["halves"]) > 0)
        res[tid] = r
    out.write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    for k, v in main(Path(sys.argv[1])).items():
        print(k, {a: (round(b * 100, 3) if isinstance(b, float) and "t" not in a.split("_")[-1] else b) for a, b in v.items()})

"""Q38 turn-of-month, always-on loop. Prereg: /mnt/project-files/research/always-on/prereg/Q38.md. Reuses Q08 data/stats."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from q08_fomc import COST, load, tstat  # noqa: E402


def windows(kf, lo, hi, cost=COST):
    idx = kf.index
    last = pd.Series(idx, index=idx).groupby(idx.to_period("M")).max().values
    rows = []
    for d in last:
        pos = idx.get_loc(d)
        a, b = pos + lo + 1, pos + hi  # day -1 is `pos`; +k is pos+k
        if a < 0 or b >= len(idx):
            continue
        sl = slice(a, b + 1)
        ex = np.prod(1 + kf["mkt"].iloc[sl] + kf["rf"].iloc[sl]) - np.prod(1 + kf["rf"].iloc[sl])
        rows.append({"d": d, "ex": ex - cost, "gross": ex, "days": b - a + 1})
    return pd.DataFrame(rows).set_index("d")


def main(out):
    kf = load()
    lvl = (1 + kf["mkt"] + kf["rf"]).cumprod()
    bull = (lvl > lvl.rolling(200).mean()).shift(1)
    hi = kf["mkt"].rolling(20).std().shift(1)
    hi = hi > hi.median()
    res = {}
    post_bh = float(kf["mkt"]["2012":].mean() * 252)
    for tid, lo, h in [("Q38a", -1, 3), ("Q38b", -1, 1), ("Q38c", -4, 3)]:
        w = windows(kf, lo, h)
        net, post = w["ex"], w["ex"]["2012":]
        h1, h2 = post[:"2016"], post["2017":]
        days = w["days"].iloc[0]
        r = {"post_mean_net": float(post.mean()), "post_t": tstat(post), "post_n": len(post),
             "pre_mean_net": float(net[:"2011"].mean()), "pre_t": tstat(net[:"2011"]),
             "halves": [float(h1.mean()), float(h2.mean())],
             "bull": float(net[bull.reindex(net.index) == True].mean()), "bear": float(net[bull.reindex(net.index) == False].mean()),
             "hivol": float(net[hi.reindex(net.index) == True].mean()), "lovol": float(net[hi.reindex(net.index) == False].mean()),
             "cost2_post": float((w["gross"] - 2 * COST)["2012":].mean()),
             "gross_post_per_day": float(w["gross"]["2012":].mean() / days),
             "bh_post_per_day": post_bh / 252,
             "strategy_ann_excess_post": float(post.mean() * 12), "bh_ann_excess_post": post_bh}
        r["pass"] = bool((r["post_t"] or 0) >= 3.5 and min(r["halves"]) > 0 and r["cost2_post"] > 0)
        res[tid] = r
    out.write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    for k, v in main(Path(sys.argv[1])).items():
        print(k, {a: (round(b * 100, 3) if isinstance(b, float) and not a.endswith("_t") else b) for a, b in v.items()})

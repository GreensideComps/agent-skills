"""Q73 earnings-season months, Q74 options-expiry week (US market timing), always-on loop.
Prereg: /mnt/project-files/research/always-on/prereg/Q73_Q77.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from q08_fomc import load as load_daily, tstat  # noqa: E402
from q44_q48_timing import COST, section, summ  # noqa: E402


def q73(cost=COST):
    f = section("F-F_Research_Data_Factors.csv")
    m, rf = f["Mkt-RF"] + f["RF"], f["RF"]
    ins = m.index.month.isin([1, 4, 7, 10])
    strat = m.where(ins, rf) - pd.Series(m.index.month.isin([1, 2, 4, 5, 7, 8, 10, 11]), index=m.index) * cost
    return strat - m, m


def q74(cost=COST):
    d = load_daily()
    d = d[(d.index >= "2000-01-01") & (d.index <= "2022-12-31")]
    idx = d.index
    third_fri = {}
    for p in pd.period_range("2000-01", "2022-12", freq="M"):
        days = pd.date_range(p.start_time, p.end_time, freq="W-FRI")
        third_fri[p] = days[2]
    rows = []
    for p, fri in third_fri.items():
        mon = fri - pd.Timedelta(days=4)
        sl = d[(idx >= mon) & (idx <= fri)]
        if len(sl) == 0:
            continue
        ex = np.prod(1 + sl["mkt"] + sl["rf"]) - np.prod(1 + sl["rf"])
        rows.append({"d": fri, "ex": ex - cost, "gross": ex})
    return pd.DataFrame(rows).set_index("d")


def main(out: Path):
    res = {}
    ex, m = q73()
    x = summ(ex, m)
    x["cost2"] = summ(q73(2 * COST)[0])["ex_ann"]
    post = ex["2007":]
    x["since2007"], x["t_since2007"] = float(post.mean() * 12), tstat(post)
    x["pass"] = bool((x["t"] or 0) >= 3.5 and x["ex_ann"] > 0 and min(x["halves"]) > 0 and x["cost2"] > 0
                     and x["since2007"] > 0 and (x["t_since2007"] or 0) >= 2.5)
    res["Q73a"] = x
    w = q74()
    net, post = w["ex"], w["ex"]["2007":]
    h = len(net) // 2
    y = {"n": len(net), "mean_net": float(net.mean()), "t": tstat(net), "halves": [float(net.iloc[:h].mean()), float(net.iloc[h:].mean())],
         "gross_mean": float(w["gross"].mean()), "cost2": float((w["gross"] - 2 * COST).mean()),
         "since2007": float(post.mean()), "t_since2007": tstat(post)}
    y["pass"] = bool((y["t"] or 0) >= 3.5 and min(y["halves"]) > 0 and y["cost2"] > 0 and (y["t_since2007"] or 0) >= 2.5)
    res["Q74a"] = y
    out.write_text(json.dumps(res, indent=1, default=float))
    return res


if __name__ == "__main__":
    for k, v in main(Path(sys.argv[1])).items():
        print(k, {a: (round(b, 4) if isinstance(b, float) else b) for a, b in v.items()})

"""Q53 value-sleeve region rotation, Q67 Dev ex-US small value timing, Q68 Dev ex-US January small caps,
always-on loop. Prereg: /mnt/project-files/research/always-on/prereg/Q53_Q67_Q68.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from q08_fomc import tstat  # noqa: E402
from q44_q48_timing import COST, section, summ, switch  # noqa: E402

DEV6, EM6 = "Developed_ex_US_6_Portfolios_ME_BE-ME.csv", "Emerging_Markets_6_Portfolios_ME_BE-ME.csv"


def mkt(name):
    f = section(name)
    return f["Mkt-RF"] + f["RF"]


def q53(lag=0, cost=COST):
    v = pd.DataFrame({"us": section("Portfolios_Formed_on_BE-ME.csv")["Hi 30"], "dev": section(DEV6)["BIG HiBM"],
                      "em": section(EM6)["BIG HiBM"]}).dropna()
    m = pd.DataFrame({"us": mkt("F-F_Research_Data_Factors.csv"), "dev": mkt("Developed_ex_US_3_Factors.csv"),
                      "em": mkt("Emerging_5_Factors.csv")}).reindex(v.index)
    mom = (1 + v).rolling(12).apply(np.prod, raw=True) - 1
    ch = pd.get_dummies(mom.fillna(-np.inf).idxmax(axis=1)).reindex(columns=v.columns, fill_value=0).astype(float)
    ch[mom.isna().any(axis=1)] = np.nan
    bench = m @ pd.Series({"us": 0.6, "dev": 0.3, "em": 0.1})
    return (switch(ch, v, lag, cost) - bench).dropna(), bench


def q67(lag=0, cost=COST):
    p, m = section(DEV6), mkt("Developed_ex_US_3_Factors.csv")
    r = pd.DataFrame({"a": p["SMALL HiBM"], "b": p["SMALL LoBM"], "m": m}).dropna()
    mom = (1 + r).rolling(12).apply(np.prod, raw=True) - 1
    win = mom["a"] > mom["b"]
    ch = pd.DataFrame({"a": win.astype(float), "b": 0.0, "m": (~win).astype(float)}, index=r.index)
    ch[mom.isna().any(axis=1)] = np.nan
    return (switch(ch, r, lag, cost) - r["m"]).dropna(), r["m"]


def q68(lag=0, cost=COST):
    p, m = section(DEV6), mkt("Developed_ex_US_3_Factors.csv")
    small = p[["SMALL LoBM", "ME1 BM2", "SMALL HiBM"]].mean(axis=1)
    r = pd.DataFrame({"s": small, "m": m}).dropna()
    jan = r.index.month == 1
    strat = r["s"].where(jan, r["m"]) - pd.Series(r.index.month.isin([1, 2]), index=r.index) * cost
    return (strat - r["m"]), r["m"]


def main(out: Path):
    res = {}
    for tid, fn in [("Q53a", q53), ("Q67a", q67), ("Q68a", q68)]:
        ex, b = fn()
        x = summ(ex, b)
        x["cost2"] = summ(fn(cost=2 * COST)[0])["ex_ann"]
        x["lag1"] = summ(fn(lag=1)[0])["ex_ann"] if tid != "Q68a" else x["ex_ann"]
        post = ex["2007":]
        x["since2007"], x["t_since2007"] = float(post.mean() * 12), tstat(post)
        x["pass"] = bool((x["t"] or 0) >= 3.5 and x["ex_ann"] > 0 and min(x["halves"]) > 0 and x["cost2"] > 0
                         and x["lag1"] > 0 and x["since2007"] > 0 and (x["t_since2007"] or 0) >= 2.5)
        res[tid] = x
    out.write_text(json.dumps(res, indent=1, default=float))
    return res


if __name__ == "__main__":
    for k, v in main(Path(sys.argv[1])).items():
        print(k, {a: (round(b, 4) if isinstance(b, float) else ([round(c, 4) for c in b] if isinstance(b, list) else b)) for a, b in v.items()})

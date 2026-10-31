"""Q78 revenue acceleration (stock level), Q79 seasonal defensive rotation, Q80 low-correlation industries,
always-on loop. Prereg: /mnt/project-files/research/always-on/prereg/Q78_Q80.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import q01_low_vol as q  # noqa: E402
from q08_fomc import tstat  # noqa: E402
from q33_q37_quality import DATA  # noqa: E402
from q44_q48_timing import COST, section, summ  # noqa: E402

DEFENSIVE = ["Food", "Soda", "Beer", "Smoke", "Hshld", "Hlth", "MedEq", "Drugs", "Util", "Telcm"]


def q78_features() -> pd.DataFrame:
    df = q.features(q.xs.load()).sort_values(["cik", "month"])
    sic = pd.read_csv(DATA / "sec_companies.csv.gz", usecols=["cik", "sic"])
    df = df.merge(sic, on="cik", how="left")
    df = df[~df["sic"].between(6000, 6799)].copy()
    df["_rev"] = df["ttm_revenue"].where(df["ttm_revenue"] > 0)
    g = df["_rev"] / df.groupby("cik")["_rev"].shift(12) - 1
    df["_g"] = g
    g3, g6 = df.groupby("cik")["_g"].shift(3), df.groupby("cik")["_g"].shift(6)
    df["racc"] = np.where((g > g3) & (g3 > g6), 0.0, np.nan)
    return df


def market():
    f = section("F-F_Research_Data_Factors.csv")
    return f["Mkt-RF"] + f["RF"]


def q79(cost=COST):
    ind, m = section("49_Industry_Portfolios.csv"), market()
    d = ind[DEFENSIVE].mean(axis=1)
    summer = m.index.month.isin([5, 6, 7, 8, 9, 10])
    strat = d.where(summer, m) - pd.Series(m.index.month.isin([5, 11]), index=m.index) * cost
    return (strat - m).dropna(), m


def q80(cost=COST):
    ind, m = section("49_Industry_Portfolios.csv"), market()
    out, prev = [], set()
    for yr in range(1929, 2022):
        end = pd.Period(f"{yr}-12", "M")
        win = ind.loc[end - 35:end]
        mw = m.loc[end - 35:end]
        ok = win.columns[win.notna().sum() >= 36]
        corr = win[ok].corrwith(mw).sort_values()
        pick = list(corr.index[:5])
        nxt = ind.loc[end + 1:end + 12, pick].mean(axis=1)
        turn = len(set(pick) - prev) / 5
        nxt.iloc[0] -= turn * cost
        prev = set(pick)
        out.append(nxt)
    s = pd.concat(out)
    return (s - m.reindex(s.index)).dropna(), m


def main(out: Path):
    res = {k: v for k, v in q.main(out.with_name("Q78.json"), (("Q78a", "racc"),), q78_features()).items()}
    for tid, fn in [("Q79a", q79), ("Q80a", q80)]:
        ex, b = fn()
        x = summ(ex, b)
        x["cost2"] = summ(fn(2 * COST)[0])["ex_ann"]
        post = ex["2007":]
        x["since2007"], x["t_since2007"] = float(post.mean() * 12), tstat(post)
        x["pass"] = bool((x["t"] or 0) >= 3.5 and x["ex_ann"] > 0 and min(x["halves"]) > 0 and x["cost2"] > 0
                         and x["since2007"] > 0 and (x["t_since2007"] or 0) >= 2.5)
        res[tid] = x
    out.write_text(json.dumps(res, indent=1, default=float))
    return res


if __name__ == "__main__":
    r = main(Path(sys.argv[1]))
    v = r["Q78a"]
    print("Q78a ann %.2f%% t %.2f dsr %.3f thirds %s c2 %.2f%% lag %.2f%% pass %s" % (100 * v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"],
          [round(100 * t, 1) for t in v["T2_thirds_ann"]], 100 * v["T6_cost2"]["ann"], 100 * v["T6_lag1"]["ann"], v["pass"]))
    for k in ("Q79a", "Q80a"):
        print(k, {a: (round(b, 4) if isinstance(b, float) else ([round(c, 4) for c in b] if isinstance(b, list) else b)) for a, b in r[k].items()})

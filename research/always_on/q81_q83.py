"""Q81 industry momentum, Q82 post-crash small caps, Q83 3-year industry reversal (KF data), always-on loop.
Prereg: /mnt/project-files/research/always-on/prereg/Q81_Q83.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from q08_fomc import tstat  # noqa: E402
from q44_q48_timing import COST, section, summ  # noqa: E402
from q78_q80 import market  # noqa: E402


def pick_top(score: pd.DataFrame, rets: pd.DataFrame, k: int, cost: float, every: int = 1) -> pd.Series:
    w = pd.DataFrame(0.0, index=rets.index, columns=rets.columns)
    cur = None
    for i, t in enumerate(rets.index):
        if i % every == 0 or cur is None:
            s = score.loc[t].dropna()
            cur = list(s.sort_values(ascending=False).index[:k]) if len(s) >= k else None
        if cur:
            w.loc[t, cur] = 1 / k
    w = w.shift(1)
    turn = w.diff().abs().sum(axis=1) / 2
    return ((w * rets.fillna(0)).sum(axis=1) - turn * cost)[w.sum(axis=1) > 0]


def q81(cost=COST):
    ind = section("49_Industry_Portfolios.csv")
    mom = ((1 + ind).rolling(11).apply(np.prod, raw=True) - 1).shift(1)
    s = pick_top(mom, ind, 5, cost)
    m = market()
    return (s - m.reindex(s.index)).dropna(), m


def q82(cost=COST):
    m, small = market(), section("Portfolios_Formed_on_ME.csv")["Lo 30"]
    lvl = (1 + m).cumprod()
    dd = lvl / lvl.cummax() - 1
    hold, left = [], 0
    for t in m.index:
        hold.append(left > 0)
        left = left - 1 if left > 0 else (12 if dd.loc[t] < -0.20 else 0)
    hold = pd.Series(hold, index=m.index)
    strat = small.where(hold, m) - (hold != hold.shift()).astype(float) * cost
    return (strat - m).dropna(), m


def q83(cost=COST):
    ind = section("49_Industry_Portfolios.csv")
    r36 = (1 + ind).rolling(36).apply(np.prod, raw=True) - 1
    s = pick_top(-r36.where(pd.Series(r36.index.month == 12, index=r36.index), axis=0).ffill(limit=11), ind, 5, cost, every=1)
    m = market()
    return (s - m.reindex(s.index)).dropna(), m


def main(out: Path):
    res = {}
    for tid, fn in [("Q81a", q81), ("Q82a", q82), ("Q83a", q83)]:
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
    for k, v in main(Path(sys.argv[1])).items():
        print(k, {a: (round(b, 4) if isinstance(b, float) else ([round(c, 4) for c in b] if isinstance(b, list) else b)) for a, b in v.items()})

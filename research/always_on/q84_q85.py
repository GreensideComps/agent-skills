"""Q84 broad-industry momentum, Q85 quarterly industry momentum (follow-ups to Q81a), always-on loop.
Prereg: /mnt/project-files/research/always-on/prereg/Q84_Q85.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from q08_fomc import tstat  # noqa: E402
from q44_q48_timing import COST, section, summ  # noqa: E402
from q78_q80 import market  # noqa: E402
from q81_q83 import pick_top  # noqa: E402

SPEC = {"Q84a": ("12_Industry_Portfolios.csv", 3, 1), "Q85a": ("49_Industry_Portfolios.csv", 5, 3)}


def run(tid, cost=COST):
    f, k, every = SPEC[tid]
    ind = section(f)
    mom = ((1 + ind).rolling(11).apply(np.prod, raw=True) - 1).shift(1)
    s = pick_top(mom, ind, k, cost, every=every)
    m = market()
    return (s - m.reindex(s.index)).dropna(), m


def main(out: Path):
    res = {}
    for tid in SPEC:
        ex, b = run(tid)
        x = summ(ex, b)
        x["cost2"] = summ(run(tid, 2 * COST)[0])["ex_ann"]
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

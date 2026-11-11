"""Q64 Halloween effect (hold Nov-Apr, cash May-Oct), always-on loop. Prereg: /mnt/project-files/research/always-on/prereg/Q64.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from q08_fomc import tstat  # noqa: E402
from q44_q48_timing import COST, section, summ  # noqa: E402

FILES = {"Q64a": "F-F_Research_Data_Factors.csv", "Q64b": "Developed_ex_US_3_Factors.csv", "Q64c": "Emerging_5_Factors.csv"}


def run(tid, cost=COST):
    f, rf = section(FILES[tid]), section("F-F_Research_Data_Factors.csv")["RF"]
    mkt = (f["Mkt-RF"] + f["RF"]).dropna()
    rf = rf.reindex(mkt.index)
    inside = mkt.index.month.isin([11, 12, 1, 2, 3, 4])
    strat = mkt.where(inside, rf)
    switch = mkt.index.month.isin([11, 5])  # enter at start of Nov, exit at start of May
    strat = strat - switch * cost
    return (strat - mkt), mkt, f["Mkt-RF"].dropna(), inside


def main(out: Path):
    res = {}
    for tid in FILES:
        ex, mkt, mx, inside = run(tid)
        x = summ(ex, mkt)
        x["cost2"] = summ(run(tid, 2 * COST)[0])["ex_ann"]
        x["since2007"] = float(ex["2007":].mean() * 12)
        win, sum_ = mx[inside[: len(mx)]], mx[~inside[: len(mx)]]
        x["nov_apr_minus_may_oct_monthly"] = float(win.mean() - sum_.mean())
        x["seasonal_t"] = tstat(win) and float((win.mean() - sum_.mean()) / (win.var() / len(win) + sum_.var() / len(sum_)) ** 0.5)
        x["pass"] = bool((x["t"] or 0) >= 3.5 and x["ex_ann"] > 0 and min(x["halves"]) > 0 and x["cost2"] > 0)
        res[tid] = x
    out.write_text(json.dumps(res, indent=1, default=float))
    return res


if __name__ == "__main__":
    for k, v in main(Path(sys.argv[1])).items():
        print(k, {a: (round(b, 4) if isinstance(b, float) else b) for a, b in v.items()})

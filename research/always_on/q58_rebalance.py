"""Q58 rebalancing premium on a 60/30/10 regional mix vs buy-and-drift, always-on loop.
Prereg: /mnt/project-files/research/always-on/prereg/Q58.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from q44_q48_timing import COST, section, summ  # noqa: E402

TARGET = pd.Series({"us": 0.6, "dev": 0.3, "em": 0.1})


def rets() -> pd.DataFrame:
    us, dv, em = section("F-F_Research_Data_Factors.csv"), section("Developed_ex_US_3_Factors.csv"), section("Emerging_5_Factors.csv")
    return pd.DataFrame({"us": us["Mkt-RF"] + us["RF"], "dev": dv["Mkt-RF"] + dv["RF"], "em": em["Mkt-RF"] + em["RF"]}).dropna()


def path(r: pd.DataFrame, every: int | None, cost: float) -> pd.Series:
    w, out = TARGET.copy(), []
    for m, x in r.iterrows():
        g = (w * (1 + x)).sum()
        out.append(g - 1)
        w = w * (1 + x) / g
        if every == 1 or (every == 12 and m.month == 12):
            out[-1] -= (w - TARGET).abs().sum() / 2 * cost
            w = TARGET.copy()
    return pd.Series(out, index=r.index)


def main(out: Path):
    r = rets()
    drift = path(r, None, 0)
    res = {}
    for tid, every in [("Q58a", 1), ("Q58b", 12)]:
        ex = path(r, every, COST) - drift
        x = summ(ex, drift)
        x["cost2"] = summ(path(r, every, 2 * COST) - drift)["ex_ann"]
        x["since2007"] = float(ex["2007":].mean() * 12)
        x["pass"] = bool((x["t"] or 0) >= 3.5 and x["ex_ann"] > 0 and min(x["halves"]) > 0 and x["cost2"] > 0)
        res[tid] = x
    out.write_text(json.dumps(res, indent=1, default=float))
    return res


if __name__ == "__main__":
    for k, v in main(Path(sys.argv[1])).items():
        print(k, {a: (round(b, 4) if isinstance(b, float) else b) for a, b in v.items()})

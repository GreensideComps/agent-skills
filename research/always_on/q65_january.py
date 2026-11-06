"""Q65 January small caps (hold KF ME Lo 30 in January, US market otherwise), always-on loop.
Prereg: /mnt/project-files/research/always-on/prereg/Q61_Q65.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from q44_q48_timing import COST, section, summ  # noqa: E402


def run(cost=COST):
    f, p = section("F-F_Research_Data_Factors.csv"), section("Portfolios_Formed_on_ME.csv")
    r = pd.DataFrame({"s": p["Lo 30"], "m": f["Mkt-RF"] + f["RF"]}).dropna()
    jan = r.index.month == 1
    strat = r["s"].where(jan, r["m"]) - pd.Series(r.index.month.isin([1, 2]), index=r.index) * cost
    return strat - r["m"], r["m"]


def main(out: Path):
    ex, m = run()
    x = summ(ex, m)
    x["cost2"] = summ(run(2 * COST)[0])["ex_ann"]
    x["lag1"] = x["ex_ann"]  # calendar rule: no signal lag applies
    x["since2007"] = float(ex["2007":].mean() * 12)
    x["pass"] = bool((x["t"] or 0) >= 3.5 and x["ex_ann"] > 0 and min(x["halves"]) > 0 and x["cost2"] > 0)
    res = {"Q65a": x}
    out.write_text(json.dumps(res, indent=1, default=float))
    return res


if __name__ == "__main__":
    for k, v in main(Path(sys.argv[1])).items():
        print(k, {a: (round(b, 4) if isinstance(b, float) else b) for a, b in v.items()})

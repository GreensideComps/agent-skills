"""Q49-Q52 style timing (Q48a rule on other markets and styles), always-on loop.
Prereg: /mnt/project-files/research/always-on/prereg/Q49_Q52.md. Truncates at 2022-12 via q44_q48_timing.section."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from q44_q48_timing import COST, section, summ, switch  # noqa: E402

SPEC = {  # trial: (portfolio file, style col, opposite col, market factors file)
    "Q49a": ("Developed_ex_US_6_Portfolios_ME_BE-ME.csv", "BIG HiBM", "BIG LoBM", "Developed_ex_US_3_Factors.csv"),
    "Q49b": ("Emerging_Markets_6_Portfolios_ME_BE-ME.csv", "BIG HiBM", "BIG LoBM", "Emerging_5_Factors.csv"),
    "Q50a": ("10_Portfolios_Prior_12_2.csv", "Hi PRIOR", "Lo PRIOR", "F-F_Research_Data_Factors.csv"),
    "Q51a": ("Portfolios_Formed_on_OP.csv", "Hi 30", "Lo 30", "F-F_Research_Data_Factors.csv"),
    "Q52a": ("Portfolios_Formed_on_INV.csv", "Lo 30", "Hi 30", "F-F_Research_Data_Factors.csv"),
    # Q54-Q55 (prereg/Q54_Q55.md): checks of the Q50a pass; "MKT" = compare with the region market itself
    "Q54a": ("Developed_ex_US_6_Portfolios_ME_Prior_12_2.csv", "BIG HiPRIOR", "BIG LoPRIOR", "Developed_ex_US_3_Factors.csv"),
    "Q55a": ("10_Portfolios_Prior_12_2.csv", "Hi PRIOR", "MKT", "F-F_Research_Data_Factors.csv"),
}


def run(tid, lag=0, cost=COST):
    pf, a, b, mf = SPEC[tid]
    p, f = section(pf), section(mf)
    mkt = f["Mkt-RF"] + f["RF"]
    r = pd.DataFrame({"a": p[a], "b": mkt if b == "MKT" else p[b], "m": mkt}).dropna()
    mom = (1 + r).rolling(12).apply(np.prod, raw=True) - 1
    win = mom["a"] > mom["b"]
    ch = pd.DataFrame({"a": win.astype(float), "b": 0.0, "m": (~win).astype(float)}, index=r.index)
    ch[mom.isna().any(axis=1)] = np.nan
    return (switch(ch, r, lag, cost) - r["m"]).dropna(), r["m"], win[mom.notna().all(axis=1)]


def main(out: Path, tids=tuple(SPEC)):
    res = {}
    for tid in tids:
        ex, m, win = run(tid)
        x = summ(ex, m)
        x["cost2"] = summ(run(tid, cost=2 * COST)[0])["ex_ann"]
        x["lag1"] = summ(run(tid, lag=1)[0])["ex_ann"]
        x["start"], x["in_style"] = str(ex.index[0]), float(win.mean())
        x["since2007"] = float(ex["2007":].mean() * 12)
        x["pass"] = bool((x["t"] or 0) >= 3.5 and x["ex_ann"] > 0 and min(x["halves"]) > 0 and x["cost2"] > 0 and x["lag1"] > 0)
        res[tid] = x
    out.write_text(json.dumps(res, indent=1, default=float))
    return res


if __name__ == "__main__":
    for k, v in main(Path(sys.argv[1]), tuple(sys.argv[2:]) or tuple(SPEC)).items():
        print(k, {a: (round(b, 4) if isinstance(b, float) else ([round(c, 4) for c in b] if isinstance(b, list) else b)) for a, b in v.items()})

"""Q09 trend to gold and Q10 equity/gold rotation, always-on loop.
Prereg: /mnt/project-files/research/always-on/prereg/Q09_Q10.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("/mnt/project-files/research-data")
COST = 0.0020


def load() -> pd.DataFrame:
    kf = pd.read_csv(DATA / "french/F-F_Research_Data_Factors_daily.csv", skiprows=4, names=["d", "mkt", "smb", "hml", "rf"])
    kf = kf[kf["d"].astype(str).str.match(r"^\d{8}$")].copy()
    kf["d"] = pd.to_datetime(kf["d"].astype(str))
    kf = kf[kf["d"] <= "2022-12-31"]
    kf["eq"] = 1 + (kf["mkt"].astype(float) + kf["rf"].astype(float)) / 100
    kf["tb"] = 1 + kf["rf"].astype(float) / 100
    m = kf.groupby(kf["d"] + pd.offsets.MonthEnd(0))[["eq", "tb"]].prod() - 1
    g = pd.read_csv(DATA / "gold_monthly_worldbank_to_2022.csv", parse_dates=["month"]).set_index("month")["gold"]
    m["gold"] = g.pct_change()
    m["gold_px"] = g
    m["eq_px"] = (1 + m["eq"]).cumprod()
    return m.dropna(subset=["gold"]).loc["1971-01-31":]


def weights(m: pd.DataFrame, tid: str, k: int = 10, lag: int = 0) -> pd.DataFrame:
    eq_on = m["eq_px"] > m["eq_px"].rolling(k).mean()
    au_on = m["gold_px"] > m["gold_px"].rolling(k).mean()
    r12e = m["eq_px"] / m["eq_px"].shift(12) - 1
    r12g = m["gold_px"] / m["gold_px"].shift(12) - 1
    r12t = (1 + m["tb"]).rolling(12).apply(np.prod, raw=True) - 1
    w = pd.DataFrame(0.0, index=m.index, columns=["eq", "gold", "tb"])
    if tid == "Q09a":
        w["eq"] = eq_on.astype(float)
        w["gold"] = (~eq_on & au_on).astype(float)
    elif tid == "Q09b":
        w["eq"] = eq_on.astype(float)
        w["gold"] = (~eq_on).astype(float)
    elif tid == "Q10a":
        w["eq"] = 0.5 * (r12e > 0)
        w["gold"] = 0.5 * (r12g > 0)
    elif tid == "Q10b":
        best = pd.concat([r12e, r12g, r12t], axis=1, keys=["eq", "gold", "tb"]).fillna(-np.inf).idxmax(axis=1)
        for c in ["eq", "gold", "tb"]:
            w[c] = (best == c).astype(float)
    w["tb"] = 1 - w["eq"] - w["gold"]
    return w.shift(1 + lag)  # decided at the prior month-end


def run(m, tid, k=10, lag=0, cost=COST):
    w = weights(m, tid, k, lag).dropna()
    r = (w * m.loc[w.index, ["eq", "gold", "tb"]]).sum(axis=1) - cost * w.diff().abs().sum(axis=1).fillna(0) / 2
    return r, m.loc[w.index, "eq"]


def tstat(x):
    return float(x.mean() / x.std() * np.sqrt(len(x)))


def summ(r, b):
    ex = r - b
    cagr = lambda x: float((1 + x).prod() ** (12 / len(x)) - 1)  # noqa: E731
    dd = lambda x: float(((1 + x).cumprod() / (1 + x).cumprod().cummax() - 1).min())  # noqa: E731
    return {"ex_ann": float(ex.mean() * 12), "t": tstat(ex), "cagr": cagr(r), "bh_cagr": cagr(b), "maxdd": dd(r), "bh_maxdd": dd(b)}


def main(out: Path):
    m = load()
    bull = (m["eq_px"] > m["eq_px"].rolling(10).mean()).shift(1)
    res = {}
    for tid in ["Q09a", "Q09b", "Q10a", "Q10b"]:
        r, b = run(m, tid)
        t = slice("2001-01-31", "2022-12-31")
        x = {"test": summ(r[t], b[t]), "insample_1975_2000": summ(r["1975":"2000"], b["1975":"2000"]),
             "halves": [summ(r["2001":"2011"], b["2001":"2011"])["ex_ann"], summ(r["2012":"2022"], b["2012":"2022"])["ex_ann"]]}
        ex = (r - b)[t]
        x["bull_ex_ann"] = float(ex[bull.reindex(ex.index) == True].mean() * 12)
        x["bear_ex_ann"] = float(ex[bull.reindex(ex.index) == False].mean() * 12)
        r2, b2 = run(m, tid, cost=2 * COST)
        x["cost2_ex_ann"] = summ(r2[t], b2[t])["ex_ann"]
        r3, b3 = run(m, tid, lag=1)
        x["lag1_ex_ann"] = summ(r3[t], b3[t])["ex_ann"]
        if tid.startswith("Q09"):
            x["sma6_ex_ann"] = summ(*[s[t] for s in run(m, tid, k=6)])["ex_ann"]
            x["sma12_ex_ann"] = summ(*[s[t] for s in run(m, tid, k=12)])["ex_ann"]
        x["pass"] = bool(x["test"]["t"] >= 3.5 and x["test"]["ex_ann"] > 0 and min(x["halves"]) > 0)
        res[tid] = x
    out.write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    for k, v in main(Path(sys.argv[1])).items():
        print(k, json.dumps(v, default=lambda z: round(z, 4)))

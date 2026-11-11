"""Q44 region rotation, Q45 volatility-managed exposure, Q46 pre-holiday, Q47 size timing, Q48 value timing,
always-on loop. Prereg: /mnt/project-files/research/always-on/prereg/Q44_Q48.md. Truncates all data at 2022-12."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from q08_fomc import load as load_daily, tstat  # noqa: E402

KF = Path("/mnt/project-files/research-data/french")
COST, END = 0.0020, "2022-12"


def section(name: str, n: int = 0) -> pd.DataFrame:
    """The n-th monthly table (first block of YYYYMM rows) of a Ken French CSV, as decimal returns."""
    lines = (KF / name).read_text(errors="ignore").splitlines()
    blocks, cur, hdr = [], [], None
    for ln in lines:
        f = [x.strip() for x in ln.split(",")]
        if f[0] == "" and len(f) > 1 and cur == []:
            hdr = f[1:]
        elif len(f[0]) == 6 and f[0].isdigit():
            cur.append(f)
        elif cur:
            blocks.append((hdr, cur)); cur = []
    if cur:
        blocks.append((hdr, cur))
    hdr, rows = blocks[n]
    df = pd.DataFrame([r[1:len(hdr) + 1] for r in rows], columns=hdr, index=pd.PeriodIndex([r[0] for r in rows], freq="M"))
    df = df.astype(float).replace(-99.99, np.nan) / 100
    return df[df.index <= END]


def summ(ex: pd.Series, bench: pd.Series | None = None) -> dict:
    ex = ex.dropna()
    h = len(ex) // 2
    out = {"ex_ann": float(ex.mean() * 12), "t": tstat(ex), "months": len(ex),
           "halves": [float(ex.iloc[:h].mean() * 12), float(ex.iloc[h:].mean() * 12)]}
    if bench is not None:
        b = bench.reindex(ex.index)
        lvl = (1 + b.fillna(0)).cumprod()
        bull = (lvl > lvl.rolling(10).mean()).shift(1)
        vol = b.rolling(12).std().shift(1)
        hi = vol > vol.median()
        out.update(bull=float(ex[bull == True].mean() * 12), bear=float(ex[bull == False].mean() * 12),
                   hivol=float(ex[hi == True].mean() * 12), lovol=float(ex[hi == False].mean() * 12))
    return out


def switch(choice: pd.DataFrame, rets: pd.DataFrame, lag: int, cost: float) -> pd.Series:
    """choice: one-hot weights decided at month t; applied to month t+1+lag returns, cost on changes."""
    w = choice.shift(1 + lag)
    turn = w.diff().abs().sum(axis=1) / 2
    return (w * rets).sum(axis=1, min_count=1) - turn * cost


def rotation(lb: int, cash_filter: bool, lag=0, cost=COST):
    us, dv, em = section("F-F_Research_Data_Factors.csv"), section("Developed_ex_US_3_Factors.csv"), section("Emerging_5_Factors.csv")
    r = pd.DataFrame({"us": us["Mkt-RF"] + us["RF"], "dev": dv["Mkt-RF"] + dv["RF"], "em": em["Mkt-RF"] + em["RF"]}).dropna()
    rf = us["RF"].reindex(r.index)
    mom = (1 + r).rolling(lb).apply(np.prod, raw=True) - 1
    best = mom.fillna(-np.inf).idxmax(axis=1)
    ch = pd.get_dummies(best).reindex(columns=r.columns, fill_value=0).astype(float)
    ch[mom.isna().any(axis=1)] = np.nan
    if cash_filter:
        rfc = (1 + rf).rolling(lb).apply(np.prod, raw=True) - 1
        ch[(mom.max(axis=1) - rfc) < 0] = 0.0
    strat = switch(ch, r, lag, cost)
    strat = strat + rf * (1 - ch.shift(1 + lag).sum(axis=1))  # cash earns rf
    bench = r @ pd.Series({"us": 0.6, "dev": 0.3, "em": 0.1})
    return (strat - bench).dropna(), bench


def volman(window: int, lag=0, cost=COST):
    d = load_daily()
    d = d[d.index <= "2022-12-31"]
    m = d.index.to_period("M")
    vol = d["mkt"].rolling(window).std().groupby(m).last()
    tgt = vol.expanding(24).median()
    w = (tgt / vol).clip(upper=1).shift(1 + lag)
    mret = (1 + d["mkt"] + d["rf"]).groupby(m).prod() - 1
    rf = (1 + d["rf"]).groupby(m).prod() - 1
    strat = w * (mret - rf) - w.diff().abs() * cost
    mx = mret - rf
    ok = strat.notna()
    X = np.column_stack([np.ones(ok.sum()), mx[ok]])
    beta, res = np.linalg.lstsq(X, strat[ok], rcond=None)[0], None
    resid = strat[ok] - X @ beta
    se = np.sqrt(np.sum(resid ** 2) / (ok.sum() - 2) * np.linalg.inv(X.T @ X)[0, 0])
    s = summ(strat[ok] - mx[ok], mx + rf)
    s.update(alpha_ann=float(beta[0] * 12), alpha_t=float(beta[0] / se), beta=float(beta[1]),
             sr_strat=float(strat[ok].mean() / strat[ok].std() * np.sqrt(12)), sr_bh=float(mx[ok].mean() / mx[ok].std() * np.sqrt(12)))
    return s


def preholiday(cost=COST):
    d = load_daily()
    d = d[(d.index >= "2000-01-01") & (d.index <= "2022-12-31")]
    nxt = pd.Series(d.index[1:].tolist() + [pd.NaT], index=d.index)
    gap = np.busday_count(d.index.values.astype("datetime64[D]")[:-1], nxt.values.astype("datetime64[D]")[:-1])
    pre = d.iloc[:-1][gap > 1]
    ex = pre["mkt"] - cost
    h = len(ex) // 2
    return {"n": len(ex), "mean_net": float(ex.mean()), "t": tstat(ex), "halves": [float(ex.iloc[:h].mean()), float(ex.iloc[h:].mean())],
            "gross": float(pre["mkt"].mean()), "cost2": float((pre["mkt"] - 2 * cost).mean()), "all_days_mean": float(d["mkt"].mean())}


def styles(kind: str, lag=0, cost=COST):
    us = section("F-F_Research_Data_Factors.csv")
    mkt = us["Mkt-RF"] + us["RF"]
    if kind in ("Q47a",):
        p = section("Portfolios_Formed_on_ME.csv")
        a, b = p["Lo 30"], p["Hi 30"]
    else:
        p = section("Portfolios_Formed_on_BE-ME.csv")
        a, b = p["Hi 30"], p["Lo 30"]
    r = pd.DataFrame({"a": a, "b": b, "m": mkt}).dropna()
    if kind == "Q48b":
        ch = pd.DataFrame({"a": 1.0, "b": 0.0, "m": 0.0}, index=r.index)
    else:
        mom = (1 + r).rolling(12).apply(np.prod, raw=True) - 1
        win = mom["a"] > mom["b"]
        alt = "b" if kind == "Q47a" else "m"
        ch = pd.DataFrame({"a": win.astype(float), "b": 0.0, "m": 0.0}, index=r.index)
        ch[alt] = (~win).astype(float)
        ch[mom.isna().any(axis=1)] = np.nan
    strat = switch(ch, r, lag, cost)
    return (strat - r["m"]).dropna(), r["m"]


def main(out: Path):
    res = {}
    for tid, args in [("Q44a", (12, False)), ("Q44b", (6, False)), ("Q44c", (12, True))]:
        ex, b = rotation(*args)
        x = summ(ex, b)
        x["cost2"] = summ(rotation(*args, cost=2 * COST)[0])["ex_ann"]
        x["lag1"] = summ(rotation(*args, lag=1)[0])["ex_ann"]
        res[tid] = x
    for tid, wdw in [("Q45a", 21), ("Q45b", 63)]:
        x = volman(wdw)
        x["t"] = x["alpha_t"]
        x["cost2"] = volman(wdw, cost=2 * COST)["alpha_ann"]
        x["lag1"] = volman(wdw, lag=1)["alpha_ann"]
        x["ex_ann"] = x["alpha_ann"]
        res[tid] = x
    x = preholiday()
    x.update(ex_ann=x["mean_net"], cost2=x["cost2"], lag1=x["mean_net"])
    res["Q46a"] = x
    for tid in ("Q47a", "Q48a", "Q48b"):
        ex, b = styles(tid)
        x = summ(ex, b)
        x["cost2"] = summ(styles(tid, cost=2 * COST)[0])["ex_ann"]
        x["lag1"] = summ(styles(tid, lag=1)[0])["ex_ann"]
        res[tid] = x
    for x in res.values():
        x["pass"] = bool((x["t"] or 0) >= 3.5 and x["ex_ann"] > 0 and min(x["halves"]) > 0 and x["cost2"] > 0 and x["lag1"] > 0)
    out.write_text(json.dumps(res, indent=1, default=float))
    return res


if __name__ == "__main__":
    for k, v in main(Path(sys.argv[1])).items():
        print(k, {a: (round(b, 4) if isinstance(b, float) else ([round(c, 4) for c in b] if isinstance(b, list) else b)) for a, b in v.items()})

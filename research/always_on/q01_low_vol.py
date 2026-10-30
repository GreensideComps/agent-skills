"""Q01 low volatility, always-on loop. Pre-registration: /mnt/project-files/research/always-on/prereg/Q01.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import edge_registry as reg  # noqa: E402
import xsection as xs  # noqa: E402

START, END = "2015-01-31", "2022-11-30"
N_EXTRA = 94
MIN_FLAGGED = 5  # event portfolios: months with fewer flagged names are skipped  # regime track C7 trials (PR #39), not yet in the registry


def features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["cik", "month"]).copy()
    df["ret"] = df.groupby("cik")["ret_next"].shift(1)  # return over the month ending at `month`
    g = df.groupby("cik")["ret"]
    df["vol12"] = g.transform(lambda s: s.rolling(12, min_periods=12).std())
    df["vol24"] = g.transform(lambda s: s.rolling(24, min_periods=20).std())
    lc = df[(df["band"] == "large") & (df["close_raw"] >= xs.MIN_PRICE)]
    mkt = lc.groupby("month")["ret"].mean().rename("mkt")
    df = df.merge(mkt, left_on="month", right_index=True, how="left")

    def beta(x: pd.DataFrame) -> pd.Series:
        c = x["ret"].rolling(24, min_periods=20).cov(x["mkt"])
        v = x["mkt"].rolling(24, min_periods=20).var()
        return c / v
    df["beta24"] = df.groupby("cik", group_keys=False)[["ret", "mkt"]].apply(beta)
    return df


def portfolio(df, col, band="large", lag=0, every=1, cost=xs.COST_PER_TURNOVER):
    in_band = df["band"].notna() if band == "all" else df["band"] == band
    d = df[(df["month"] >= START) & (df["month"] <= END) & in_band
           & (df["close_raw"] >= xs.MIN_PRICE) & df["ret_next"].notna()].copy()
    if lag:
        d[col] = d.groupby("cik")[col].shift(lag)  # signal one month stale
    rows, held = [], set()
    for i, (mo, g) in enumerate(d.groupby("month")):
        s = g.dropna(subset=[col])
        flag = s[col].nunique() == 1
        if len(g) < 30 or len(s) < (MIN_FLAGGED if flag else 30):
            continue
        if i % every == 0 or not held:
            if flag:  # a membership flag: hold every flagged name
                new = set(s["cik"])
            else:
                q = pd.qcut((-s[col]).rank(method="first"), 5, labels=False)
                new = set(s.loc[q == 4, "cik"])
            turn = 1.0 if not held else len(new - held) / max(len(new), 1)
            held = new
        else:
            turn = 0.0
        p = g[g["cik"].isin(held)]["ret_next"].mean()
        rows.append({"month": mo, "excess": p - g["ret_next"].mean() - 2 * cost * turn, "univ": g["ret_next"].mean()})
    return pd.DataFrame(rows).set_index("month")


def stats(x: pd.Series) -> dict:
    x = x.dropna()
    return {"months": len(x), "ann": float(x.mean() * 12), "t_nw": xs.newey_west_t(x),
            "sr_m": float(x.mean() / x.std()), "skew": float(x.skew()), "kurt": float(x.kurt() + 3)}


def main(out: Path, trials=(("Q01a", "vol12"), ("Q01b", "vol24"), ("Q01c", "beta24")), df=None, band="large", band2="mid"):
    df = features(xs.load()) if df is None else df
    ev = reg.load()
    n = reg.n_trials(ev) + N_EXTRA
    res = {}
    lc = df[(df["band"] == "large")].groupby("month")["ret"].mean().sort_index()
    idx = (1 + lc.fillna(0)).cumprod()
    bull = (idx > idx.rolling(10).mean()).shift(1)
    mvol = lc.rolling(12).std().shift(1)
    hivol = mvol > mvol[(mvol.index >= START) & (mvol.index <= END)].median()
    for tid, col in trials:
        r = portfolio(df, col, band=band)
        s = stats(r["excess"])
        d = reg.deflated_sharpe(s["sr_m"], s["months"], s["skew"], s["kurt"], reg.LEGACY_STAT, ev)
        # deflate with the larger N (registry + regime track)
        import math, statistics
        nd = statistics.NormalDist(); g_ = 0.5772156649; var = d["var_used"]
        sr0 = math.sqrt(var) * ((1 - g_) * nd.inv_cdf(1 - 1 / n) + g_ * nd.inv_cdf(1 - 1 / (n * math.e)))
        den = math.sqrt(max(1 - s["skew"] * s["sr_m"] + (s["kurt"] - 1) / 4 * s["sr_m"] ** 2, 1e-12))
        dsr = nd.cdf((s["sr_m"] - sr0) * math.sqrt(s["months"] - 1) / den)
        thirds = [float(r["excess"].loc[a:b].mean() * 12) for a, b in xs._thirds(pd.Series(r.index))]
        e = r["excess"]
        res[tid] = {
            "T1_main": s, "dsr": dsr, "n_trials": n,
            "T2_thirds_ann": thirds,
            "T3_bull_ann": float(e[bull.reindex(e.index) == True].mean() * 12),
            "T3_bear_ann": float(e[bull.reindex(e.index) == False].mean() * 12),
            "T3_hivol_ann": float(e[hivol.reindex(e.index) == True].mean() * 12),
            "T3_lovol_ann": float(e[hivol.reindex(e.index) == False].mean() * 12),
            "T4_quarterly": stats(portfolio(df, col, every=3, band=band)["excess"]),
            "T5_mid": stats(portfolio(df, col, band=band2)["excess"]),
            "T6_cost2": stats(portfolio(df, col, cost=2 * xs.COST_PER_TURNOVER, band=band)["excess"]),
            "T6_lag1": stats(portfolio(df, col, lag=1, band=band)["excess"]),
        }
        p = res[tid]
        p["pass"] = bool(dsr > 0.95 and sum(t > 0 for t in thirds) >= 2
                         and p["T6_cost2"]["ann"] > 0 and p["T6_lag1"]["ann"] > 0)
    out.write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    r = main(Path(sys.argv[1]))
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s mid %.2f%% pass %s" % (
            100 * v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"],
            [round(100 * t, 1) for t in v["T2_thirds_ann"]], 100 * v["T5_mid"]["ann"], v["pass"]))

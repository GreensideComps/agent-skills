"""Cross-sectional stock-signal harness (STRATEGY_V2, Stage 1).

Monthly decision dates. At each month-end every company's inputs are what was public then:
fundamentals from `equity/equity/monthly.py` (filed on or before the month-end), price and point-in-time
market cap (cover-page shares outstanding x the close as it traded). The outcome is the next month's
dividend-adjusted return. A signal is a function of one month's cross-section returning a score per
company; the harness reports, per size band:

* information coefficient (Spearman, score vs next-month return), monthly, with a Newey-West t-stat;
* top-minus-bottom decile and top-quintile-minus-universe returns, equal-weighted, gross and after a
  turnover-based cost;
* coverage (how many companies each month had a score, a price and a market cap).

Data files (built by `python -m equity research-data`, kept in the shared project folder because
they are too big for git) are read from $RESEARCH_DATA, default /mnt/project-files/research-data.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(os.environ.get("RESEARCH_DATA", "/mnt/project-files/research-data"))
SIZE_BANDS = {"large": (10e9, math.inf), "mid": (2e9, 10e9), "small": (0.3e9, 2e9)}
MIN_PRICE = 1.0
COST_PER_TURNOVER = 0.0030  # one-way: 0.15% FX + ~0.15% spread for liquid US stocks, as a fraction


def load(data: Path = DATA) -> pd.DataFrame:
    """One row per company-month with metrics, price, market cap, size band and next-month return."""
    m = pd.read_csv(data / "monthly_metrics.csv.gz", dtype={"cik": int})
    p = pd.read_csv(data / "prices_monthly.csv.gz", dtype={"cik": int})
    p = p[p["currency"] == "USD"].sort_values(["cik", "month"]).drop_duplicates(["cik", "month"], keep="last")
    p["ret_next"] = p.groupby("cik")["adjclose"].shift(-1) / p["adjclose"] - 1
    # a gap in monthly bars means the next row is not the next month: no return
    nxt = pd.to_datetime(p.groupby("cik")["month"].shift(-1))
    gap = (nxt.dt.year - pd.to_datetime(p["month"]).dt.year) * 12 + nxt.dt.month - pd.to_datetime(p["month"]).dt.month
    p.loc[gap != 1, "ret_next"] = np.nan
    df = m.merge(p[["cik", "month", "ticker", "close_raw", "adjclose", "ret_next"]], on=["cik", "month"], how="left")
    shares = df["shares_out"].where(df["shares_out"] > 0, df["shares_diluted"])
    df["mcap"] = shares * df["close_raw"]
    df["band"] = None
    for b, (lo, hi) in SIZE_BANDS.items():
        df.loc[(df["mcap"] >= lo) & (df["mcap"] < hi), "band"] = b
    df["month"] = pd.to_datetime(df["month"])
    return df


def investable(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df["close_raw"] >= MIN_PRICE) & df["band"].notna() & df["ret_next"].notna()]


def newey_west_t(x: pd.Series, lags: int = 3) -> float | None:
    x = x.dropna().to_numpy()
    n = len(x)
    if n < 12:
        return None
    e = x - x.mean()
    s = (e @ e) / n
    for k in range(1, lags + 1):
        s += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / math.sqrt(s / n)) if s > 0 else None


def evaluate(df: pd.DataFrame, signal, name: str, start: str = "2012-01-31", end: str = "2022-12-31",
             bands=("large", "mid", "small")) -> dict:
    """Run `signal(month_frame) -> pd.Series` (index aligned to the frame) over [start, end]."""
    d = investable(df[(df["month"] >= start) & (df["month"] <= end)]).copy()
    d["score"] = np.nan
    for mo, g in d.groupby("month"):
        d.loc[g.index, "score"] = signal(g)
    out = {"signal": name, "start": start, "end": end, "bands": {}, "series": {}}
    for b in bands:
        x = d[(d["band"] == b) & d["score"].notna()]
        rows, prev_top = [], set()
        for mo, g in x.groupby("month"):
            if len(g) < 30:
                continue
            ic = g["score"].rank().corr(g["ret_next"].rank())
            q = pd.qcut(g["score"].rank(method="first"), 10, labels=False)
            top, bot = g[q == 9], g[q == 0]
            q5 = g[q >= 8]
            names = set(q5["cik"])
            turn = 1.0 if not prev_top else len(names - prev_top) / max(len(names), 1)
            prev_top = names
            rows.append({"month": mo, "n": len(g), "ic": ic, "d10_d1": top["ret_next"].mean() - bot["ret_next"].mean(),
                         "q5_minus_univ": q5["ret_next"].mean() - g["ret_next"].mean(), "q5_turnover": turn})
        r = pd.DataFrame(rows)
        if r.empty:
            out["bands"][b] = {"months": 0}
            continue
        net = r["q5_minus_univ"] - 2 * COST_PER_TURNOVER * r["q5_turnover"]
        out["series"][b] = r.assign(q5_net=net)
        out["bands"][b] = {
            "months": len(r), "avg_names": float(r["n"].mean()),
            "mean_ic": float(r["ic"].mean()), "ic_t_nw": newey_west_t(r["ic"]), "ic_pos_share": float((r["ic"] > 0).mean()),
            "d10_d1_ann": float(r["d10_d1"].mean() * 12), "d10_d1_t_nw": newey_west_t(r["d10_d1"]),
            "q5_minus_univ_ann_gross": float(r["q5_minus_univ"].mean() * 12),
            "q5_minus_univ_ann_net": float(net.mean() * 12), "q5_net_t_nw": newey_west_t(net),
            "q5_turnover_monthly": float(r["q5_turnover"].mean()),
            "sub_periods_ic": {f"{a.year}-{b_.year}": float(r[(r['month'] >= a) & (r['month'] <= b_)]["ic"].mean())
                               for a, b_ in _thirds(r["month"])},
        }
    return out


def _thirds(months: pd.Series):
    m = sorted(months)
    k = len(m) // 3
    return [(m[0], m[k - 1]), (m[k], m[2 * k - 1]), (m[2 * k], m[-1])] if k else []


def coverage(df: pd.DataFrame) -> pd.DataFrame:
    """Per month: companies filing, with a price, with a market cap, and per size band."""
    g = df.groupby("month")
    c = pd.DataFrame({"filing": g.size(), "with_price": g["close_raw"].count(), "with_mcap": g["mcap"].count()})
    for b in SIZE_BANDS:
        c[b] = df[df["band"] == b].groupby("month").size()
    return c.fillna(0).astype(int)

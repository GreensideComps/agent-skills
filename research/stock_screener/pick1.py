"""pick-1: the system's own stock screener (Q199). Prereg: /mnt/project-files/research/always-on/prereg/Q199.md.

Usage:
  python pick1.py backtest OUT.json      # exploration backtest 2015-2022 only
  python pick1.py live YYYY-MM OUT.csv   # picks from the latest complete month's data (live use, no evaluation)
"""
from __future__ import annotations
import json, math, statistics, sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xsection as xs  # noqa: E402
import edge_registry as reg  # noqa: E402

DATA = xs.DATA
COST = xs.COST_PER_TURNOVER
N_EXTRA = 94 + 8  # regime track C7 + owner timing batch, not in trials.jsonl
TOP, PER_SIC = 15, 3


def load() -> pd.DataFrame:
    df = xs.load()
    df = _extend_partial_month(df)
    co = pd.read_csv(DATA / "sec_companies.csv.gz", usecols=["cik", "sic"])
    df = df.merge(co, on="cik", how="left")
    df = df.sort_values(["cik", "month"]).reset_index(drop=True)
    g = df.groupby("cik")
    df["px"] = df["adjclose"]
    # 12-1 momentum: price at t-1 over price at t-12 (consecutive monthly rows assumed; gaps -> NaN)
    mi = df["month"].dt.year * 12 + df["month"].dt.month
    lag1, lag12 = g["px"].shift(1), g["px"].shift(12)
    ok = (mi - g["month"].shift(12).pipe(lambda s: s.dt.year * 12 + s.dt.month)) == 12
    df["mom"] = (lag1 / lag12 - 1).where(ok)
    sh = df["shares_out"].where(df["shares_out"] > 0, df["shares_diluted"])
    df["sh"] = sh
    df["sh_chg"] = (sh / g["sh"].shift(12) - 1).where(ok)
    df["fcf"] = df["ttm_ocf"] - df["ttm_capex"].abs()
    df["ebitda"] = df["ttm_operating_income"] + df["ttm_d_and_a"].fillna(0)
    nd = df["debt_total"].fillna(0) - df["cash"].fillna(0) - df["short_investments"].fillna(0)
    df["nd_ebitda"] = np.where(nd <= 0, 0.0, nd / df["ebitda"].where(df["ebitda"] > 0))
    ev = df["mcap"] + df["debt_total"].fillna(0) - df["cash"].fillna(0)
    df["fcf_ev"] = (df["fcf"] / ev).where(ev > 0)
    df["gpa"] = df["ttm_gross_profit"] / df["total_assets"]
    df["sic2"] = (df["sic"] // 100)
    return df


def _extend_partial_month(df: pd.DataFrame) -> pd.DataFrame:
    """Live use: the metrics file only has completed months, but prices_monthly carries a row for the current
    (partial) month. Add that month with each company's latest metrics carried forward (as-of) and the latest
    price, so the screen can run mid-month on fresh prices. Backtests cut data at 2022 and never reach this."""
    last_m = df["month"].max()
    p = pd.read_csv(xs.DATA / "prices_monthly.csv.gz", dtype={"cik": int})
    p = p[p["currency"] == "USD"]
    p["month"] = pd.to_datetime(p["month"])
    newer = p[p["month"] > last_m].sort_values("month").drop_duplicates(["cik", "month"], keep="last")
    if newer.empty:
        return df
    base = df[df["month"] == last_m].drop(columns=["ticker", "close_raw", "adjclose", "ret_next", "mcap", "band"])
    add = base.drop(columns=["month"]).merge(newer[["cik", "month", "ticker", "close_raw", "adjclose"]], on="cik")
    shares = add["shares_out"].where(add["shares_out"] > 0, add["shares_diluted"])
    add["mcap"] = shares * add["close_raw"]
    add["ret_next"] = np.nan
    add["band"] = None
    for b, (lo, hi) in xs.SIZE_BANDS.items():
        add.loc[(add["mcap"] >= lo) & (add["mcap"] < hi), "band"] = b
    return pd.concat([df, add[df.columns]], ignore_index=True)


def universe(m: pd.DataFrame, min_cap=2e9) -> pd.DataFrame:
    sic = m["sic"].fillna(0)
    return m[(m["mcap"] >= min_cap) & (m["close_raw"] >= 5) & ~sic.between(6000, 6799) & ~sic.between(4900, 4999)]


def score(u: pd.DataFrame) -> pd.DataFrame:
    gated = u[(u["fcf"] > 0) & (u["ttm_operating_income"] > 0) & (u["nd_ebitda"] < 3)
              & (u["sh_chg"] <= 0.02) & (u["equity"] > 0)].dropna(subset=["gpa", "fcf_ev", "mom"]).copy()
    for c in ["gpa", "fcf_ev", "mom"]:
        x = gated[c]
        gated["z_" + c] = ((x - x.mean()) / x.std()).clip(-3, 3)
    gated["score"] = gated[["z_gpa", "z_fcf_ev", "z_mom"]].mean(axis=1)
    return gated.sort_values("score", ascending=False)


def pick(u: pd.DataFrame) -> pd.DataFrame:
    s, out, per = score(u), [], {}
    for _, r in s.iterrows():
        k = r["sic2"]
        if per.get(k, 0) >= PER_SIC:
            continue
        per[k] = per.get(k, 0) + 1
        out.append(r)
        if len(out) == TOP:
            break
    return pd.DataFrame(out)


def gbp_factor() -> pd.Series:
    """month-end USD-per-GBP; GBP return = (1+r_usd) * fx_t / fx_t+1 - 1."""
    fx = pd.read_csv(DATA / "edge/gbpusd_daily_to_2022.csv.gz")
    fx.columns = ["date", "fx"] + list(fx.columns[2:])
    fx["date"] = pd.to_datetime(fx["date"])
    return fx.set_index("date")["fx"].resample("ME").last()


def vwrp_monthly() -> pd.Series:
    b = pd.read_csv(DATA / "edge/benchmarks_daily_gbp_to_2022.csv.gz", parse_dates=["date"]).set_index("date")
    m = b.resample("ME").last()
    r_vwrl = m["VWRL"].pct_change()
    r_vwrp = m["VWRP"].pct_change()
    r = r_vwrl.copy()
    r[r_vwrp.notna()] = r_vwrp[r_vwrp.notna()]
    return r  # return over the month ending at index


def backtest(df, start="2015-01-31", end="2022-12-31", min_cap=2e9, every=12, lag=0, cost=COST):
    """Monthly rows: return over month m (held names chosen at the last rebalance before m)."""
    months = sorted(df["month"].unique())
    months = [pd.Timestamp(m) for m in months]
    by = {m: g for m, g in df.groupby("month")}
    rows, held, prev = [], [], set()
    for i, m in enumerate(months):
        if m < pd.Timestamp(start) - pd.offsets.MonthEnd(1) or m >= pd.Timestamp(end):
            continue
        g = by[m]
        nxt = m + pd.offsets.MonthEnd(1)
        reb_month = 12 if lag == 0 else 1  # decision at Dec month-end (or Jan for lag)
        due = (m.month == reb_month) if every == 12 else (m.month in (reb_month, (reb_month + 6 - 1) % 12 + 1))
        turn = 0.0
        if due or not held:
            u = universe(g, min_cap)
            if len(u) < 50:
                continue
            p = pick(u)
            new = set(p["cik"])
            turn = 1.0 if not prev else len(new - prev) / max(len(new), 1)
            held, prev = list(new), new
        gu = universe(g, min_cap)
        h = g[g["cik"].isin(held)]
        if h["ret_next"].notna().sum() == 0:
            continue
        # a held name whose next return is missing (delisted / merged): count it at 0, not dropped
        pr = h["ret_next"].fillna(0).mean()
        ur = gu["ret_next"].dropna().mean()
        rows.append({"month": nxt, "port": pr - 2 * cost * turn, "port_gross": pr, "univ": ur, "turn": turn,
                     "n": len(h), "names": ",".join(sorted(h["ticker"].astype(str)))})
    return pd.DataFrame(rows).set_index("month")


def stats(x):
    x = x.dropna()
    return {"months": len(x), "ann": float(x.mean() * 12), "t_nw": xs.newey_west_t(x),
            "sr_m": float(x.mean() / x.std()), "skew": float(x.skew()), "kurt": float(x.kurt() + 3)}


def dsr(s, n):
    ev = reg.load()
    d = reg.deflated_sharpe(s["sr_m"], s["months"], s["skew"], s["kurt"], reg.LEGACY_STAT, ev)
    nd = statistics.NormalDist(); g_ = 0.5772156649
    sr0 = math.sqrt(d["var_used"]) * ((1 - g_) * nd.inv_cdf(1 - 1 / n) + g_ * nd.inv_cdf(1 - 1 / (n * math.e)))
    den = math.sqrt(max(1 - s["skew"] * s["sr_m"] + (s["kurt"] - 1) / 4 * s["sr_m"] ** 2, 1e-12))
    return nd.cdf((s["sr_m"] - sr0) * math.sqrt(s["months"] - 1) / den)


def run_backtest(out: Path):
    df = load()
    df = df[df["month"] <= "2022-12-31"]  # exploration only
    fx = gbp_factor(); vw = vwrp_monthly()
    def gbp(r):  # USD monthly return ending at index -> GBP
        f = fx.reindex(r.index); f0 = fx.shift(1).reindex(r.index)
        return (1 + r) * f0 / f - 1
    main = backtest(df)
    e1 = main["port"] - main["univ"]
    e2 = gbp(main["port"]) - vw.reindex(main.index)
    n = reg.n_trials(reg.load()) + N_EXTRA
    s1 = stats(e1)
    idx = (1 + main["univ"]).cumprod(); bull = (idx > idx.rolling(10).mean()).shift(1)
    thirds = [float(c.mean() * 12) for c in np.array_split(e1, 3)]
    views = {}
    for name, kw in {"T4_half_yearly": dict(every=6), "T5_large_only": dict(min_cap=10e9),
                     "T6_cost2": dict(cost=2 * COST), "T6_lag1": dict(lag=1)}.items():
        b = backtest(df, **kw); views[name] = stats(b["port"] - b["univ"])
    trades = main[main["turn"] > 0]
    res = {"n_trials": n, "B1_vs_universe": s1, "dsr": dsr(s1, n), "B2_vs_vwrp_gbp": stats(e2),
           "portfolio_cagr_gbp": float((1 + gbp(main["port"])).prod() ** (12 / len(main)) - 1),
           "vwrp_cagr_gbp": float((1 + vw.reindex(main.index)).prod() ** (12 / len(main)) - 1),
           "universe_cagr_usd": float((1 + main["univ"]).prod() ** (12 / len(main)) - 1),
           "portfolio_cagr_usd": float((1 + main["port"]).prod() ** (12 / len(main)) - 1),
           "T2_thirds_ann": thirds,
           "T3_bull_ann": float(e1[bull == True].mean() * 12), "T3_bear_ann": float(e1[bull == False].mean() * 12),
           **views,
           "gross_minus_univ_ann": float((main["port_gross"] - main["univ"]).mean() * 12),
           "cost_drag_ann": float((main["port_gross"] - main["port"]).mean() * 12),
           "yearly": {str(y): {"port": float((1 + g["port"]).prod() - 1), "univ": float((1 + g["univ"]).prod() - 1),
                               "names": g["names"].iloc[0]} for y, g in main.groupby(main.index.year)}}
    res["pass"] = bool(res["dsr"] > 0.95 and sum(t > 0 for t in thirds) >= 2 and views["T6_cost2"]["ann"] > 0
                       and views["T6_lag1"]["ann"] > 0 and res["gross_minus_univ_ann"] > res["cost_drag_ann"]
                       and res["B2_vs_vwrp_gbp"]["ann"] > 0)
    out.write_text(json.dumps(res, indent=1))
    return res


def run_live(month: str, out: Path):
    df = load()
    m = df[df["month"] == pd.Timestamp(month) + pd.offsets.MonthEnd(0)]
    p = pick(universe(m))
    cols = ["ticker", "cik", "sic", "mcap", "score", "gpa", "fcf_ev", "mom", "nd_ebitda", "sh_chg", "last_filed"]
    p[cols].to_csv(out, index=False)
    return p[cols]


if __name__ == "__main__":
    if sys.argv[1] == "backtest":
        r = run_backtest(Path(sys.argv[2]))
        print(json.dumps({k: v for k, v in r.items() if k != "yearly"}, indent=1))
        for y, v in r["yearly"].items():
            print(y, "%.1f%% vs %.1f%%" % (100 * v["port"], 100 * v["univ"]), v["names"][:120])
    else:
        print(run_live(sys.argv[2], Path(sys.argv[3])).to_string())

"""Stage 2 (STRATEGY_V2): pre-registered cross-sectional signal tests.

The definitions, windows and pass rules here are frozen by `research/prereg/stage2.md`, committed before any
result was computed. Changing a definition after seeing results is a new trial: it gets a new id, it is
added to TRIALS, and the trial count used to deflate the Sharpe ratio goes up.

Test window: decisions 2015-01 to 2022-11 (returns to 2022-12). The 2023-01 to 2026-09 holdout is not read.

    RESEARCH_DATA=/path python3 stage2.py [out.md]
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

import data_sources
import xsection

START, END = "2015-01-31", "2022-11-30"
HOLDOUT_START = "2023-01-01"
_N = NormalDist()

# SIC to 12 groups (pre-registered). Manufacturing is split where large caps cluster.
GROUPS = [((100, 999), "agri"), ((1000, 1499), "mining_energy"), ((1500, 1799), "construction"),
          ((2800, 2899), "chemicals_pharma"), ((3570, 3579), "computers"), ((3600, 3699), "electronics_semis"),
          ((3800, 3899), "instruments_medtech"), ((2000, 3999), "other_manufacturing"),
          ((4000, 4999), "transport_utilities_telecom"), ((5000, 5999), "trade_retail"),
          ((6000, 6799), "finance"), ((7370, 7379), "software_it"), ((7000, 8999), "services"),
          ((9000, 9999), "other")]


def sic_group(sic) -> str:
    try:
        s = int(sic)
    except (TypeError, ValueError):
        return "unknown"
    for (lo, hi), g in GROUPS:
        if lo <= s <= hi:
            return g
    return "unknown"


def lag(df: pd.DataFrame, col: str, k: int) -> pd.Series:
    """Value of `col` for the same company exactly k months earlier (NaN if that month is missing)."""
    key = df[["cik", "p"]].copy()
    src = df[["cik", "p", col]].copy()
    src["p"] = src["p"] + k
    m = key.merge(src, on=["cik", "p"], how="left")
    return pd.Series(m[col].to_numpy(), index=df.index)


def prepare(df: pd.DataFrame, companies: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["cik", "month"]).reset_index(drop=True)
    df["p"] = df["month"].dt.to_period("M")
    df = df.merge(companies[["cik", "sic"]], on="cik", how="left")
    df["group"] = df["sic"].map(sic_group)
    df["financial"] = df["group"] == "finance"
    gp = df["ttm_gross_profit"].where(df["ttm_gross_profit"].notna(), df["ttm_revenue"] - df["ttm_cost_of_revenue"])
    debt = df["debt_total"].where(df["debt_total"].notna(),
                                  df[["debt_noncurrent", "debt_current", "short_borrowings"]].sum(axis=1, min_count=1))
    cash = df[["cash", "short_investments"]].sum(axis=1, min_count=1)
    ev = df["mcap"] + debt.fillna(0) - cash.fillna(0)
    ta = df["total_assets"].where(df["total_assets"] > 0)
    # S1 valuation
    df["s1a_fcf_yield"] = (df["ttm_ocf"] - df["ttm_capex"].fillna(0)) / df["mcap"]
    df["s1b_ebit_ev"] = (df["ttm_operating_income"] / ev).where(ev > 0)
    # S2 quality
    df["s2a_gross_prof"] = gp / ta
    df["s2b_low_accruals"] = -(df["ttm_net_income"] - df["ttm_ocf"]) / ta
    # S3 fundamental momentum
    rev12 = lag(df, "ttm_revenue", 12)
    df["rev_g"] = (df["ttm_revenue"] / rev12 - 1).where((rev12 > 0) & (df["ttm_revenue"] > 0))
    df["s3a_rev_growth"] = df["rev_g"]
    df["s3b_rev_accel"] = df["rev_g"] - lag(df, "rev_g", 3)
    # S4 earnings surprise: change in TTM EPS when a new quarter arrives (= new quarter minus the same quarter a
    # year earlier), scaled by the std of the company's previous such changes.
    eps3 = lag(df, "ttm_eps_diluted", 3)
    end3 = lag(df, "ttm_end", 3)
    d = (df["ttm_eps_diluted"] - eps3).where(df["ttm_end"].notna() & (df["ttm_end"] != end3) & end3.notna())
    df["eps_d"] = d
    hist = df.groupby("cik")["eps_d"].transform(lambda x: x.shift(1).rolling(36, min_periods=6).std())
    fresh = (df["month"] - pd.to_datetime(df["ttm_end"], errors="coerce")).dt.days <= 75
    df["s4_sue"] = (d / hist).where(fresh & (hist > 0))
    # S5 capital allocation
    adj12 = lag(df, "adjclose", 12)
    mcap12 = lag(df, "mcap", 12)
    df["s5a_low_issuance"] = -(np.log(df["mcap"] / mcap12) - np.log(df["adjclose"] / adj12))
    ta12 = lag(df, "total_assets", 12)
    df["s5b_low_asset_growth"] = -(df["total_assets"] / ta12 - 1).where(ta12 > 0)
    # S6 market behaviour
    a1, a12 = lag(df, "adjclose", 1), adj12
    df["s6a_mom_12_1"] = a1 / a12 - 1
    hi = pd.concat([lag(df, "adjclose", k) for k in range(0, 12)], axis=1).max(axis=1, skipna=False)
    df["s6b_52w_high"] = df["adjclose"] / hi
    return df


def residual_momentum(df: pd.DataFrame, ff3: pd.DataFrame) -> pd.Series:
    """S6c (added 2026-10-14, before running): FF3 residual momentum.

    Monthly total returns are regressed on Mkt-RF, SMB and HML over months t-36..t-2 (at least 24). The score is
    the mean residual over t-12..t-2 divided by their standard deviation (at least 9 of the 11 months).
    """
    r = df["adjclose"] / lag(df, "adjclose", 1) - 1
    f = ff3.copy()
    f.index = f.index.to_period("M")
    out = pd.Series(np.nan, index=df.index)
    for _, idx in df.groupby("cik").groups.items():
        g = df.loc[idx]
        rr = pd.Series(r.loc[idx].to_numpy(), index=g["p"].to_numpy())
        if rr.notna().sum() < 24:
            continue
        j = pd.concat([rr.rename("r"), f], axis=1, join="inner")
        y = (j["r"] - j["RF"]).to_numpy()
        X = np.column_stack([np.ones(len(j)), j[["Mkt-RF", "SMB", "HML"]].to_numpy()])
        pos = {p: i for i, p in enumerate(j.index)}
        for row, p in zip(idx, g["p"]):
            ks = [pos.get(p - k) for k in range(2, 37)]
            ks = [k for k in ks if k is not None and not np.isnan(y[k])]
            if len(ks) < 24:
                continue
            b, *_ = np.linalg.lstsq(X[ks], y[ks], rcond=None)
            form = [pos.get(p - k) for k in range(2, 13)]
            form = [k for k in form if k is not None and not np.isnan(y[k])]
            if len(form) < 9:
                continue
            e = y[form] - X[form] @ b
            sd = e.std(ddof=1)
            if sd > 0:
                out[row] = e.mean() / sd
    return out


def insider_features(df: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    """S7 (added 2026-10-14, before running): officer and director open-market trades filed in the last 6
    months (filing month t-5..t). S7a: (distinct buyers - distinct sellers) / (buyers + sellers), unscored when
    nobody traded. S7b: purchase value / market cap, 0 when there were no purchases."""
    t = trades.copy()
    t["p"] = pd.to_datetime(t["filed"]).dt.to_period("M")
    t["value"] = (t["shares"] * t["price"]).where(t["code"] == "P", 0.0)
    win = pd.concat([t.assign(p=t["p"] + k) for k in range(6)])
    who = win.drop_duplicates(["issuer_cik", "owner_cik", "code", "p"])
    cnt = who.groupby(["issuer_cik", "p", "code"]).size().unstack(fill_value=0)
    val = win.groupby(["issuer_cik", "p"])["value"].sum()
    agg = pd.DataFrame({"buyers": cnt.get("P", 0), "sellers": cnt.get("S", 0)}).join(val.rename("buy_value"), how="outer")
    agg = agg.fillna(0).reset_index().rename(columns={"issuer_cik": "cik"})
    m = df[["cik", "p"]].merge(agg, on=["cik", "p"], how="left")
    b, s_ = m["buyers"].fillna(0), m["sellers"].fillna(0)
    out = pd.DataFrame(index=df.index)
    out["s7a_net_buyers"] = ((b - s_) / (b + s_)).where(b + s_ > 0).to_numpy()
    out["s7b_buy_value"] = (m["buy_value"].fillna(0) / df["mcap"].to_numpy()).to_numpy()
    return out


def _neutral(col: str, exclude_fin: bool):
    def f(g: pd.DataFrame) -> pd.Series:
        x = g[col].where(~g["financial"]) if exclude_fin else g[col]
        return x.groupby(g["group"]).rank(pct=True)
    return f


def _raw(col: str, exclude_fin: bool = False):
    def f(g: pd.DataFrame) -> pd.Series:
        return g[col].where(~g["financial"]) if exclude_fin else g[col]
    return f


# id -> (signal family, description, function). Frozen; see prereg/stage2.md.
TRIALS = {
    "S1a": ("S1", "FCF yield, within SIC group, ex financials", _neutral("s1a_fcf_yield", True)),
    "S1b": ("S1", "EBIT / EV, within SIC group, ex financials", _neutral("s1b_ebit_ev", True)),
    "S2a": ("S2", "Gross profit / assets, within SIC group, ex financials", _neutral("s2a_gross_prof", True)),
    "S2b": ("S2", "Low accruals (OCF - NI) / assets, ex financials", _raw("s2b_low_accruals", True)),
    "S3a": ("S3", "TTM revenue growth, year on year", _raw("s3a_rev_growth")),
    "S3b": ("S3", "Revenue growth acceleration (vs 3 months earlier)", _raw("s3b_rev_accel")),
    "S4": ("S4", "Standardised unexpected EPS, new quarter within 75 days", _raw("s4_sue")),
    "S5a": ("S5", "Low net issuance (12-month market cap change less return)", _raw("s5a_low_issuance")),
    "S5b": ("S5", "Low asset growth, year on year", _raw("s5b_low_asset_growth")),
    "S6a": ("S6", "12-1 month price momentum", _raw("s6a_mom_12_1")),
    "S6b": ("S6", "Close / 12-month high", _raw("s6b_52w_high")),
    # Added 2026-10-14 after the first 11 ran; pre-registered in prereg/stage2.md (addendum) before running.
    "S6c": ("S6", "FF3 residual momentum, 12-2 months", _raw("s6c_resid_mom")),
    "S7a": ("S7", "Insider net buyers ratio, 6 months", _raw("s7a_net_buyers")),
    "S7b": ("S7", "Insider purchase value / market cap, 6 months", _raw("s7b_buy_value")),
}
NOT_RUN = {"S8": "estimate revisions: paid data only",
           "S9": "expectations gap: needs the Stage 3 expectations engine"}


def sharpe_stats(x: pd.Series) -> dict:
    x = x.dropna()
    sr = x.mean() / x.std(ddof=1) if x.std(ddof=1) > 0 else 0.0
    return {"sr": float(sr), "skew": float(x.skew()), "kurt": float(x.kurt() + 3), "n": len(x)}


def deflated_sharpe(st: dict, all_srs: list[float]) -> float:
    """Bailey and Lopez de Prado (2014): probability the true Sharpe beats the best of N unskilled trials."""
    n_trials = len(all_srs)
    var = float(np.var(all_srs, ddof=1)) if n_trials > 1 else 0.0
    g = 0.5772156649
    sr0 = math.sqrt(var) * ((1 - g) * _N.inv_cdf(1 - 1 / n_trials) + g * _N.inv_cdf(1 - 1 / (n_trials * math.e))) \
        if n_trials > 1 else 0.0
    sr, sk, ku, n = st["sr"], st["skew"], st["kurt"], st["n"]
    den = math.sqrt(max(1 - sk * sr + (ku - 1) / 4 * sr ** 2, 1e-12))
    return float(_N.cdf((sr - sr0) * math.sqrt(n - 1) / den))


def factor_alpha(series: pd.Series, factors: pd.DataFrame) -> dict:
    j = pd.concat([series.rename("y"), factors], axis=1, sort=True).dropna()
    if len(j) < 24:
        return {}
    X = np.column_stack([np.ones(len(j)), j[factors.columns].to_numpy()])
    b, *_ = np.linalg.lstsq(X, j["y"].to_numpy(), rcond=None)
    e = j["y"].to_numpy() - X @ b
    # Newey-West (3 lags) standard error of the intercept
    n, k = X.shape
    xtx = np.linalg.inv(X.T @ X)
    S = (X * e[:, None]).T @ (X * e[:, None])
    for L in range(1, 4):
        w = 1 - L / 4
        G = (X[L:] * e[L:, None]).T @ (X[:-L] * e[:-L, None])
        S += w * (G + G.T)
    se = math.sqrt((xtx @ S @ xtx)[0, 0])
    return {"alpha_ann": float(b[0] * 12), "alpha_t": float(b[0] / se) if se > 0 else None,
            "betas": {c: float(v) for c, v in zip(factors.columns, b[1:])}}


def run(df: pd.DataFrame, factors: pd.DataFrame, mkt: pd.Series) -> dict:
    assert df["month"].max() >= pd.Timestamp(HOLDOUT_START)  # holdout exists in the file...
    d = df[df["month"] <= END]  # ...and is cut before anything is computed
    res = {}
    for tid, (fam, desc, fn) in TRIALS.items():
        res[tid] = {"family": fam, "desc": desc, **xsection.evaluate(d, fn, tid, start=START, end=END)}
    srs = [sharpe_stats(r["series"]["large"]["q5_net"])["sr"] for r in res.values() if "large" in r["series"]]
    for tid, r in res.items():
        s = r["series"].get("large")
        if s is None:
            r["verdict"] = "inconclusive"
            continue
        s = s.set_index(pd.DatetimeIndex(s["month"]) + pd.offsets.MonthEnd(1))  # return month
        st = sharpe_stats(s["q5_net"])
        r["dsr"] = deflated_sharpe(st, srs)
        r["sr_monthly"] = st["sr"]
        net3 = s["q5_minus_univ"] - 3 * 2 * xsection.COST_PER_TURNOVER * s["q5_turnover"]
        r["net_cost_x3_ann"] = float(net3.mean() * 12)
        thirds = xsection._thirds(s.index.to_series())
        r["subperiod_net_positive"] = [bool(s.loc[a:b, "q5_net"].mean() > 0) for a, b in thirds]
        r["alpha_ls"] = factor_alpha(s["d10_d1"], factors)
        r["alpha_q5"] = factor_alpha(s["q5_net"], factors)
        up = mkt.reindex(s.index) > 0
        r["ic_up_mkt"], r["ic_down_mkt"] = float(s.loc[up, "ic"].mean()), float(s.loc[~up, "ic"].mean())
        b = r["bands"]["large"]
        passes = {"ic_t_ge_2": (b["ic_t_nw"] or 0) >= 2, "dsr_ge_0.9": r["dsr"] >= 0.9,
                  "q5_net_pos_2_of_3": sum(r["subperiod_net_positive"]) >= 2, "survives_cost_x3": r["net_cost_x3_ann"] > 0}
        r["checks"] = passes
        r["verdict"] = "pass" if all(passes.values()) else (
            "fail" if b["mean_ic"] <= 0 or (b["ic_t_nw"] or 0) < 1 else "inconclusive")
    return res


def by_group_ic(df: pd.DataFrame, tid: str) -> dict:
    fn = TRIALS[tid][2]
    d = xsection.investable(df[(df["month"] >= START) & (df["month"] <= END) & (df["band"] == "large")]).copy()
    d["score"] = np.nan
    for _, g in d.groupby("month"):
        d.loc[g.index, "score"] = fn(g)
    out = {}
    for grp, x in d.dropna(subset=["score"]).groupby("group"):
        ics = [g["score"].rank().corr(g["ret_next"].rank()) for _, g in x.groupby("month") if len(g) >= 10]
        if len(ics) >= 24:
            out[grp] = (float(np.nanmean(ics)), len(ics))
    return out


def report(res: dict, groups: dict, out: Path) -> None:
    L = ["# Stage 2: pre-registered signal tests (large caps)", "",
         f"Decisions {START[:7]} to {END[:7]}, monthly, US companies with a point-in-time market cap over $10bn. "
         "Pre-registration: `research/prereg/stage2.md`. Holdout 2023-01 to 2026-09 not read. "
         f"Trials counted: {len(res)}.", "",
         "> **Survivor bias:** free prices exclude companies that later disappeared (Stage 1 report). Results are "
         "likely flattered for signals that avoid failing companies (quality, low issuance) and understated for "
         "signals that buy them (deep value).", "",
         "| Trial | Signal | Months | Names | Mean IC | IC t (NW) | Top-quintile vs universe, net, a yr | Net at 3x costs | "
         "Net > 0 by third | DSR | FF5+Mom alpha of top quintile (t) | Verdict |",
         "|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---|"]
    for tid, r in res.items():
        b = r["bands"].get("large", {})
        if not b.get("months"):
            L.append(f"| {tid} | {r['desc']} | 0 | | | | | | | | | inconclusive |")
            continue
        a = r.get("alpha_q5") or {}
        L.append(f"| {tid} | {r['desc']} | {b['months']} | {b['avg_names']:.0f} | {b['mean_ic']:.3f} | "
                 f"{b['ic_t_nw']:.2f} | {b['q5_minus_univ_ann_net']:+.1%} | {r['net_cost_x3_ann']:+.1%} | "
                 f"{''.join('+' if x else '-' for x in r['subperiod_net_positive'])} | {r['dsr']:.2f} | "
                 f"{a.get('alpha_ann', float('nan')):+.1%} ({a.get('alpha_t') or float('nan'):.2f}) | **{r['verdict']}** |")
    L += ["", "Not run: " + "; ".join(f"{k} ({v})" for k, v in NOT_RUN.items()) + ".", "",
          "## Other size bands (information only; pass rules apply to large caps)", "",
          "| Trial | Mid: mean IC (t) | Mid: top quintile net | Small: mean IC (t) | Small: top quintile net |",
          "|---|---:|---:|---:|---:|"]
    for tid, r in res.items():
        cells = []
        for band in ("mid", "small"):
            b = r["bands"].get(band, {})
            cells += [f"{b['mean_ic']:.3f} ({b['ic_t_nw']:.2f})", f"{b['q5_minus_univ_ann_net']:+.1%}"] if b.get("months") \
                else ["", ""]
        L.append(f"| {tid} | " + " | ".join(cells) + " |")
    L += ["", "## Regime and sub-period (large caps)", "", "| Trial | IC, market up months | IC, market down months | "
          "IC by third |", "|---|---:|---:|---|"]
    for tid, r in res.items():
        if "ic_up_mkt" in r:
            sp = ", ".join(f"{k}: {v:.3f}" for k, v in r["bands"]["large"]["sub_periods_ic"].items())
            L.append(f"| {tid} | {r['ic_up_mkt']:.3f} | {r['ic_down_mkt']:.3f} | {sp} |")
    L += ["", "## By sector group (large caps, mean IC, months with 10+ names)", ""]
    for tid, g in groups.items():
        L.append(f"- **{tid}:** " + ", ".join(f"{k} {v[0]:+.3f} ({v[1]})" for k, v in sorted(g.items())))
    L += ["", "## Pass rules (from STRATEGY_V2 2.2, frozen)", "",
          "Pass needs all four: IC t >= 2; deflated Sharpe >= 0.9 across all trials; top quintile beats the universe "
          "after costs in at least 2 of 3 sub-periods; still positive at 3x costs. Fail: mean IC <= 0 or IC t < 1. "
          "Otherwise inconclusive. A pass is evidence tier E3 for that signal in large caps only; signals are not "
          "combined until each passes alone.", ""]
    out.write_text("\n".join(L))
    print("\n".join(L))


def main(out: Path) -> None:
    df = xsection.load()
    comp = pd.read_csv(xsection.DATA / "sec_companies.csv.gz", dtype={"cik": int, "sic": str})
    df = prepare(df, comp)
    ff3 = data_sources.french("F-F_Research_Data_Factors")
    df["s6c_resid_mom"] = residual_momentum(df, ff3)
    trades = pd.read_csv(xsection.DATA / "insider_trades.csv.gz")
    df = df.join(insider_features(df, trades))
    f5 = data_sources.french("F-F_Research_Data_5_Factors_2x3")
    mom = data_sources.french("F-F_Momentum_Factor")
    factors = pd.concat([f5.drop(columns=["RF"]), mom], axis=1, sort=True)
    factors.columns = [c.strip() for c in factors.columns]
    res = run(df, factors, f5["Mkt-RF"] + f5["RF"])
    groups = {tid: by_group_ic(df, tid) for tid in res}
    report(res, groups, out)
    slim = {k: {kk: vv for kk, vv in v.items() if kk != "series"} for k, v in res.items()}
    out.with_suffix(".json").write_text(json.dumps(slim, indent=1, default=str))


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("stage2.md"))

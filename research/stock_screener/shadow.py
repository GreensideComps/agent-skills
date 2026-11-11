"""Screener challengers, tracked forward only (fresh data, no backtest, no N increase).
Champion = pick-1 (live demo stock_screen). Challengers are frozen definitions; each month-end run:
  python shadow.py YYYY-MM     (YYYY-MM = latest complete data month)
It (1) scores last month's baskets with this month's prices into LEDGER.csv and (2) on the first run and every
December data month writes new baskets. Promotion rule (fixed 4 Nov 2026): at a January rebalance, a challenger
replaces the champion only after >= 24 scored months AND mean excess vs champion > 2%/yr with t >= 2.
New challengers may be added any time (append to VARIANTS with a date); never edit or remove an existing one."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pick1 as p1

OUT = Path("/mnt/project-files/research/stock-screener/shadow")
VARIANTS = {  # name: (added, description, picker)
    "champion_pick1": ("2026-11-04", "pick-1 as live", lambda m: p1.pick(p1.universe(m))),
    "c1_large_only": ("2026-11-04", "pick-1 on $10bn+ only (best Q199 robustness view)",
                      lambda m: p1.pick(p1.universe(m, 10e9))),
    "c2_top30": ("2026-11-04", "pick-1 top 30, max 4 per SIC2 (more diversified)", None),
    "c3_no_momentum": ("2026-11-04", "quality + value only, no 12-1m momentum", None),
    "c4_no_value": ("2026-11-06", "quality + momentum only, no FCF/EV value leg", None),
    "c5_no_quality": ("2026-11-06", "value + momentum only, no gross-profitability leg", None),
    "c6_low_vol": ("2026-11-06", "pick-1 after dropping the most volatile third (12m monthly-return std)", None),
    "c7_monthly": ("2026-11-06", "pick-1 rebuilt every month (fast refresh; tests the cost of the yearly/12-tranche cadence)",
                   lambda m: p1.pick(p1.universe(m))),
    "c8_profit_half": ("2026-11-09", "profitability weighted 1/2, value 1/4, momentum 1/4 (Q230: best leg since 2007)", None),
    "c9_beta_cap": ("2026-11-09", "pick-1 ranking, but a name is added only if basket mean 36m beta (vs cap-weighted universe) stays <= 1.0 (S5: beta 1.18, no alpha)", None),
    "c10_value_hml": ("2026-11-09", "value leg = mean z of earnings yield and book-to-market instead of FCF/EV (S5: FCF/EV did not load on HML)", None),
}
MONTHLY = {"c7_monthly"}  # variants re-formed every month instead of each December


def _c2(m):
    old = p1.TOP, p1.PER_SIC
    p1.TOP, p1.PER_SIC = 30, 4
    try:
        return p1.pick(p1.universe(m))
    finally:
        p1.TOP, p1.PER_SIC = old


def _legs(m, legs, weights=None):
    s = p1.score(p1.universe(m)).copy()
    s["score"] = s[legs].mean(axis=1) if weights is None else sum(w * s[c] for c, w in zip(legs, weights))
    s = s.sort_values("score", ascending=False)
    out, per = [], {}
    for _, r in s.iterrows():
        if per.get(r["sic2"], 0) >= p1.PER_SIC:
            continue
        per[r["sic2"]] = per.get(r["sic2"], 0) + 1; out.append(r)
        if len(out) == p1.TOP:
            break
    return pd.DataFrame(out)


def _c3(m):
    return _legs(m, ["z_gpa", "z_fcf_ev"])


VARIANTS["c2_top30"] = VARIANTS["c2_top30"][:2] + (_c2,)
VARIANTS["c3_no_momentum"] = VARIANTS["c3_no_momentum"][:2] + (_c3,)
VARIANTS["c4_no_value"] = VARIANTS["c4_no_value"][:2] + (lambda m: _legs(m, ["z_gpa", "z_mom"]),)
_VOL = {}


def _vol12(m_end):
    if m_end not in _VOL:
        df = p1.load().sort_values(["cik", "month"])
        df = df[df["month"] <= m_end]
        r = df.groupby("cik")["adjclose"].pct_change()
        df = df.assign(r=r)
        last = df.groupby("cik").tail(12)
        _VOL[m_end] = last.groupby("cik")["r"].agg(lambda x: x.std() if x.count() >= 10 else float("nan"))
    return _VOL[m_end]


def _c6(m):
    u = p1.universe(m)
    v = _vol12(u["month"].iloc[0]).reindex(u["cik"]).values
    u = u.assign(vol12=v).dropna(subset=["vol12"])
    return p1.pick(u[u["vol12"] <= u["vol12"].quantile(2 / 3)])


VARIANTS["c6_low_vol"] = VARIANTS["c6_low_vol"][:2] + (_c6,)
VARIANTS["c5_no_quality"] = VARIANTS["c5_no_quality"][:2] + (lambda m: _legs(m, ["z_fcf_ev", "z_mom"]),)
_BETA = {}


def _beta36(m_end):
    if m_end not in _BETA:
        df = p1.load().sort_values(["cik", "month"])
        df = df[(df["month"] <= m_end) & (df["month"] > m_end - pd.DateOffset(months=37))]
        df = df.assign(r=df.groupby("cik")["adjclose"].pct_change(), w=df.groupby("cik")["mcap"].shift(1))
        ok = df.dropna(subset=["r", "w"])
        mkt = ok.groupby("month").apply(lambda g: (g["r"] * g["w"]).sum() / g["w"].sum())
        df = df.join(mkt.rename("mkt"), on="month").dropna(subset=["r", "mkt"])

        def b(g):
            return g["r"].cov(g["mkt"]) / g["mkt"].var() if len(g) >= 24 else float("nan")
        _BETA[m_end] = df.groupby("cik").apply(b)
    return _BETA[m_end]


def _c9(m):
    u = p1.universe(m)
    beta = _beta36(u["month"].iloc[0])
    s = p1.score(u).assign(beta=lambda x: beta.reindex(x["cik"]).values).dropna(subset=["beta"])
    out, per, bs = [], {}, []
    for _, r in s.iterrows():
        if per.get(r["sic2"], 0) >= p1.PER_SIC or (bs and (sum(bs) + r["beta"]) / (len(bs) + 1) > 1.0):
            continue
        per[r["sic2"]] = per.get(r["sic2"], 0) + 1; out.append(r); bs.append(r["beta"])
        if len(out) == p1.TOP:
            break
    return pd.DataFrame(out)


def _c10(m):
    s = p1.score(p1.universe(m)).copy()
    s = s.assign(ey=s["ttm_net_income"] / s["mcap"], bm=s["equity"] / s["mcap"]).dropna(subset=["ey", "bm"])
    for c in ["ey", "bm"]:
        s["z_" + c] = ((s[c] - s[c].mean()) / s[c].std()).clip(-3, 3)
    s["z_val"] = s[["z_ey", "z_bm"]].mean(axis=1)
    s["score"] = s[["z_gpa", "z_val", "z_mom"]].mean(axis=1)
    s = s.sort_values("score", ascending=False)
    out, per = [], {}
    for _, r in s.iterrows():
        if per.get(r["sic2"], 0) >= p1.PER_SIC:
            continue
        per[r["sic2"]] = per.get(r["sic2"], 0) + 1; out.append(r)
        if len(out) == p1.TOP:
            break
    return pd.DataFrame(out)


VARIANTS["c9_beta_cap"] = VARIANTS["c9_beta_cap"][:2] + (_c9,)
VARIANTS["c10_value_hml"] = VARIANTS["c10_value_hml"][:2] + (_c10,)
VARIANTS["c8_profit_half"] = VARIANTS["c8_profit_half"][:2] + (
    lambda m: _legs(m, ["z_gpa", "z_fcf_ev", "z_mom"], [0.5, 0.25, 0.25]),)


def main(month: str):
    OUT.mkdir(parents=True, exist_ok=True)
    df = p1.load()
    m_end = pd.Timestamp(month) + pd.offsets.MonthEnd(0)
    prev = m_end - pd.offsets.MonthEnd(1)
    now, before = df[df["month"] == m_end], df[df["month"] == prev]
    px_now = dict(zip(now["cik"], now["adjclose"])); px_prev = dict(zip(before["cik"], before["adjclose"]))
    ledger = OUT / "LEDGER.csv"
    rows = []
    for name in VARIANTS:
        bf = OUT / f"{name}_basket.csv"
        if bf.exists():
            b = pd.read_csv(bf)
            if b["formed"].iloc[0] < month:  # score the month just ended
                r = [(px_now.get(c, px_prev.get(c)) / px_prev[c] - 1) if px_prev.get(c) else 0.0 for c in b["cik"]]
                rows.append({"month": month, "variant": name, "ret_usd": sum(r) / len(r), "n": len(r)})
        if not bf.exists() or m_end.month == 12 or name in MONTHLY:
            b = VARIANTS[name][2](now)[["cik", "ticker", "score"]].copy(); b["formed"] = month
            b.to_csv(bf, index=False)
    if rows:
        old = pd.read_csv(ledger) if ledger.exists() else pd.DataFrame()
        new = pd.concat([old, pd.DataFrame(rows)]).drop_duplicates(["month", "variant"], keep="first")
        new.to_csv(ledger, index=False)
    print(pd.read_csv(ledger).tail(8) if ledger.exists() else "baskets written; first scores next month")


if __name__ == "__main__":
    main(sys.argv[1])

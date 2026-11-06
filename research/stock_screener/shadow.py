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
}


def _c2(m):
    old = p1.TOP, p1.PER_SIC
    p1.TOP, p1.PER_SIC = 30, 4
    try:
        return p1.pick(p1.universe(m))
    finally:
        p1.TOP, p1.PER_SIC = old


def _legs(m, legs):
    s = p1.score(p1.universe(m)).copy()
    s["score"] = s[legs].mean(axis=1)
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
VARIANTS["c5_no_quality"] = VARIANTS["c5_no_quality"][:2] + (lambda m: _legs(m, ["z_fcf_ev", "z_mom"]),)


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
        if not bf.exists() or m_end.month == 12:
            b = VARIANTS[name][2](now)[["cik", "ticker", "score"]].copy(); b["formed"] = month
            b.to_csv(bf, index=False)
    if rows:
        old = pd.read_csv(ledger) if ledger.exists() else pd.DataFrame()
        new = pd.concat([old, pd.DataFrame(rows)]).drop_duplicates(["month", "variant"], keep="first")
        new.to_csv(ledger, index=False)
    print(pd.read_csv(ledger).tail(8) if ledger.exists() else "baskets written; first scores next month")


if __name__ == "__main__":
    main(sys.argv[1])

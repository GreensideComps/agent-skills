"""B5 quality-flag audit (owner question 2026-10-19 07:25Z): which universe rows the registered share-outlier flag
(median over the exploration window) and the point-in-time variant (expanding median) exclude, and how they overlap
with identity rule C. Input level only: share counts, prices, total assets. No score, return or NAV is computed.

Usage: python3 edge_b5_quality_flag_audit.py  ->  equity/reports/research/edge/b5_quality_flag_audit.json
"""
import json

import pandas as pd

import edge_split
import edge_ttm_checks as tc
import stage2
import xsection


def audit() -> dict:
    df = edge_split.cut_exploration(xsection.load())
    df["so_full"] = edge_split.share_outliers(df)
    df["so_pit"] = edge_split.share_outliers_pit(df)
    df["bad_price"] = (df["adjclose"] <= 0) | (df["close_raw"] <= 0)
    comp = pd.read_csv(xsection.DATA / "sec_companies.csv.gz", usecols=["cik", "sic", "name"])
    df = df.merge(comp, on="cik", how="left")
    fin = df["sic"].map(stage2.sic_group) == "finance"
    u = df[(df["band"] == "large") & (df["close_raw"] >= 1) & ~fin & (df["month"] >= "2015-01-31")
           & (df["month"] <= "2022-11-30")]
    ratio = u["mcap"] / u["total_assets"].where(u["total_assets"] > 0)
    rule_c = (ratio > 100) | (u["cik"] == 1635327)
    sets = {"full": u.so_full, "pit": u.so_pit, "both": u.so_full & u.so_pit, "full_only": u.so_full & ~u.so_pit,
            "pit_only": u.so_pit & ~u.so_full, "bad_price": u.bad_price}
    out = {"universe": {"rows": len(u), "companies": int(u.cik.nunique()), "months": int(u.month.nunique())}}
    for k, m in sets.items():
        out[k] = {"rows": int(m.sum()), "companies": int(u.loc[m, "cik"].nunique()),
                  "also_rule_c": int((m & rule_c).sum()),
                  "by_company": {f"{c} {n}": int(v) for (c, n), v in
                                 u[m].groupby(["cik", "name"]).size().sort_values(ascending=False).items()}}
    q_full, q_pit = ~(u.so_full | u.bad_price), ~(u.so_pit | u.bad_price)
    per = u[q_full != q_pit].groupby("month").size()
    out["quality_ok_differs"] = {"rows": int((q_full != q_pit).sum()), "months": len(per), "max_per_month": int(per.max())}
    return out


def main() -> None:
    a = audit()
    (tc.OUT / "b5_quality_flag_audit.json").write_text(json.dumps(a, indent=1))
    print(json.dumps({k: (v if k in ("universe", "quality_ok_differs") else {x: v[x] for x in ("rows", "companies", "also_rule_c")})
                      for k, v in a.items()}, indent=1))


if __name__ == "__main__":
    main()

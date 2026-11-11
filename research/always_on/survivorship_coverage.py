#!/usr/bin/env python3
"""How much of the real company universe the backtest price file leaves out (survivorship), by year.

For each January 2013-2022: companies with trailing revenue of $1bn or more in SEC filings, how many have a price
that month, how many stopped filing within three years (taken over, merged or failed), and how many of those the
price file covers. Data is read through the holdout guard (edge_split.cut_exploration), so nothing after 2022-12 is
seen, and only the presence of a price is used, never a return.

Run:  python3 research/always_on/survivorship_coverage.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def coverage(min_revenue: float = 1e9, df=None) -> list[dict] | None:
    if df is None:
        try:
            import edge_split  # noqa: PLC0415
            import xsection  # noqa: PLC0415
            df = edge_split.cut_exploration(xsection.load())
        except (ImportError, OSError, ValueError):
            return None
    df = df[["cik", "month", "ttm_revenue", "close_raw"]].copy()
    df["ym"] = df["month"].astype(str).str[:7]
    last = df.groupby("cik")["ym"].max()
    rows = []
    for y in range(2013, 2023):
        ym = f"{y}-01"
        big = df[(df["ym"] == ym) & (df["ttm_revenue"] >= min_revenue)].drop_duplicates("cik")
        if big.empty:
            continue
        priced = big["close_raw"].notna()
        r = {"year": y, "companies": len(big), "priced": int(priced.sum()), "share_priced": float(priced.mean()),
             "gone_in_3y": None, "gone_priced": None}
        if y + 3 <= 2022:
            gone = big["cik"].map(last) < f"{y + 3}-01"
            r["gone_in_3y"], r["gone_priced"] = int(gone.sum()), int((gone & priced).sum())
        rows.append(r)
    return rows


def main() -> None:
    cov = coverage()
    if cov is None:
        print("research data not available on this machine")
        return
    print("| January | Companies with $1bn+ revenue in SEC filings | With a price in the backtest file | Share | "
          "Stopped filing within 3 years | Of those, priced |\n|---|---|---|---|---|---|")
    for r in cov:
        g = "n/a" if r["gone_in_3y"] is None else str(r["gone_in_3y"])
        gp = "n/a" if r["gone_priced"] is None else str(r["gone_priced"])
        print(f"| {r['year']} | {r['companies']} | {r['priced']} | {r['share_priced']:.0%} | {g} | {gp} |")


if __name__ == "__main__":
    main()

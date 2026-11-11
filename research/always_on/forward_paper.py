"""Forward paper record for the loop's most robust leads (Q31). Writes each strategy's holdings, formed only
from data dated on or before the decision month, BEFORE the holding month starts. Judged later on months that
had not happened when the list was written. No orders are placed.

Usage: python research/always_on/forward_paper.py DECISION_MONTH (e.g. 2026-09-30) HOLD_FROM (e.g. 2026-11)."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import q32_composite as q32  # noqa: E402

OUT = Path("/mnt/project-files/research/always-on/forward")


def holdings(decision: str) -> dict[str, pd.DataFrame]:
    df = q32.features()
    d = df[(df["month"] == decision) & (df["band"] == "large") & (df["close_raw"] >= q32.q.xs.MIN_PRICE)]
    ebit = d["ttm_operating_income"].where(d["ttm_operating_income"] > 0)
    nd = ((d["debt_total"].fillna(0) - d["cash"].fillna(0)) / ebit).dropna()
    q23b = d.loc[nd[nd <= nd.quantile(0.2)].index]
    return {"Q32a": d[d["c_and"].notna()], "Q23b": q23b, "Q06c": d[d["d_grow"].notna()]}


if __name__ == "__main__":
    decision, hold_from = sys.argv[1], sys.argv[2]
    written = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    lines = []
    for name, h in holdings(decision).items():
        f = OUT / f"{name}_{hold_from}.csv"
        if f.exists():
            raise SystemExit(f"{f} exists: forward lists are write-once")
        h[["cik", "ticker", "close_raw", "mcap"]].sort_values("ticker").to_csv(f, index=False)
        lines.append(f"| {hold_from} | {name} | {len(h)} | {decision} | {written} | {f.name} |")
    with open(OUT / "LEDGER.md", "a") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))

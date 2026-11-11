"""Q86 forward paper record for Q84a sector momentum: write the 3 KF-12 industries with the best 12-1m return
(and matching US sector ETFs) for HOLD_MONTH, write-once. Uses only past returns as the signal; it does NOT
compute or print any 2023+ performance (holdout rule). Usage: forward_sectors.py HOLD_MONTH (YYYY-MM)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import q44_q48_timing as t  # noqa: E402

FWD = Path("/mnt/project-files/research/always-on/forward")
ETF = {"NoDur": "XLP", "Durbl": "XLY", "Manuf": "XLI", "Enrgy": "XLE", "Chems": "XLB", "BusEq": "XLK",
       "Telcm": "XLC", "Utils": "XLU", "Shops": "XLY", "Hlth": "XLV", "Money": "XLF", "Other": "XLI"}


def main(hold: str):
    out = FWD / f"Q84a_{hold}.csv"
    if out.exists():
        sys.exit(f"{out} exists (write-once)")
    t.END = "2100-12"  # latest data for the SIGNAL only; no returns are evaluated here
    ind = t.section("12_Industry_Portfolios.csv")
    last = ind.index[-1]
    mom = (1 + ind.loc[last - 11:last - 1]).prod() - 1  # 12-1m window ending at the latest month
    pick = mom.sort_values(ascending=False).index[:3]
    pd.DataFrame({"industry": pick, "us_etf_proxy": [ETF[p] for p in pick], "weight": 1 / 3}).to_csv(out, index=False)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    with open(FWD / "LEDGER.md", "a") as f:
        f.write(f"| {hold} | Q84a | 3 | {last} | {now} | {out.name} |\n")
    print(out, list(pick), "signal month", last)


if __name__ == "__main__":
    main(sys.argv[1])

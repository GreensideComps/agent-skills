"""Q206 buyback_value live picks (forward test only, no evaluation). Usage: python q206_live.py YYYY-MM
Writes /mnt/project-files/research/always-on/forward/Q206_picks_YYYY-MM.csv: symbol,sic,rank,fcf_ev,buyback_yield,nd_ebitda.
Same gates as prereg/Q206.md, PIT via monthly_metrics last_filed, ranked by FCF/EV (best first)."""
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stock_screener"))
import pick1
mon = pd.Timestamp(sys.argv[1]) + pd.offsets.MonthEnd(0)
df = pick1.load()
df["bby"] = df["ttm_buybacks"].abs() / df["mcap"]
m = df[df["month"] == mon]
u = pick1.universe(m).dropna(subset=["fcf_ev", "bby"])
sel = u[(u["bby"] >= u["bby"].quantile(0.9)) & (u["sh_chg"] < 0) & (u["fcf"] > 0) & (u["nd_ebitda"] < 3)
        & (u["fcf_ev"] >= u["fcf_ev"].quantile(0.7))].sort_values("fcf_ev", ascending=False)
out = pd.DataFrame({"symbol": sel["ticker"].str.replace(".", "-", regex=False).values, "sic": sel["sic"].fillna(0).astype(int).values,
                    "rank": range(1, len(sel) + 1), "fcf_ev": sel["fcf_ev"].round(4).values,
                    "buyback_yield": sel["bby"].round(4).values, "nd_ebitda": sel["nd_ebitda"].round(2).values})
p = Path(f"/mnt/project-files/research/always-on/forward/Q206_picks_{mon:%Y-%m}.csv")
out.to_csv(p, index=False); print(len(u), "in universe;", len(out), "picks ->", p); print(out.head(15).to_string(index=False))

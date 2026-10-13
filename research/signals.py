"""Phase 4: generate current signals and write a paper-trading ledger.

Places NO orders. Reference prices are the latest Yahoo Finance LSE closes and
are labelled as such; Trading 212's API has no quote endpoint, so execution
prices can only be compared after an approved execution test (via
/api/v0/equity/history/orders fill prices).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from data_sources import DATA, yahoo, yahoo_currency
from dataset import build, gbpusd_daily
from strategies import gem, trend_sma

OUT = DATA.parent / "output"
CAPITAL = 100.0
FX_FEE = 0.0015

# Trading 212 ticker -> Yahoo symbol used for reference prices
T212 = {
    "VWRPl_EQ": "VWRP.L", "IWMOl_EQ": "IWMO.L", "VUAGl_EQ": "VUAG.L",
    "VXUSl_EQ": "VXUS.L", "VAGSl_EQ": "VAGS.L",
}
ROLE = {"US": "VUAGl_EQ", "INTL": "VXUSl_EQ", "BOND": "VAGSl_EQ", "WORLD": "VWRPl_EQ", "CASH": None}


def ref_price(t212: str):
    sym = T212[t212]
    df = yahoo(sym, refresh=True)
    px = float(df["close"].iloc[-1])
    cur = yahoo_currency(sym)
    if cur == "GBp":
        px, cur = px / 100, "GBP"
    return px, cur, df.index[-1].date().isoformat()


R = build()
asof = R.index[-1]
hist = R  # all data through the as-of month-end
gbpusd = float(gbpusd_daily().iloc[-1])


def trailing(col, L=12):
    return float((1 + R[col].iloc[-L:]).prod() - 1)


tr = {k: trailing(k) for k in ("US", "INTL", "BOND", "CASH", "WORLD")}
gem_w = gem(12, "US", "INTL", "BOND")(hist)
sma_w = trend_sma(10, "WORLD", "BOND")(hist)
idx = (1 + R["WORLD"]).cumprod()
sma_gap = float(idx.iloc[-1] / idx.iloc[-10:].mean() - 1)

portfolios = {
    "A_benchmark": ({"VWRPl_EQ": 1.0}, "Passive benchmark: 100% FTSE All-World."),
    "B_momentum_tilt": ({"VWRPl_EQ": 0.5, "IWMOl_EQ": 0.5},
                        "Static 50/50 All-World + MSCI World Momentum; rebalance annually or at >10pp drift."),
    "C_gem12": ({ROLE[k]: v for k, v in gem_w.items()},
                f"GEM L=12: US 12m {tr['US']:+.1%} vs ex-US {tr['INTL']:+.1%} vs cash {tr['CASH']:+.1%} -> "
                f"{'/'.join(gem_w)}"),
}

now = datetime.now(timezone.utc).isoformat(timespec="seconds")
rows = []
for pname, (w, why) in portfolios.items():
    for tk, wt in w.items():
        px, cur, pdate = ref_price(tk)
        gbp = CAPITAL * wt
        fx = FX_FEE if cur != "GBP" else 0.0
        px_gbp = px / gbpusd if cur == "USD" else px
        qty = np.floor(gbp * (1 - fx) / px_gbp * 1e4) / 1e4  # fractional, 4dp, rounded down
        rows.append({"generated_utc": now, "portfolio": pname, "signal_asof": asof.date().isoformat(),
                     "action": "BUY (intended, NOT placed)", "t212_ticker": tk, "target_weight": wt,
                     "target_gbp": round(gbp, 2), "ref_price": round(px, 4), "ref_ccy": cur, "ref_price_date": pdate,
                     "ref_source": f"Yahoo {T212[tk]} close", "est_qty": qty, "est_fx_fee_gbp": round(gbp * fx, 3),
                     "reason": why, "status": "PAPER"})
L = pd.DataFrame(rows)
path = OUT / "paper_ledger.csv"
L.to_csv(path, mode="a", header=not path.exists(), index=False)

state = {"generated_utc": now, "signal_asof": asof.date().isoformat(), "trailing_12m": tr,
         "gem_weights": gem_w, "sma10_weights": sma_w, "world_vs_sma10": sma_gap, "gbpusd": gbpusd}
(OUT / "signals_latest.json").write_text(json.dumps(state, indent=1, default=float))
pd.set_option("display.width", 220)
print(json.dumps(state, indent=1, default=float))
print(L[["portfolio", "t212_ticker", "target_gbp", "ref_price", "ref_ccy", "ref_price_date", "est_qty", "est_fx_fee_gbp"]].to_string(index=False))

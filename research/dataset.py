"""Builds cleaned monthly GBP total-return series used by every backtest.

Conventions
-----------
* All returns are simple monthly total returns in GBP for a UK investor holding
  the asset unhedged (except BOND, which is explicitly GBP-hedged).
* Month-end = last available trading-day price in that calendar month.
* Where a UCITS ETF tradeable on Trading 212 exists, its actual LSE price
  history is spliced in from SPLICE_FROM onwards; earlier history uses the
  documented proxy. Proxy history before the splice is the 'research' history.
* Mutual-fund proxies (VFINX, VGTSX, VEIEX, VFITX) are already net of fund fees.
  Ken French index-level returns are gross, so a fee haircut is subtracted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data_sources import DATA, french, fred, yahoo, yahoo_currency

SPLICE_FROM = "2012-06-30"  # first full month of VWRL.L / VUSA.L history
LAST_COMPLETE_MONTH = "2026-09-30"  # data pulled 2026-10-13; October is partial


def clean_prices(s: pd.Series, settle_days: int = 5, jump: float = 0.10) -> pd.Series:
    """Remove Yahoo LSE glitches: one-day jumps that fully reverse (unit or
    currency mix-ups) and the first few noisy days after listing."""
    s = s.dropna().copy()
    s = s.iloc[settle_days:]
    for _ in range(3):
        r = s.pct_change()
        nxt = r.shift(-1)
        bad = (r.abs() > jump) & (((1 + r) * (1 + nxt) - 1).abs() < 0.03)
        # also multi-day episodes: price far from both a 5-day backward and forward median
        med_b = s.rolling(5, min_periods=3).median().shift(1)
        med_f = s[::-1].rolling(5, min_periods=3).median().shift(1)[::-1]
        far = ((s / med_b - 1).abs() > 0.2) & ((s / med_f - 1).abs() > 0.2)
        bad = bad | far
        if not bad.any():
            break
        s[bad] = np.nan
        s = s.ffill()
    return s


def gbpusd_daily() -> pd.Series:
    """USD per 1 GBP. FRED DEXUSUK, extended with Yahoo GBPUSD=X."""
    f = fred("DEXUSUK")
    y = yahoo("GBPUSD=X")["close"]
    s = f.combine_first(y[y.index > f.index[-1]])
    return s.sort_index()


def _tr_daily_gbp(symbol: str) -> pd.Series:
    df = yahoo(symbol)
    px = clean_prices(df["adjclose"])
    cur = yahoo_currency(symbol)
    if cur == "GBp":
        px = px / 100
    elif cur == "USD":
        fx = gbpusd_daily().reindex(px.index).ffill()
        px = px / fx
    elif cur != "GBP":
        raise ValueError(f"unsupported currency {cur} for {symbol}")
    return px.dropna()


def monthly_from_daily(px: pd.Series) -> pd.Series:
    m = px.resample("ME").last()
    return m.pct_change().dropna()


def uk_cash_monthly() -> pd.Series:
    """UK cash: 3m interbank/12, then ERNS.L (iShares GBP Ultrashort Bond) from Nov 2013.

    XSTR.L was rejected: Yahoo's history omits its distributions (flat price)."""
    ib = fred("IR3TIB01GBM156N") / 100 / 12
    ib.index = ib.index + pd.offsets.MonthEnd(0)
    erns = monthly_from_daily(_tr_daily_gbp("ERNS.L"))
    erns = erns[erns.index >= "2013-11-30"]
    return erns.combine_first(ib[ib.index < "2013-11-30"]).rename("CASH")


def usd_to_gbp_monthly(r_usd: pd.Series) -> pd.Series:
    fx = gbpusd_daily().resample("ME").last()
    fx_ret = fx.pct_change()  # USD per GBP up => USD assets lose in GBP
    out = (1 + r_usd) / (1 + fx_ret.reindex(r_usd.index)) - 1
    return out.dropna()


def build(splice: bool = True) -> pd.DataFrame:
    cash = uk_cash_monthly()
    kf_dev = french("Developed_3_Factors")
    kf_exus = french("Developed_ex_US_3_Factors")
    kf_us = french("F-F_Research_Data_Factors")
    us_rf = kf_us["RF"]

    def proxy_kf(df, fee=0.002):
        return df["Mkt-RF"] + df["RF"] - fee / 12

    world = usd_to_gbp_monthly(proxy_kf(kf_dev, 0.002))
    us = monthly_from_daily(_tr_daily_gbp("VFINX"))
    intl = monthly_from_daily(_tr_daily_gbp("VGTSX"))
    intl = intl.combine_first(usd_to_gbp_monthly(proxy_kf(kf_exus, 0.003)))
    em = monthly_from_daily(_tr_daily_gbp("VEIEX"))

    # GBP-hedged intermediate government bonds: USD return - US cash + UK cash
    vfitx_usd = monthly_from_daily(clean_prices(yahoo("VFITX")["adjclose"]))
    vbmfx_usd = monthly_from_daily(clean_prices(yahoo("VBMFX")["adjclose"]))
    b_usd = vfitx_usd.combine_first(vbmfx_usd)
    bond = (b_usd - us_rf.reindex(b_usd.index) + cash.reindex(b_usd.index)).dropna()

    gold = monthly_from_daily(_tr_daily_gbp("GC=F"))
    gold = gold[gold.index >= "2000-09-30"]

    cols = {"WORLD": world, "US": us, "INTL": intl, "EM": em, "BOND": bond, "GOLD": gold, "CASH": cash}
    if splice:
        ucits = {
            "WORLD": ("VWRL.L", SPLICE_FROM), "US": ("VUSA.L", SPLICE_FROM),
            "GOLD": ("SGLN.L", SPLICE_FROM), "BOND": ("VAGS.L", "2019-07-31"),
        }
        for k, (sym, start) in ucits.items():
            u = monthly_from_daily(_tr_daily_gbp(sym))
            u = u[u.index >= start]
            cols[k] = u.combine_first(cols[k][cols[k].index < start])
    df = pd.DataFrame(cols).sort_index()
    df = df[df.index <= LAST_COMPLETE_MONTH]
    return df


def factor_etfs() -> pd.DataFrame:
    """Actual GBP-line MSCI World factor ETFs (no FX fee on Trading 212)."""
    m = {"MOM": "IWFM.L", "VALUE": "IWFV.L", "QUALITY": "IWFQ.L", "MINVOL": "MINV.L", "WORLD_ETF": "SWDA.L"}
    return pd.DataFrame({k: monthly_from_daily(_tr_daily_gbp(v)) for k, v in m.items()})


if __name__ == "__main__":
    df = build()
    df.to_csv(DATA / "monthly_gbp_returns.csv")
    print(df.describe().T[["count", "mean", "std"]])
    print(df.apply(lambda c: c.first_valid_index().date()))
    print("last row", df.index[-1].date())

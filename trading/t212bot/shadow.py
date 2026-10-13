"""Shadow (paper) portfolios tracked alongside the real demo account.

They start on the bot's inception date with the same capital and trade at
Yahoo daily closes with a 0.10% one-way cost (plus 0.15% FX fee on USD
lines), so the real account's fills can be compared against simple
alternatives. Everything is recomputed deterministically from prices on each
run, so there is no hidden state to drift.

GEM-12 signal: 12-month GBP total return of US (VUAG.L) vs ex-US (Vanguard
Total International VGTSX converted to GBP, a long-history stand-in for
VXUS.L) vs cash (ERNS.L). The winner is held if it beats cash, else bonds
(VAGS.L). Evaluated at each month-end and traded at the next trading day's
close.
"""
from __future__ import annotations

import json
import subprocess
import urllib.request
from datetime import date

import pandas as pd

COST = 0.001
FX_FEE = 0.0015


def yahoo_daily(symbol: str) -> pd.DataFrame:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           "?range=5y&interval=1d&events=div%7Csplit&includeAdjustedClose=true")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (t212bot)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            js = json.loads(r.read())
    except Exception:
        r = subprocess.run(["curl", "-sSf", "-m", "30", "-A", "Mozilla/5.0", url], capture_output=True, check=True)
        js = json.loads(r.stdout)
    res = js["chart"]["result"][0]
    idx = pd.to_datetime(res["timestamp"], unit="s").normalize()
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose", q["close"])
    df = pd.DataFrame({"close": q["close"], "adjclose": adj}, index=idx)
    df = df[~df.index.duplicated(keep="last")].dropna()
    cur = res["meta"]["currency"]
    if cur == "GBp":
        df = df / 100
        cur = "GBP"
    df.attrs["currency"] = cur
    return df


class PriceBook:
    def __init__(self, loader=yahoo_daily):
        self._load, self._cache = loader, {}

    def get(self, sym: str) -> pd.DataFrame:
        if sym not in self._cache:
            self._cache[sym] = self._load(sym)
        return self._cache[sym]

    def gbp_tr(self, sym: str) -> pd.Series:
        df = self.get(sym)
        s = df["adjclose"]
        if df.attrs.get("currency", "GBP") == "USD":
            fx = self.get("GBPUSD=X")["close"].reindex(s.index).ffill()
            s = s / fx
        return s.dropna()


def static_nav(book: PriceBook, targets: dict[str, str], weights: dict[str, float], start: date, capital: float) -> pd.Series:
    navs = []
    for t, w in weights.items():
        sym = targets[t]
        px = book.gbp_tr(sym)
        px = px[px.index >= pd.Timestamp(start)]
        fee = COST + (FX_FEE if book.get(sym).attrs.get("currency") == "USD" else 0)
        units = capital * w * (1 - fee) / px.iloc[0]
        navs.append(units * px)
    return pd.concat(navs, axis=1).ffill().sum(axis=1).rename("nav")


def gem_signal(book: PriceBook, asof: pd.Timestamp) -> str:
    def r12(s: pd.Series) -> float:
        m = s[s.index <= asof].resample("ME").last()
        if len(m) < 13:
            return float("nan")
        return float(m.iloc[-1] / m.iloc[-13] - 1)
    us, intl, cash = r12(book.gbp_tr("VUAG.L")), r12(book.gbp_tr("VGTSX")), r12(book.gbp_tr("ERNS.L"))
    best, rb = ("US", us) if us >= intl else ("INTL", intl)
    return best if rb > cash else "BOND"


def gem_nav(book: PriceBook, roles: dict[str, str], start: date, capital: float) -> tuple[pd.Series, list[dict]]:
    """roles: {'US': sym, 'INTL': sym, 'BOND': sym} (Yahoo symbols of tradeable lines)."""
    days = book.gbp_tr(roles["US"])
    days = days[days.index >= pd.Timestamp(start)].index
    nav, log = [], []
    holding, units, value = None, 0.0, capital
    for i, d in enumerate(days):
        new_month = i == 0 or d.month != days[i - 1].month
        if new_month:
            asof = (d - pd.offsets.MonthEnd(1)) if i > 0 else (pd.Timestamp(d) - pd.offsets.MonthEnd(1))
            sig = gem_signal(book, asof)
            if sig != holding:
                if holding is not None:
                    px_old = book.gbp_tr(roles[holding]).asof(d)
                    value = units * px_old * (1 - COST)
                px_new = book.gbp_tr(roles[sig]).asof(d)
                units = value * (1 - COST) / px_new
                log.append({"date": d.date().isoformat(), "signal_asof": asof.date().isoformat(), "hold": sig})
                holding = sig
        px = book.gbp_tr(roles[holding]).asof(d)
        nav.append((d, units * px))
    return pd.Series(dict(nav), name="nav"), log

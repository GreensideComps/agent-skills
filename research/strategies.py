"""Strategy weight functions. Each takes the return history through month t and
returns target weights for month t+1 (long-only, sum <= 1, rest in CASH)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def trailing(hist: pd.DataFrame, col: str, L: int) -> float:
    x = hist[col].iloc[-L:]
    if len(x) < L or x.isna().any():
        return np.nan
    return float((1 + x).prod() - 1)


def bench(asset="WORLD"):
    return lambda h: {asset: 1.0}


def static(weights: dict):
    return lambda h: dict(weights)


def trend_abs(L=12, risk="WORLD", safe="CASH"):
    """Time-series momentum: hold risk asset if its L-month return beats cash."""
    def f(h):
        r, c = trailing(h, risk, L), trailing(h, "CASH", L)
        if np.isnan(r) or np.isnan(c):
            return None
        return {risk: 1.0} if r > c else {safe: 1.0}
    return f


def trend_sma(L=10, risk="WORLD", safe="CASH"):
    """Price above its L-month moving average (Faber 2007), on total-return index."""
    def f(h):
        x = h[risk].dropna()
        if len(x) < L:
            return None
        idx = (1 + x).cumprod()
        return {risk: 1.0} if idx.iloc[-1] > idx.iloc[-L:].mean() else {safe: 1.0}
    return f


def gem(L=12, a="US", b="INTL", safe="BOND"):
    """Antonacci dual momentum: relative (a vs b) + absolute (vs cash)."""
    def f(h):
        ra, rb, c = trailing(h, a, L), trailing(h, b, L), trailing(h, "CASH", L)
        if np.isnan([ra, rb, c]).any():
            return None
        best, rbest = (a, ra) if ra >= rb else (b, rb)
        return {best: 1.0} if rbest > c else {safe: 1.0}
    return f


def rotation(K=2, L=6, universe=("US", "INTL", "EM", "BOND", "GOLD"), abs_filter=True):
    """Cross-asset relative momentum: top-K by L-month return, equal weight;
    slots whose asset fails the cash filter go to CASH."""
    def f(h):
        c = trailing(h, "CASH", L)
        scores = {a: trailing(h, a, L) for a in universe if a in h}
        scores = {a: s for a, s in scores.items() if not np.isnan(s)}
        if len(scores) < K or np.isnan(c):
            return None
        top = sorted(scores, key=scores.get, reverse=True)[:K]
        w = {}
        for a in top:
            tgt = a if (not abs_filter or scores[a] > c) else "CASH"
            w[tgt] = w.get(tgt, 0) + 1.0 / K
        return w
    return f


def inverse_vol(assets=("WORLD", "BOND", "GOLD"), L=12):
    def f(h):
        vols = {}
        for a in assets:
            x = h[a].iloc[-L:] if a in h else pd.Series(dtype=float)
            if len(x) == L and not x.isna().any():
                vols[a] = x.std()
        if not vols:
            return None
        inv = {a: 1 / v for a, v in vols.items()}
        s = sum(inv.values())
        return {a: v / s for a, v in inv.items()}
    return f


def vol_target(target=0.12, L=6, risk="WORLD"):
    """Scale exposure to hit a target annual vol (max 100%, no leverage)."""
    def f(h):
        x = h[risk].iloc[-L:]
        if len(x) < L or x.isna().any():
            return None
        v = x.std() * np.sqrt(12)
        w = min(1.0, target / v) if v > 0 else 1.0
        return {risk: w, "CASH": 1 - w}
    return f


def grid():
    """Pre-declared candidate set: (family, name, weight_fn)."""
    G = []
    G.append(("benchmark", "WORLD buy&hold", bench("WORLD")))
    G.append(("benchmark", "60/40 WORLD/BOND", static({"WORLD": 0.6, "BOND": 0.4})))
    for L in (6, 8, 10, 12):
        for safe in ("CASH", "BOND"):
            G.append(("trend_abs", f"TSMOM L={L} safe={safe}", trend_abs(L, "WORLD", safe)))
            G.append(("trend_sma", f"SMA L={L} safe={safe}", trend_sma(L, "WORLD", safe)))
    for L in (6, 9, 12):
        for safe in ("CASH", "BOND"):
            G.append(("gem", f"GEM L={L} safe={safe}", gem(L, "US", "INTL", safe)))
    for K in (1, 2, 3):
        for L in (3, 6, 12):
            G.append(("rotation", f"ROT K={K} L={L}", rotation(K, L)))
    for L in (6, 12):
        G.append(("inverse_vol", f"InvVol WORLD/BOND/GOLD L={L}", inverse_vol(("WORLD", "BOND", "GOLD"), L)))
    for tgt in (0.10, 0.12, 0.15):
        G.append(("vol_target", f"VolTarget {int(tgt*100)}% L=6", vol_target(tgt, 6)))
    return G

"""Decision C9 (owner 30 Oct 11:35Z): two price-only swing strategies on the C6 watchlist, from free Yahoo bars.

vol_squeeze: the 20-day Bollinger bandwidth sits in the lowest 10% of its last 250 days on the previous close, then
a close above the prior 20-day high on at least 1.5x average volume, above the 200-day average. Bought in the next
session unless the price is already more than 3% above the trigger close. Stop at the 20-day low or -8% (the tighter),
a trailing stop at the 10-day low once the trade has been up 10%, and 20 trading days at most.

gap_go: a 3-12% opening gap that, 30-60 minutes after the US open, still holds at least 20% of the gap and trades above
both the open and the first 30 minutes' VWAP. Stop at the first 30 minutes' low, target +6%, flat by the close, at most
two a day. A check the agent was asleep for is logged as missed, never traded late.

Missing or short data means no signal. Nothing here sends an order.
"""
from __future__ import annotations

import time
from typing import Callable

from . import review

SQUEEZE, GAP = "vol_squeeze", "gap_go"


def ohlcv(sym: str, get: Callable, rng: str = "2y", interval: str = "1d") -> dict[str, list]:
    """Yahoo bars, oldest first, rows without a close dropped: {t, o, h, l, c, v}. A missing open/high/low takes the
    close, so it can never widen a range."""
    r = get(review.CHART.format(s=sym), {"range": rng, "interval": interval})["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    ts = r.get("timestamp") or []
    c = q.get("close") or []
    out = {k: [] for k in "tohlcv"}
    for i, ci in enumerate(c):
        if ci is None:
            continue
        pick = lambda k: (q.get(k) or [None] * len(c))[i]  # noqa: E731
        out["t"].append(float(ts[i]) if i < len(ts) else None)
        out["c"].append(float(ci))
        for k, name in (("o", "open"), ("h", "high"), ("l", "low")):
            out[k].append(float(pick(name)) if pick(name) is not None else float(ci))
        out["v"].append(float(pick("volume") or 0))
    return out


def completed(bars: dict, now: float) -> dict:
    """The bars of finished sessions: today's bar is dropped until 21:00 UTC, after the US close."""
    t = bars["t"]
    if t and t[-1] is not None and time.gmtime(t[-1])[:3] == time.gmtime(now)[:3] and time.gmtime(now).tm_hour < 21:
        return {k: v[:-1] for k, v in bars.items()}
    return bars


def _sd(x: list[float]) -> float:
    m = sum(x) / len(x)
    return (sum((a - m) ** 2 for a in x) / len(x)) ** 0.5


def squeeze(bars: dict, sc: dict) -> dict:
    """The vol_squeeze reading on the last completed bar: {signal, why, pct, close, low20, day, ...}."""
    c, h, l, v = bars["c"], bars["h"], bars["l"], bars["v"]
    k = len(c) - 1
    if k < 270:
        return {"signal": False, "why": f"only {k + 1} daily bars"}
    bw = {i: 4 * _sd(c[i - 19:i + 1]) / (sum(c[i - 19:i + 1]) / 20) for i in range(k - 250, k)}
    prev = bw[k - 1]
    pct = sum(1 for i in range(k - 250, k) if bw[i] < prev) / 250
    hi20 = max(h[k - 20:k])
    avg_v = sum(v[k - 20:k]) / 20
    ma200 = sum(c[k - 199:k + 1]) / 200
    dollar = sum(c[i] * v[i] for i in range(k - 19, k + 1)) / 20
    out = {"day": bars["t"][k] and time.strftime("%Y-%m-%d", time.gmtime(bars["t"][k])), "close": c[k],
           "pct": round(pct, 3), "hi20": hi20, "vol_x": round(v[k] / avg_v, 2) if avg_v else None,
           "ma200": round(ma200, 2), "low20": min(l[k - 19:k + 1]), "dollar_vol": round(dollar)}
    why = ("price under $10" if c[k] <= sc["min_price"] else
           "20-day dollar volume under the floor" if dollar < sc["min_dollar_volume"] else
           f"bandwidth percentile {pct:.0%} > {sc['squeeze_pct']:.0%}" if pct > sc["squeeze_pct"] else
           "no close above the 20-day high" if c[k] <= hi20 else
           f"volume {out['vol_x']}x < {sc['volume_x']}x" if not avg_v or v[k] < sc["volume_x"] * avg_v else
           "below the 200-day average" if c[k] <= ma200 else None)
    return {**out, "signal": why is None, "why": why or "squeeze breakout"}


def squeeze_trailing(bars: dict, entry_t: float, entry_px: float, price: float, sc: dict) -> bool:
    """True once the trade has been up `trail_after` and the price is below the low of the last 10 finished days."""
    peak = max([h for t, h in zip(bars["t"], bars["h"]) if t is not None and t >= entry_t - 86400] + [price])
    return peak >= entry_px * (1 + sc["trail_after"]) and price < min(bars["l"][-sc["trail_days"]:])


def gap_check(bars: dict, prev_close: float, open_t: float, now: float, gc: dict) -> dict:
    """gap_go at its check time, from today's 1-minute bars: {signal, why, gap, held, open, vwap30, low30, price}."""
    if not (open_t + gc["check_from_s"] <= now <= open_t + gc["check_to_s"]):
        return {"signal": False, "why": "outside the check window"}
    rows = [i for i, t in enumerate(bars["t"]) if t is not None and t >= open_t - 60]
    first = [i for i in rows if bars["t"][i] < open_t + 1800]
    if not first or not prev_close:
        return {"signal": False, "why": "no intraday bars"}
    o = bars["o"][first[0]]
    price = bars["c"][rows[-1]]
    vol = sum(bars["v"][i] for i in first)
    vwap = (sum((bars["h"][i] + bars["l"][i] + bars["c"][i]) / 3 * bars["v"][i] for i in first) / vol if vol
            else (max(bars["h"][i] for i in first) + min(bars["l"][i] for i in first)) / 2)
    low30 = min(bars["l"][i] for i in first)
    gap = o / prev_close - 1
    held = (price - prev_close) / (o - prev_close) if o > prev_close else 0.0
    out = {"gap": round(gap, 4), "held": round(held, 3), "open": o, "vwap30": round(vwap, 4), "low30": low30,
           "price": price, "prev_close": prev_close}
    why = (f"gap {gap:+.1%} outside {gc['min_gap']:.0%}-{gc['max_gap']:.0%}" if not gc["min_gap"] <= gap <= gc["max_gap"]
           else f"only {held:.0%} of the gap held" if held < gc["min_held"]
           else "not above the open" if price <= o
           else "not above the first-30-minute VWAP" if price <= vwap
           else "stop at or above the price" if low30 >= price else None)
    return {**out, "signal": why is None, "why": why or "gap held"}

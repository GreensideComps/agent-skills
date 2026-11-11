"""Live slippage vs the price each backtest assumes (research Q224, 7 Nov 2026). For every filled strategy order, the
reference is the open or the close of the fill's New York session (ref_kind per strategy in config), read from
Yahoo daily bars once that session's bar is final. Rows go to state/slippage.json keyed by intent id; the order
journal itself is never edited. cost = fill vs reference, signed so that a positive number is a cost (paid more on a
buy, got less on a sell)."""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from .gap_rebound import CHART, NY


def day_bars(sym: str, get: Callable, rng: str = "1mo") -> dict[str, tuple[float, float]]:
    """{NY date: (open, close)} from Yahoo, days with both prices only."""
    r = get(CHART.format(s=sym), {"range": rng, "interval": "1d"})["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = {}
    for t, o, c in zip(r.get("timestamp") or [], q.get("open") or [], q.get("close") or []):
        if o is not None and c is not None:
            out[datetime.fromtimestamp(t, NY).date().isoformat()] = (float(o), float(c))
    return out


def row(rec: dict, kind: str, bars: dict, fill_day: str) -> dict | None:
    fill = (rec.get("broker") or {}).get("fill") or {}
    px, qty = fill.get("price"), fill.get("quantity") or rec.get("quantity")
    if not px or not qty or fill_day not in bars:
        return None
    ref = bars[fill_day][0 if kind == "open" else 1]
    if ref > 20 * px:  # an LSE line quoted in pence on Yahoo
        ref /= 100
    buy = float(qty) > 0
    cost = (px / ref - 1) if buy else (ref / px - 1)
    return {"ticker": rec["ticker"], "strategy": (rec.get("signal") or {}).get("strategy"),
            "type": (rec.get("signal") or {}).get("type"), "side": "buy" if buy else "sell", "fill_px": px,
            "fill_ts": fill.get("filledAt") or rec.get("ts"), "ref_kind": kind, "ref_day": fill_day,
            "ref_px": round(ref, 4), "cost": round(cost, 5)}

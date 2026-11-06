"""Multi-horizon trade review (agent-1.5, owner 30 Oct 08:05Z): each watched name and open trade is scored on
several free signals per horizon instead of one daily move.

short  (days):         trend vs the 20-day average, RSI(14), volume surge in the direction of the day's move,
                       Wikipedia attention z.
medium (weeks-months): 3- and 6-month momentum, distance from the 52-week high, 20-day volatility.
long   (months+):      trend vs the 200-day average, 12-1 month momentum, 50-day vs 200-day average.

Each component is clipped to [-1, 1]; a horizon score is the mean of its available components, and the composite is
0.4 short + 0.35 medium + 0.25 long. None of this is a proven edge: the weights are a stated prior, every score is
logged, and the strategies stay under the kill rule. Missing data scores nothing (UNVERIFIED), never zero-filled.
"""
from __future__ import annotations

import math
import time
from typing import Callable

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{s}"
EARNINGS = "https://api.nasdaq.com/api/calendar/earnings"
WEIGHTS = {"short": 0.40, "medium": 0.35, "long": 0.25}


def clip(x: float) -> float:
    return max(-1.0, min(1.0, x))


def history(sym: str, get: Callable) -> tuple[list[float], list[float]]:
    """About a year of daily closes and volumes from Yahoo, oldest first, with empty days dropped."""
    r = get(CHART.format(s=sym), {"range": "1y", "interval": "1d"})["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    rows = [(c, v) for c, v in zip(q.get("close") or [], q.get("volume") or []) if c is not None]
    return [c for c, _ in rows], [float(v or 0) for _, v in rows]


def _ma(x: list[float], n: int) -> float | None:
    return sum(x[-n:]) / n if len(x) >= n else None


def rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    d = [b - a for a, b in zip(closes[-n - 1:-1], closes[-n:])]
    up, dn = sum(x for x in d if x > 0) / n, -sum(x for x in d if x < 0) / n
    return 100.0 if dn == 0 else 100 - 100 / (1 + up / dn)


def factors(closes: list[float], volumes: list[float], live: float | None = None) -> dict:
    c = list(closes)
    if live:
        c[-1] = live  # today's validated quote replaces the partial daily bar
    px = c[-1]
    ma20, ma50, ma200 = _ma(c, 20), _ma(c, 50), _ma(c, 200)
    rets = [b / a - 1 for a, b in zip(c[-21:-1], c[-20:])] if len(c) >= 21 else []
    f = {"px": round(px, 4), "rsi14": rsi(c),
         "trend20": px / ma20 - 1 if ma20 else None, "trend200": px / ma200 - 1 if ma200 else None,
         "ma50_over_200": (ma50 / ma200 - 1) if ma50 and ma200 else None,
         "mom63": px / c[-64] - 1 if len(c) >= 64 else None, "mom126": px / c[-127] - 1 if len(c) >= 127 else None,
         "mom12_1": c[-22] / c[-250] - 1 if len(c) >= 250 else None,
         "off_high": px / max(c[-250:]) - 1 if len(c) >= 60 else None,
         "vol20": (sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5 * math.sqrt(252)
         if len(rets) > 2 else None,
         "day_move": px / c[-2] - 1 if len(c) >= 2 else None,
         "vol_ratio": volumes[-1] / (sum(volumes[-21:-1]) / 20) if len(volumes) >= 21 and sum(volumes[-21:-1]) else None}
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in f.items()}


def score(f: dict, attention_z: float | None = None) -> dict:
    def mean(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs), 3) if xs else None

    r = f.get("rsi14")
    short = mean([None if f["trend20"] is None else clip(f["trend20"] / 0.05),
                  None if r is None else (-0.5 if r > 75 else clip((r - 50) / 20)),
                  None if f.get("vol_ratio") is None or f.get("day_move") is None
                  else clip((f["vol_ratio"] - 1)) * (1 if f["day_move"] >= 0 else -1),
                  None if attention_z is None else clip(attention_z / 3)])
    medium = mean([None if f["mom63"] is None else clip(f["mom63"] / 0.15),
                   None if f["mom126"] is None else clip(f["mom126"] / 0.25),
                   None if f["off_high"] is None else clip((f["off_high"] + 0.10) / 0.10),
                   None if f["vol20"] is None else -clip((f["vol20"] - 0.35) / 0.20) if f["vol20"] > 0.35 else 0.0])
    long = mean([None if f["trend200"] is None else clip(f["trend200"] / 0.10),
                 None if f["mom12_1"] is None else clip(f["mom12_1"] / 0.30),
                 None if f["ma50_over_200"] is None else (0.5 if f["ma50_over_200"] > 0 else -0.5)])
    parts = {"short": short, "medium": medium, "long": long}
    have = {k: v for k, v in parts.items() if v is not None}
    w = sum(WEIGHTS[k] for k in have)
    comp = round(sum(WEIGHTS[k] * v for k, v in have.items()) / w, 3) if w else None
    return {**parts, "composite": comp}


def earnings_soon(days: int, now: float, get: Callable) -> dict[str, str]:
    """Symbols reporting within `days` calendar days (Nasdaq's free calendar): {symbol: YYYY-MM-DD}."""
    out: dict[str, str] = {}
    for i in range(days + 1):
        d = time.strftime("%Y-%m-%d", time.gmtime(now + i * 86400))
        rows = ((get(EARNINGS, {"date": d}) or {}).get("data") or {}).get("rows") or []
        for row in rows:
            out.setdefault(row.get("symbol", ""), d)
    out.pop("", None)
    return out


def entry_ok(strategy: str, rev: dict | None, cfg: dict, now: float) -> tuple[bool, str]:
    """The review gate for a new entry. No fresh review means no entry (missing data is UNVERIFIED)."""
    if not rev or now - rev.get("t", 0) > cfg["max_age_s"]:
        return False, "no fresh review"
    s = rev["scores"]
    if rev.get("earnings"):
        return False, f"earnings {rev['earnings']}"
    if s["composite"] is None:
        return False, "review has no scores"
    if strategy == "drop_rebound":  # buy dips only in names whose longer trend is intact
        ok = (s["long"] or 0) >= cfg["rebound_min_long"] and (s["medium"] or 0) >= cfg["rebound_min_medium"]
        return ok, f"long {s['long']}, medium {s['medium']}"
    ok = s["composite"] >= cfg["entry_min"]
    return ok, f"composite {s['composite']} vs {cfg['entry_min']}"

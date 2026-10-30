"""Month-end factor timing, one tagged strategy per entry in `active.timing`. After each US month end, compare the
12-month total return of a factor signal ETF with its comparison ETF, both from Yahoo adjusted closes. If the factor
is ahead, hold the factor's UCITS ETF for the next month; otherwise hold a US market ETF. One position of
`entry_weight` of the book; each switches about once a year. Each strategy holds its own market ETF line, so two of
them never share a position.

- value_timing (research loop Q48a, results/Q44_Q48.md): Russell 1000 Value (IWD) vs Growth (IWF); VRVA or VUSA.
- momentum_timing (Q50a, results/Q49_Q52.md): MSCI USA Momentum (MTUM) vs Russell 1000 (IWB); IUMO or VUAG. The test
  compared the winners decile with the losers decile, which has no ETF: momentum vs the market is a deliberate
  approximation.

Kill rule: off after `kill_after_trades` closed trades or `kill_after_days` from the first entry, whichever comes
first, if its compounded return has not beaten VWRP's over the same time. Missing or short data means no new signal:
the last recorded target stands. Nothing here sends an order.
"""
from __future__ import annotations

import calendar
import math
import time
from typing import Callable

from . import active, execution, review

NAME = "value_timing"
NAMES = ("value_timing", "momentum_timing")


def adjusted(sym: str, get: Callable) -> list[tuple[float, float]]:
    """[(t, adjusted close)] of daily bars, oldest first, rows without a price dropped."""
    r = get(review.CHART.format(s=sym), {"range": "2y", "interval": "1d"})["chart"]["result"][0]
    adj = ((r["indicators"].get("adjclose") or [{}])[0].get("adjclose")
           or r["indicators"]["quote"][0].get("close") or [])
    return [(float(t), float(a)) for t, a in zip(r.get("timestamp") or [], adj) if a is not None]


def month_ends(bars: list[tuple[float, float]], now: float) -> dict[str, float]:
    """{YYYY-MM: adjusted close} for each month whose last session has closed. Today's bar counts only after 21:00
    UTC; the latest month counts once no weekday is left in it (a holiday on its last weekday delays it a day)."""
    t_now = time.gmtime(now)
    rows = [(t, a) for t, a in bars if not (time.gmtime(t)[:3] == t_now[:3] and t_now.tm_hour < 21)]
    out: dict[str, float] = {}
    for t, a in rows:
        out[time.strftime("%Y-%m", time.gmtime(t))] = a
    if rows:
        last = time.gmtime(rows[-1][0])
        days = calendar.monthrange(last.tm_year, last.tm_mon)[1]
        left = [d for d in range(last.tm_mday + 1, days + 1) if calendar.weekday(last.tm_year, last.tm_mon, d) < 5]
        if left:
            out.pop(time.strftime("%Y-%m", last), None)
    return out


def signal(value: dict[str, float], growth: dict[str, float], vc: dict) -> dict | None:
    # `value` is the factor's month ends, `growth` the comparison's (named after the first strategy, value_timing)
    """The target for the month after the latest month end both series share, or None without 12 months' history."""
    common = sorted(set(value) & set(growth))
    if not common:
        return None
    m = common[-1]
    y, mo = map(int, m.split("-"))
    back = f"{y - 1}-{mo:02d}"
    if back not in value or back not in growth:
        return None
    rv, rg = value[m] / value[back] - 1, growth[m] / growth[back] - 1
    f, b = vc["factor"], vc["versus"]
    hold = f if rv > rg else "market"
    return {"month": m, "factor_12m": round(rv, 4), "versus_12m": round(rg, 4), "hold": hold,
            "target": vc["factor_ticker"] if hold == f else vc["market_ticker"],
            "why": f"{m}: {f} {rv:+.1%} vs {b} {rg:+.1%} over 12 months, so hold {hold}"}


def exit_why(state: dict | None, ticker: str) -> str | None:
    """'switch' once the latest signal names another ETF than the one held."""
    tgt = (state or {}).get("target")
    return "switch" if tgt and tgt != ticker else None


def kill(records, positions, now: float, vwrp_px, vc: dict, ts: str) -> dict | None:
    """A strategies.json entry when the kill rule is met, else None."""
    ts_ = [t for t in active.trades(records) if t["entry"]["signal"].get("strategy") == vc["name"]]
    if not ts_:
        return None
    closed = [t for t in ts_ if t["exit"]]
    t0 = ts_[0]["entry"].get("t", now)
    if len(closed) < vc["kill_after_trades"] and now - t0 < vc["kill_after_days"] * 86400:
        return None
    growth = 1.0
    for t in closed:
        growth *= 1 + active.closed_result(t)["ret"]
    for t in ts_:
        if not t["exit"]:
            p = positions.get(t["entry"]["ticker"]) or {}
            e_net, e_fee = active._fill(t["entry"])
            cur = float((p.get("walletImpact") or {}).get("currentValue") or e_net)
            growth *= (cur - e_fee) / e_net if e_net else 1.0
    v0 = ts_[0]["entry"]["signal"].get("vwrp_px")
    vwrp = vwrp_px / v0 if v0 and vwrp_px else None
    if vwrp is None or growth - 1 > vwrp - 1:
        return None
    return {"ts": ts, "why": f"{len(closed)} closed trades over {(now - t0) / 86400:.0f} days: {growth - 1:+.2%} vs "
                             f"VWRP {vwrp - 1:+.2%}", "score": {"n": len(closed), "ret": growth - 1,
                                                                 "vwrp_ret": vwrp - 1}}


def entry_orders(cfg, records, positions, quote_of, fx, total, cash, now, vwrp_px, disabled, state) -> tuple[list, list]:
    """One entry into the current target when no trade of this strategy is open. `cfg` is the strategy's own entry."""
    vc, cfg = cfg, cfg["_cfg"]
    NAME = vc["name"]  # noqa: N806
    notes: list[str] = []
    if NAME in disabled or not state or not state.get("target"):
        return [], notes
    if any(e["signal"].get("strategy") == NAME for e in active.open_trades(records)):
        return [], notes
    tk = state["target"]
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    if tk in positions or any(r["ticker"] == tk and (r.get("signal") or {}).get("strategy") == NAME
                              and r.get("ts", "").startswith(day) for r in execution.latest_intents(records).values()):
        return [], notes
    q = quote_of(tk)
    rate = 1.0 if vc["currency"].get(tk) == "GBP" else fx
    if not q or not rate:
        notes.append(f"{NAME}: {tk} is the target but has no validated quote")
        return [], notes
    size = vc["entry_weight"] * total
    if cash < size * (1 + cfg["core"].get("buy_reserve", 0)):
        notes.append(f"{NAME}: {tk} is the target but cash £{cash:.2f} < £{size:.2f}")
        return [], notes
    px_gbp = q["price"] / rate
    qty = math.floor(size / px_gbp * 10 ** cfg["active"]["qty_decimals"]) / 10 ** cfg["active"]["qty_decimals"]
    if qty <= 0:
        return [], notes
    return [(tk, qty, qty * px_gbp, q["price"], True, f"active entry: {NAME} ({vc['rule']}); {state['why']}",
             {"type": "active_entry", "strategy": NAME, "rule": vc["rule"], "month": state["month"],
              "factor_12m": state["factor_12m"], "versus_12m": state["versus_12m"], "hold": state["hold"],
              "approximation": vc.get("approximation"),
              "entry_px": q["price"], "stop": vc["stop_loss"], "take_profit": vc["take_profit"],
              "time_stop_s": vc["time_stop_days"] * 86400, "quote": q, "vwrp_px": vwrp_px})], notes

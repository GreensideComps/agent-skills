"""news_shock_vix_hi (research Q222, benched unproven 6 Nov 2026): a liquid US stock that falls 8% or more against SPY
over the two sessions after a non-earnings 8-K (no item 2.02), filed on a day VIX closed at 25 or above, is bought
2% and held 5 trading days. Theory: liquidity providers earn more in fear (Nagel 2012).

Live timing: the scan needs the close of day +1, so the buy is near the close of day +2. That is Q222's one-day-lag
variant (+5.75%/trade, vs +3.05% at the day +1 close). Q222 FAILED the go-live rule (DSR 0.000; 142 of 197 trades in
2020), so this is a demo bench tag, killed after 30 trades if it does not beat VWRP.
"""
from __future__ import annotations

import math
import re
import time
from datetime import date, datetime, timedelta

from . import active, execution
from .gap_rebound import NY, exit_day, in_buy_window, ny_now

NAME = "news_shock_vix_hi"
EFTS = "https://efts.sec.gov/LATEST/search-index"
_TK = re.compile(r"\(([A-Z][A-Z0-9.\-]*(?:,\s*[A-Z][A-Z0-9.\-]*)*)\)\s*\(CIK")


def filings(hits: list[dict], earnings: bool = False) -> list[dict]:
    """[{symbol, items, file_date}] for 8-Ks without item 2.02 (with it when `earnings`: the results releases that
    gap_rebound scans), one row per listed ticker (first ticker per filer)."""
    out = []
    for h in hits:
        s = h.get("_source") or h
        items = s.get("items") or []
        if ("2.02" in items) != earnings or (s.get("form") or "8-K") != "8-K":
            continue
        for name in s.get("display_names") or []:
            m = _TK.search(name)
            if m:
                out.append({"symbol": m.group(1).split(",")[0].strip(), "items": items, "file_date": s.get("file_date")})
    return out


def window(days: list[str], d0: str) -> tuple[str, str] | None:
    """Calendar filing dates whose first trading day on or after is `d0`: (day after the previous session, d0)."""
    if d0 not in days or days.index(d0) == 0:
        return None
    prev = date.fromisoformat(days[days.index(d0) - 1])
    return (prev + timedelta(days=1)).isoformat(), d0


def move(sb: list[tuple], spy: list[tuple], d0: str) -> dict | None:
    """Q217/Q222 shock: close of d0+1 over close of d0-1, minus SPY's, and the median dollar volume of the 20 sessions
    before d0. None when the bars do not cover the window."""
    days = [d for d, _, _ in sb]
    sd = {d: c for d, c, _ in spy}
    if d0 not in days:
        return None
    i = days.index(d0)
    if i < 20 or i + 1 >= len(sb) or days[i - 1] not in sd or days[i + 1] not in sd:
        return None
    ret = sb[i + 1][1] / sb[i - 1][1] - 1
    spy_ret = sd[days[i + 1]] / sd[days[i - 1]] - 1
    dv = sorted(c * v for _, c, v in sb[i - 20:i])
    return {"day0": d0, "day_p1": days[i + 1], "ret": round(ret, 4), "spy_ret": round(spy_ret, 4),
            "ear": round(ret - spy_ret, 4), "median_dollar_vol": round((dv[9] + dv[10]) / 2)}


def recent(signals: dict, sym: str, d0: str, days: list[str], gap: int = 10) -> bool:
    """True when the same name already had a signal within `gap` trading days before d0."""
    last = [s["day0"] for s in signals.values() if s.get("symbol") == sym and s["day0"] < d0]
    if not last or max(last) not in days or d0 not in days:
        return bool(last) and (date.fromisoformat(d0) - date.fromisoformat(max(last))).days <= gap * 7 // 5
    return days.index(d0) - days.index(max(last)) <= gap


def entry_orders(nc, cfg, records, positions, quote_of, fx, total, cash, now, vwrp_px, disabled, state,
                 precision=None) -> tuple[list, list]:
    """One buy per eligible signal whose buy day is today (New York) inside the buy window; one try per name a day."""
    notes: list[str] = []
    if NAME in disabled or not state:
        return [], notes
    today = ny_now(now).date().isoformat()
    sigs = {tk: s for tk, s in (state.get("signals") or {}).items() if s.get("eligible") and s.get("buy_day") == today}
    if not sigs:
        return [], notes
    if not in_buy_window(now, nc["buy_window_min"]):
        notes.append(f"{NAME}: {', '.join(sorted(sigs))} buy in the last {nc['buy_window_min']} minutes of {today}")
        return [], notes
    held = [e for e in active.open_trades(records) if e["signal"].get("strategy") == NAME]
    open_tk = {e["ticker"] for e in active.open_trades(records)}
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    tried = {r["ticker"] for r in execution.latest_intents(records).values()
             if (r.get("signal") or {}).get("strategy") == NAME and r.get("ts", "").startswith(day)
             and r.get("status") != "not_sent" and "quantity-precision-mismatch" not in (r.get("error") or "")}
    size = nc["entry_weight"] * total
    reserve = 1 + cfg["core"].get("buy_reserve", 0)
    out = []
    for tk, s in sorted(sigs.items(), key=lambda kv: kv[1]["ear"]):
        if len(held) + len(out) >= nc["max_open"]:
            notes.append(f"{NAME}: {tk} qualifies but {nc['max_open']} trades are open (20% cap)")
            break
        if tk in open_tk or tk in positions or tk in tried:
            continue
        q = quote_of(tk)
        if not q or not fx:
            notes.append(f"{NAME}: {tk} has no validated quote")
            continue
        if cash < size * reserve:
            notes.append(f"{NAME}: {tk} qualifies but cash £{cash:.2f} < £{size * reserve:.2f}")
            break
        d = 10 ** min(nc.get("qty_decimals", 3), (precision or {}).get(tk, 8))
        qty = math.floor(size / (q["price"] / fx) * d) / d
        if qty <= 0:
            continue
        xd = exit_day(today, nc["hold_days"])
        x_t = datetime.fromisoformat(f"{xd}T15:00:00").replace(tzinfo=NY).timestamp()
        out.append((tk, qty, qty * q["price"] / fx, q["price"], True,
                    f"active entry: {NAME} ({nc['edge']}); {s['ear']:+.1%} vs SPY after 8-K items "
                    f"{','.join(s['items'])} on {s['day0']}, VIX {s['vix']}",
                    {"type": "active_entry", "strategy": NAME, "rule": nc["rule"], "edge": nc["edge"],
                     "day0": s["day0"], "ear": s["ear"], "items": s["items"], "vix": s["vix"], "exit_day": xd,
                     "entry_px": q["price"], "stop": None, "take_profit": None, "time_stop_s": round(x_t - now),
                     "quote": q, "vwrp_px": vwrp_px}))
        cash -= size * reserve
    return out, notes

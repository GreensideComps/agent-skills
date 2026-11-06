"""social_trend (decision C8, owner 30 Oct 08:15Z): Chris Camillo-style social arbitrage on a fixed universe of US
consumer brands, written down in config before any signal was looked at.

Once a week, after the Friday US close, each brand's English Wikipedia article is scored: the mean of its last 28 days
of views against the 28-day means of the 52 weeks before them. A brand whose attention is at least `z_entry` standard
deviations above that baseline and still rising week on week is a candidate for the next US session, unless its
stock is already up more than `max_run_up` over 20 trading days (the crowd got there first). Google Trends and Reddit
are confirmation only; both refuse this host (Trends 429, Reddit 403, tested 30 Oct), so per the spec a candidate
counts as confirmed without them and every scan records that. An open trade also exits when its brand's attention
falls back below baseline + `z_exit` SD. Missing data for a brand means no signal for it. Nothing here sends an order.
"""
from __future__ import annotations

import calendar
import math
import time

from . import active, execution

NAME = "social_trend"
CONFIRMATION = "unavailable: Google Trends HTTP 429 and Reddit HTTP 403 from this host, so confirmed per the spec"


def signal_friday(now: float) -> str:
    """The latest Friday (YYYY-MM-DD) whose US close (taken as 21:00 UTC, after the close in summer and winter) has
    passed."""
    t = time.gmtime(now)
    back = (t.tm_wday - 4) % 7
    if back == 0 and t.tm_hour < 21:
        back = 7
    return time.strftime("%Y-%m-%d", time.gmtime(now - back * 86400))


def valid_until(friday: str, days: int) -> float:
    """Candidates may be entered until this time: the next US session, with room for a Monday holiday."""
    return calendar.timegm(time.strptime(friday, "%Y-%m-%d")) + 86400 * days + 86400


def attention(series: list[tuple[str, int]], window: int = 28, weeks: int = 52) -> dict | None:
    """z of the last `window`-day mean of views against the `window`-day means ending each week of the `weeks`
    before it; `rising` when the last 7 days beat the 7 before. None without enough history."""
    v = [x for _, x in series]
    if len(v) < window + 7 * weeks:
        return None
    cur = sum(v[-window:]) / window
    base = [sum(v[e - window:e]) / window for e in (len(v) - window - 7 * k for k in range(weeks)) if e - window >= 0]
    mu = sum(base) / len(base)
    sd = (sum((b - mu) ** 2 for b in base) / (len(base) - 1)) ** 0.5
    return {"day": series[-1][0], "mean28": round(cur, 1), "base_mean": round(mu, 1), "base_sd": round(sd, 1),
            "z": round((cur - mu) / sd, 2) if sd > 0 else None,
            "rising": sum(v[-7:]) > sum(v[-14:-7]), "last7": sum(v[-7:]), "prior7": sum(v[-14:-7])}


def run_up(closes: list[float], n: int = 20) -> float | None:
    return closes[-1] / closes[-1 - n] - 1 if len(closes) > n and closes[-1 - n] else None


def judge(row: dict, sc: dict) -> dict:
    """Mark one brand's scan row as a candidate or not, with the reason."""
    z, r = row.get("z"), row.get("ret20")
    if row.get("error") or z is None:
        why = "no data: " + (row.get("error") or "not enough attention history")
    elif z < sc["z_entry"]:
        why = f"attention z {z} < {sc['z_entry']}"
    elif not row.get("rising"):
        why = "attention not rising week on week"
    elif r is None:
        why = "no price history"
    elif r > sc["max_run_up"]:
        why = f"stock already up {r:+.1%} over 20 trading days"
    else:
        return {**row, "candidate": True, "why": f"attention z {z}, rising, 20-day move {r:+.1%}"}
    return {**row, "candidate": False, "why": why}


def entry_orders(cfg, records, positions, quote_of, fx, total, cash, now, vwrp_px, disabled, scan,
                 reviews=None) -> tuple[list, list]:
    """Entries for this week's candidates, sized like every active entry, only before the scan's deadline."""
    sc = cfg["active"]["social"]
    notes: list[str] = []
    if NAME in disabled or not scan or now > scan.get("valid_until", 0):
        return [], notes
    open_tk = {e["ticker"] for e in active.open_trades(records)}
    tried = {r["ticker"] for r in execution.latest_intents(records).values()
             if (r.get("signal") or {}).get("strategy") == NAME and r["signal"].get("friday") == scan["friday"]}
    size = cfg["active"]["entry_weight"] * total
    reserve = 1 + cfg["core"].get("buy_reserve", 0)
    out = []
    for tk, row in sorted(scan.get("rows", {}).items()):
        if not row.get("candidate") or tk in open_tk or tk in tried or tk in positions:
            continue
        q = quote_of(tk)
        if not q or not fx:
            notes.append(f"{NAME}: {tk} is a candidate but has no validated quote")
            continue
        if cash < size * reserve:
            notes.append(f"{NAME}: {tk} is a candidate but cash £{cash:.2f} < £{size * reserve:.2f}")
            break
        px_gbp = q["price"] / fx
        qty = math.floor(size / px_gbp * 10 ** cfg["active"]["qty_decimals"]) / 10 ** cfg["active"]["qty_decimals"]
        if qty <= 0:
            continue
        rev = (reviews or {}).get(tk)
        out.append((tk, qty, qty * px_gbp, q["price"], True, f"active entry: {NAME} ({sc['rule']}); {row['why']}",
                    {"type": "active_entry", "strategy": NAME, "rule": sc["rule"], "friday": scan["friday"],
                     "attention": {k: row.get(k) for k in ("article", "z", "mean28", "base_mean", "rising")},
                     "ret20": row.get("ret20"), "confirmation": CONFIRMATION,
                     "entry_px": q["price"], "stop": sc["stop_loss"], "take_profit": sc["take_profit"],
                     "time_stop_s": sc["time_stop_days"] * 86400, "quote": q, "vwrp_px": vwrp_px,
                     "review": rev and {"scores": rev["scores"], "factors": rev["factors"]}}))
    return out, notes


def exit_why(scan: dict | None, ticker: str, sc: dict) -> str | None:
    """'attention' when the latest scan shows the brand back below baseline + z_exit SD; None when it is unknown."""
    z = ((scan or {}).get("rows", {}).get(ticker) or {}).get("z")
    return "attention" if z is not None and z < sc["z_exit"] else None

"""gap_rebound (research loop Q205, results/Q203.md): a live-only forward test of single-stock mispricing after a big
earnings drop on a weak company. UNPROVEN: the idea is the unplanned control group of Q203 (+5.0%/trade vs SPY over 60
days, t 2.75, 199 trades, 2014-22), so no backtest claim stands; it is judged only on trades after 3 Nov 2026.

Rule: a US stock that reported earnings on day 0 (Nasdaq's free calendar), is liquid (median dollar volume over the 20
days before day -1 >= $10m) and fell >= 10% versus SPY over days -1..+1 (close of day +1 over close of day -2), and
fails the health gate on filings made before day 0 (TTM free cash flow <= 0, or TTM revenue down year on year). Buy 2%
of the book near the close of day +2 (the last 90 minutes of New York trading), hold 60 trading days, then sell. No
stop or take-profit. Kill after 30 closed trades (or 730 days) if it has not beaten VWRP (value_timing.kill).

Differences from the research test, recorded so the forward test is read correctly: the universe is every US stock
Trading 212 lists with a market cap >= `min_mcap` (not the 450-stock Tiingo set); day 0 is Nasdaq's report date (not
the 8-K 2.02 filing date); the buy is a market order in the last 90 minutes, not the exact close; the 60-day exit date
counts weekdays less the NYSE holidays listed below. A missing fundamental is UNVERIFIED: no trade.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import active, execution

NAME = "gap_rebound"
NY = ZoneInfo("America/New_York")
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{s}"
EARNINGS = "https://api.nasdaq.com/api/calendar/earnings"
TICKERS = "https://www.sec.gov/files/company_tickers.json"
FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
REVENUE = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
           "RevenueFromContractWithCustomerIncludingAssessedTax")
OCF = ("NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations")
CAPEX = ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets")
NYSE_HOLIDAYS = {"2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
                 "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"}


def _d(s: str) -> date:
    return date.fromisoformat(s)


def mcap(row: dict) -> float:
    s = (row.get("marketCap") or "").replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def bars(sym: str, get: Callable, rng: str = "3mo") -> list[tuple[str, float, float]]:
    """[(YYYY-MM-DD New York date, close, volume)] from Yahoo, oldest first, empty days dropped."""
    r = get(CHART.format(s=sym), {"range": rng, "interval": "1d"})["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = []
    for t, c, v in zip(r.get("timestamp") or [], q.get("close") or [], q.get("volume") or []):
        if c is not None:
            out.append((datetime.fromtimestamp(t, NY).date().isoformat(), float(c), float(v or 0)))
    return out


def vix_tag(vix_bars: list[tuple], day: str, hi: float = 25.0) -> tuple[float | None, str]:
    """The VIX close on `day` (else the last one before it) and its regime tag (Q218b: vix_hi at `hi` or above,
    vix_lo below, vix_unknown when no close is in)."""
    c = [x[1] for x in vix_bars or [] if x[0] <= day]
    if not c:
        return None, "vix_unknown"
    return round(c[-1], 2), ("vix_hi" if c[-1] >= hi else "vix_lo")


def day_index(days: list[str], d: str) -> int | None:
    """The index of the first trading day on or after calendar date `d` (a report dated on a non-trading day reacts
    on the next session)."""
    for i, x in enumerate(days):
        if x >= d:
            return i
    return None


def event_move(sb: list[tuple], spy: list[tuple], day0: str) -> dict | None:
    """EAR (stock minus SPY, close of day +1 over close of day -2) and liquidity, or None when the bars do not cover
    the window. Both series must hold the same trading days around the event."""
    sd = {d: c for d, c, _ in spy}
    days = [d for d, _, _ in sb]
    i = day_index(days, day0)
    if i is None or i < 22 or i + 1 >= len(sb):
        return None
    dm2, dp1 = days[i - 2], days[i + 1]
    if dm2 not in sd or dp1 not in sd:
        return None
    ret = sb[i + 1][1] / sb[i - 2][1] - 1
    spy_ret = sd[dp1] / sd[dm2] - 1
    dv = sorted(c * v for _, c, v in sb[i - 22:i - 2])  # the 20 sessions before day -1
    med = (dv[9] + dv[10]) / 2
    return {"day0": days[i], "day_m2": dm2, "day_p1": dp1, "ret": round(ret, 4), "spy_ret": round(spy_ret, 4),
            "ear": round(ret - spy_ret, 4), "median_dollar_vol": round(med)}


# ------------------------------------------------------------ fundamentals (SEC companyfacts, point in time)
def _rows(facts: dict, tags: tuple, before: str) -> list[dict]:
    """USD duration entries from 10-K/10-Q filings filed before `before`, for the first tag with the latest data."""
    g = (facts.get("facts") or {}).get("us-gaap") or {}
    best: list[dict] = []
    for tag in tags:
        rows = [r for r in ((g.get(tag) or {}).get("units") or {}).get("USD", [])
                if r.get("start") and r.get("filed", "9") < before and (r.get("form") or "").startswith(("10-K", "10-Q"))]
        if rows and (not best or max(r["end"] for r in rows) > max(r["end"] for r in best)):
            best = rows
    return best


def _near(a: str, b: str, days: int) -> bool:
    return abs((_d(a) - _d(b)).days) <= days


def ttm(rows: list[dict], end: str) -> float | None:
    """Trailing twelve months ending `end`: an annual figure, or year-to-date + last full year - prior year-to-date
    (10-Q cash flows are reported year to date). The latest filing of each period wins (restatements)."""
    by: dict[tuple, dict] = {}
    for r in sorted(rows, key=lambda r: r["filed"]):
        by[(r["start"], r["end"])] = r
    rs = list(by.values())

    def dur(r):
        return (_d(r["end"]) - _d(r["start"])).days
    cur = [r for r in rs if r["end"] == end]
    for r in cur:
        if 350 <= dur(r) <= 380:
            return float(r["val"])
    for y in sorted(cur, key=dur, reverse=True):
        start_prev = (_d(y["start"]) - timedelta(days=1)).isoformat()
        fy = next((r for r in rs if 350 <= dur(r) <= 380 and _near(r["end"], start_prev, 7)), None)
        py = next((r for r in rs if r is not y and _near(r["end"], (_d(end) - timedelta(days=365)).isoformat(), 7)
                   and abs(dur(r) - dur(y)) <= 10), None)
        if fy and py:
            return float(y["val"]) + float(fy["val"]) - float(py["val"])
    return None


def capex_ttm(facts: dict, before: str, end: str) -> tuple[float | None, str]:
    """TTM capital expenditure ending `end`: the first capex tag with a TTM figure, else that tag's year-to-date
    figure annualised (some filers leave capex out of the 10-K's tagged facts). None when no tag reports near `end`."""
    for tag in CAPEX:
        rows = _rows(facts, (tag,), before)
        v = ttm(rows, end) if rows else None
        if v is not None:
            return v, ""
        ytd = [r for r in rows if r["end"] == end]
        if ytd:
            r = max(ytd, key=lambda r: (_d(r["end"]) - _d(r["start"])).days)
            months = max(1, round((_d(r["end"]) - _d(r["start"])).days / 30.4))
            return float(r["val"]) * 12 / months, f" (capex annualised from {months} months)"
    return None, ""


def health(facts: dict, before: str) -> dict:
    """{fcf, rev, rev_prev, end, weak} from filings made before `before`; weak is None (UNVERIFIED) when the gate
    cannot be decided. Weak = TTM free cash flow <= 0 or TTM revenue below the year before. With no capex figure,
    FCF is at most operating cash flow: that still decides a weak company (OCF <= 0 or revenue down), not a healthy one."""
    rev, ocf = _rows(facts, REVENUE, before), _rows(facts, OCF, before)
    out = {"end": None, "fcf": None, "rev": None, "rev_prev": None, "weak": None}
    if not rev or not ocf:
        out["why"] = "UNVERIFIED: no revenue or operating cash flow in SEC filings"
        return out
    end = max(r["end"] for r in ocf)
    r_end = max(r["end"] for r in rev)
    o = ttm(ocf, end)
    c, note = capex_ttm(facts, before, end)
    rv = ttm(rev, r_end)
    prev_end = next((e for e in sorted({r["end"] for r in rev}, reverse=True)
                     if _near(e, (_d(r_end) - timedelta(days=365)).isoformat(), 10)), None)
    rp = ttm(rev, prev_end) if prev_end else None
    out.update(end=end, rev=rv, rev_prev=rp, fcf=None if o is None or c is None else round(o - c))
    if o is None or rv is None or rp is None:
        out["why"] = "UNVERIFIED: a trailing-twelve-month figure could not be built"
        return out
    if c is None:
        if o <= 0 or rv < rp:
            out["weak"], note = True, " (no capex reported: FCF <= operating cash flow)"
            out["fcf"] = round(o)
        else:
            out["why"] = (f"UNVERIFIED: no capex reported; operating cash flow ${o / 1e6:,.0f}m and revenue up, "
                          "so the FCF test cannot be decided")
            return out
    else:
        out["weak"] = out["fcf"] <= 0 or rv < rp
    out["why"] = (f"TTM FCF ${out['fcf'] / 1e6:,.0f}m, revenue ${rv / 1e6:,.0f}m vs ${rp / 1e6:,.0f}m a year earlier"
                  f" (to {end}){note}")
    return out


# ------------------------------------------------------------ calendar helpers
def exit_day(entry_day: str, n: int = 60) -> str:
    """The New York date `n` trading days after `entry_day` (weekdays less the listed NYSE holidays)."""
    d, k = _d(entry_day), 0
    while k < n:
        d += timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in NYSE_HOLIDAYS:
            k += 1
    return d.isoformat()


def ny_now(now: float) -> datetime:
    return datetime.fromtimestamp(now, NY)


def in_buy_window(now: float, minutes: int) -> bool:
    t = ny_now(now)
    close = t.replace(hour=16, minute=0, second=0, microsecond=0)
    return close - timedelta(minutes=minutes) <= t < close - timedelta(minutes=2)


# ------------------------------------------------------------ orders
def entry_orders(gc, cfg, records, positions, quote_of, fx, total, cash, now, vwrp_px, disabled, state,
                 precision=None) -> tuple[list, list]:
    """One buy per eligible signal whose buy day is today (New York) inside the buy window; one try per name a day
    unless the order never reached the broker."""
    notes: list[str] = []
    if NAME in disabled or not state:
        return [], notes
    today = ny_now(now).date().isoformat()
    sigs = {tk: s for tk, s in (state.get("signals") or {}).items() if s.get("eligible") and s.get("buy_day") == today}
    if not sigs:
        return [], notes
    if not in_buy_window(now, gc["buy_window_min"]):
        notes.append(f"{NAME}: {', '.join(sorted(sigs))} buy in the last {gc['buy_window_min']} minutes of {today}")
        return [], notes
    held = [e for e in active.open_trades(records) if e["signal"].get("strategy") == NAME]
    open_tk = {e["ticker"] for e in active.open_trades(records)}
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    tried = {r["ticker"] for r in execution.latest_intents(records).values()
             if (r.get("signal") or {}).get("strategy") == NAME and r.get("ts", "").startswith(day)
             and r.get("status") != "not_sent" and "quantity-precision-mismatch" not in (r.get("error") or "")}
    size = gc["entry_weight"] * total
    reserve = 1 + cfg["core"].get("buy_reserve", 0)
    out = []
    for tk, s in sorted(sigs.items(), key=lambda kv: kv[1]["ear"]):
        if len(held) + len(out) >= gc["max_open"]:
            notes.append(f"{NAME}: {tk} qualifies but {gc['max_open']} trades are open")
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
        d = 10 ** min(gc.get("qty_decimals", 3), (precision or {}).get(tk, 8))
        qty = math.floor(size / (q["price"] / fx) * d) / d
        if qty <= 0:
            continue
        xd = exit_day(today, gc["hold_days"])
        x_t = datetime.fromisoformat(f"{xd}T15:00:00").replace(tzinfo=NY).timestamp()
        out.append((tk, qty, qty * q["price"] / fx, q["price"], True,
                    f"active entry: {NAME} ({gc['rule']}); EAR {s['ear']:+.1%} around {s['day0']}; {s['health']['why']}",
                    {"type": "active_entry", "strategy": NAME, "rule": gc["rule"],
                     "edge": gc.get("edge_vix_hi", gc["edge"]) if s.get("variant") == "vix_hi" else gc["edge"],
                     "variant": s.get("variant"), "vix": s.get("vix"), "day0": s["day0"], "ear": s["ear"], "health": s["health"], "exit_day": xd,
                     "entry_px": q["price"], "stop": None, "take_profit": None, "time_stop_s": round(x_t - now),
                     "quote": q, "vwrp_px": vwrp_px}))
        cash -= size * reserve
    return out, notes

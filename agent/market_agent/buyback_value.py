"""buyback_value (research loop Q206, results/Q206.md): a monthly basket of US stocks buying back a lot of stock
while cheap on cash flow. NEAR MISS, UNPROVEN: +2.2%/trade vs its universe 2015-22, DSR 0.78 < 0.95; a one-month-late
entry and double costs stayed positive; nothing in mega caps. Judged only on trades after 3 Nov 2026.

Picks come from the research loop, which runs the point-in-time screen at each month-end and writes
`picks_dir/Q206_picks_YYYY-MM.csv` (US $2bn+, ex financials and utilities; TTM buybacks / market cap in the top 10%,
shares down y/y, TTM FCF > 0, net debt / EBITDA < 3, FCF / EV in the top 30%), best FCF / EV first. The agent buys
the newest month's picks at `entry_weight` each while fewer than `max_open` are held (the research basket is ~20
names a month held 6 months, far more than 2% slots allow, so the cap takes the cheapest names first), at most
`max_per_sic2` per SIC two-digit group across the open basket (a sector guard), and sells each after `hold_days`
(time stop; no stop-loss). Funded by selling VWRP when cash is short, like stock_screen (demo only); its P&L is kept
out of the sleeve's loss stop. Kill after 30 closed trades (or 730 days) if it has not beaten VWRP.
"""
from __future__ import annotations

import csv
import math
import time
from pathlib import Path

from . import active, execution

NAME = "buyback_value"


def load_picks(picks_dir: str, now: float, max_age_days: int) -> dict | None:
    """{month, rows: [{symbol, sic, ...}]} from the newest Q206_picks_YYYY-MM.csv no older than `max_age_days`
    past its month-end, else None (stale picks buy nothing)."""
    d = Path(picks_dir)
    files = sorted(d.glob("Q206_picks_????-??.csv")) if d.is_dir() else []
    if not files:
        return None
    f = files[-1]
    month = f.stem.split("_")[-1]
    y, m = int(month[:4]), int(month[5:])
    end = time.mktime((y + m // 12, m % 12 + 1, 1, 0, 0, 0, 0, 0, 0))  # first day after the month
    if now - end > max_age_days * 86400:
        return None
    with f.open() as fh:
        rows = [r for r in csv.DictReader(fh) if (r.get("symbol") or "").strip()]
    return {"month": month, "file": str(f), "rows": rows}


def _ours(records):
    return [e for e in active.open_trades(records) if e["signal"].get("strategy") == NAME]


def wanted(bc, picks, records, positions, tradeable, disabled) -> list[dict]:
    """The picks the basket would buy now, in rank order: tradeable, not held, not already bought from this month's
    list, within the open cap and the per-group cap."""
    if not picks or NAME in disabled:
        return []
    held = _ours(records)
    groups: dict[str, int] = {}
    for e in held:
        g = e["signal"].get("sic2")
        groups[g] = groups.get(g, 0) + 1
    done = {t["entry"]["ticker"] for t in active.trades(records)
            if t["entry"]["signal"].get("strategy") == NAME and t["entry"]["signal"].get("picks_month") == picks["month"]}
    out = []
    for r in picks["rows"]:
        if len(held) + len(out) >= bc["max_open"]:
            break
        tk = tradeable(r["symbol"].strip())
        g = (r.get("sic") or "")[:2]
        if not tk or tk in positions or tk in done or groups.get(g, 0) >= bc["max_per_sic2"]:
            continue
        groups[g] = groups.get(g, 0) + 1
        out.append({**r, "ticker": tk, "sic2": g})
    return out


def need_gbp(bc, cfg, picks, records, positions, tradeable, total, disabled) -> float:
    if not bc:
        return 0.0
    n = len(wanted(bc, picks, records, positions, tradeable, disabled))
    return n * bc["entry_weight"] * total * (1 + cfg["core"].get("buy_reserve", 0))


def entry_orders(bc, cfg, records, positions, quote_of, fx, total, cash, now, vwrp_px, disabled, picks, tradeable,
                 market_open, precision=None) -> tuple[list, list]:
    """One buy per wanted pick whose market is open; one try per name a day unless it never reached the broker.
    `cash` is the cash above the sleeve's reserve."""
    notes: list[str] = []
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    tried = {r["ticker"] for r in execution.latest_intents(records).values()
             if (r.get("signal") or {}).get("strategy") == NAME and r.get("ts", "").startswith(day)
             and r.get("status") != "not_sent" and "quantity-precision-mismatch" not in (r.get("error") or "")}
    size = bc["entry_weight"] * total
    reserve = 1 + cfg["core"].get("buy_reserve", 0)
    out = []
    for w in wanted(bc, picks, records, positions, tradeable, disabled):
        tk = w["ticker"]
        if tk in tried or not market_open(tk):
            continue
        q = quote_of(tk)
        if not q or not fx:
            notes.append(f"{NAME}: {tk} has no validated quote")
            continue
        if cash < size * reserve:
            notes.append(f"{NAME}: {tk} waits for cash (£{cash:.2f} < £{size * reserve:.2f})")
            break
        d = 10 ** min(bc.get("qty_decimals", 3), (precision or {}).get(tk, 8))
        qty = math.floor(size / (q["price"] / fx) * d) / d
        if qty <= 0:
            continue
        out.append((tk, qty, qty * q["price"] / fx, q["price"], True,
                    f"active entry: {NAME} ({bc['rule']}); picks {picks['month']}",
                    {"type": "active_entry", "strategy": NAME, "rule": bc["rule"], "edge": bc["edge"],
                     "picks_month": picks["month"], "sic2": w["sic2"],
                     "pick": {k: w.get(k) for k in ("rank", "fcf_ev", "buyback_yield", "nd_ebitda") if k in w},
                     "entry_px": q["price"], "stop": None, "take_profit": None,
                     "time_stop_s": bc["hold_days"] * 86400, "quote": q, "vwrp_px": vwrp_px}))
        cash -= size * reserve
    return out, notes

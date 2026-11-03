"""stock_screen (research loop Q199, results/Q199.md): a yearly basket of individual US stocks picked by the
system-designed screener (research/stock_screener/pick1.py). LOW CONFIDENCE: the pre-registered backtest failed
(+3.4%/yr vs its universe, t 0.85); the pre-registration said before the result that it runs as a demo forward test
either way.

Rules: hold each name in `picks` at `entry_weight` of the book; no stop, take-profit or time stop. Once a year (early
January, from December month-end data) the picks list in config.json is replaced: a held name that is no longer in
`picks` exits with reason "rebalance", and a new name is bought. Each sale is one closed trade, scored against VWRP over
the same days. Kill after `kill_after_trades` closed trades or `kill_after_days` from the first entry if it has not
beaten VWRP (value_timing.kill). When cash is short, the basket is funded by selling VWRP (demo only).

The basket is a separate forward test funded from the core, not the C6 sleeve: its P&L is left out of the sleeve's
daily loss stop and freeze (active.sleeve_pnl), so one bad day across 12 stocks cannot switch the sleeve off.
"""
from __future__ import annotations

import math
import time

from . import active, execution

NAME = "stock_screen"


def watch(sc: dict | None) -> list[str]:
    """The tickers the basket needs prices for: the current picks and the names dropped at the last rebalance."""
    if not sc:
        return []
    return list(dict.fromkeys([*sc.get("picks", []), *sc.get("previous_picks", [])]))


def exit_why(sc: dict | None, ticker: str) -> str | None:
    """'rebalance' once a held name has left the picks list; otherwise held."""
    if not sc:
        return None
    return None if ticker in sc.get("picks", []) else "rebalance"


def missing(sc: dict, records, positions, disabled) -> list[str]:
    """Picks with no open stock_screen trade and no position held by anything else, in score order."""
    if NAME in disabled:
        return []
    held = {e["ticker"] for e in active.open_trades(records) if e["signal"].get("strategy") == NAME}
    return [t for t in sc.get("picks", []) if t not in held and t not in positions]


def need_gbp(sc: dict | None, cfg, records, positions, total: float, disabled) -> float:
    """The cash the basket still has to spend, with the broker's buy reserve; the core buy leaves this alone."""
    if not sc:
        return 0.0
    n = len(missing(sc, records, positions, disabled))
    return n * sc["entry_weight"] * total * (1 + cfg["core"].get("buy_reserve", 0))


def entry_orders(sc, cfg, records, positions, quote_of, fx, total, cash, now, vwrp_px, disabled,
                 market_open) -> tuple[list, list]:
    """One buy per missing pick whose market is open and price validated; at most one try per name per day. `cash`
    is the cash above the sleeve's reserve, so the basket never spends the other strategies' money."""
    notes: list[str] = []
    if not sc or NAME in disabled:
        return [], notes
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    tried = {r["ticker"] for r in execution.latest_intents(records).values()
             if (r.get("signal") or {}).get("strategy") == NAME and r.get("ts", "").startswith(day)}
    size = sc["entry_weight"] * total
    reserve = 1 + cfg["core"].get("buy_reserve", 0)
    out = []
    for tk in missing(sc, records, positions, disabled):
        if tk in tried or not market_open(tk):
            continue
        q = quote_of(tk)
        if not q or not fx:
            notes.append(f"{NAME}: {tk} has no validated quote")
            continue
        if cash < size * reserve:
            notes.append(f"{NAME}: {tk} waits for cash (£{cash:.2f} < £{size * reserve:.2f})")
            break
        d = 10 ** sc.get("qty_decimals", cfg["active"]["qty_decimals"])
        qty = math.floor(size / (q["price"] / fx) * d) / d
        if qty <= 0:
            continue
        out.append((tk, qty, qty * q["price"] / fx, q["price"], True,
                    f"active entry: {NAME} ({sc['rule']}); picks {sc['picks_month']}",
                    {"type": "active_entry", "strategy": NAME, "rule": sc["rule"], "picks_month": sc["picks_month"],
                     "entry_px": q["price"], "stop": None, "take_profit": None, "time_stop_s": None,
                     "quote": q, "vwrp_px": vwrp_px}))
        cash -= size * reserve
    return out, notes


def fund_order(sc, cfg, positions, quote_of, total: float, cash: float, keep: float, need: float, day: str,
               records) -> tuple | None:
    """A VWRP sale that frees the basket's remaining spend when cash above the sleeve's reserve cannot cover the next
    buy. At most one a day; sized to the whole remaining need so the basket fills in one funding step."""
    if not sc or not sc.get("fund_from_vwrp") or need <= 0:
        return None
    reserve = 1 + cfg["core"].get("buy_reserve", 0)
    free = cash - keep
    if free >= min(need, sc["entry_weight"] * total * reserve):
        return None
    if any((r.get("signal") or {}).get("type") == "screen_fund" and r.get("ts", "").startswith(day)
           for r in execution.latest_intents(records).values()):
        return None
    bt = cfg["benchmark"]["t212"]
    p = positions.get(bt) or {}
    q = quote_of(bt)
    if not q or not p:
        return None
    gbp = min(need - free, cfg["limits"]["max_order_gbp"])  # also refills the sleeve reserve the basket must not use
    qty = min(math.ceil(gbp / q["price"] * 100) / 100, float(p.get("quantityAvailableForTrading") or 0))
    if qty <= 0:
        return None
    return (bt, -qty, qty * q["price"], q["price"], True,
            f"{NAME} funding: sell VWRP to buy the screen basket (needs £{need:.2f}, free cash £{free:.2f})",
            {"type": "screen_fund", "strategy": NAME, "need_gbp": round(need, 2), "quote": q})

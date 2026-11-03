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


def exit_why(sc: dict | None, ticker: str, state: dict | None = None) -> str | None:
    """A hard SEC event found by `watch_filings` (state["exit"]), else 'rebalance' once a held name has left the
    picks list; otherwise held."""
    if not sc:
        return None
    hard = ((state or {}).get("exit") or {}).get(ticker)
    if hard:
        return hard["why"]
    return None if ticker in sc.get("picks", []) else "rebalance"


def missing(sc: dict, records, positions, disabled) -> list[str]:
    """Picks with no open stock_screen trade and no position held by anything else, in score order."""
    if NAME in disabled:
        return []
    held = {e["ticker"] for e in active.open_trades(records) if e["signal"].get("strategy") == NAME}
    sold = set((sc.get("_state") or {}).get("exit") or {})  # a hard-event exit holds the cash until January
    return [t for t in sc.get("picks", []) if t not in held and t not in positions and t not in sold]


def need_gbp(sc: dict | None, cfg, records, positions, total: float, disabled) -> float:
    """The cash the basket still has to spend, with the broker's buy reserve; the core buy leaves this alone."""
    if not sc:
        return 0.0
    n = len(missing(sc, records, positions, disabled))
    return n * sc["entry_weight"] * total * (1 + cfg["core"].get("buy_reserve", 0))


def entry_orders(sc, cfg, records, positions, quote_of, fx, total, cash, now, vwrp_px, disabled,
                 market_open, precision=None) -> tuple[list, list]:
    """One buy per missing pick whose market is open and price validated; at most one try per name per day. `cash`
    is the cash above the sleeve's reserve, so the basket never spends the other strategies' money."""
    notes: list[str] = []
    if not sc or NAME in disabled:
        return [], notes
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    tried = {r["ticker"] for r in execution.latest_intents(records).values()
             if (r.get("signal") or {}).get("strategy") == NAME and r.get("ts", "").startswith(day)
             and r.get("status") != "not_sent"  # never reached the broker (lost in a restart): retry now
             and "quantity-precision-mismatch" not in (r.get("error") or "")}  # retried at fewer decimals
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
        d = 10 ** min(sc.get("qty_decimals", cfg["active"]["qty_decimals"]), (precision or {}).get(tk, 8))
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
    ftype = sc.get("fund_type", "screen_fund")  # buyback_value reuses this with its own type and name
    if any((r.get("signal") or {}).get("type") == ftype and r.get("ts", "").startswith(day)
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
            f"{sc.get('name', NAME)} funding: sell VWRP to buy its basket (needs £{need:.2f}, free cash £{free:.2f})",
            {"type": ftype, "strategy": sc.get("name", NAME), "need_gbp": round(need, 2), "quote": q})


# ------------------------------------------------------------ continuous watch (owner 3 Nov: "on all of the time")
# Rules from the research thread (Q200/Q201: interim selling on ranks, gate breaks or a 25% crash guard all did worse
# than holding to January). Only hard SEC events sell; everything else is an alert for the daily brief.
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
HARD_ITEMS = {"1.03": "bankruptcy", "3.01": "delisting notice", "4.01": "auditor change",
              "4.02": "non-reliance on past financials"}
HARD_FORMS = {"25-NSE": "delisting", "25": "delisting", "15-12B": "deregistration", "15-12G": "deregistration",
              "DEFM14A": "merger vote", "PREM14A": "merger proxy", "SC TO-T": "tender offer", "SC 14D9": "tender offer"}
PERIODIC = {"10-Q", "10-K", "10-Q/A", "10-K/A"}


def recent_filings(sub: dict) -> list[dict]:
    """[{form, date, adsh, items}] from an EDGAR submissions reply, newest first."""
    r = (sub.get("filings") or {}).get("recent") or {}
    forms = r.get("form") or []
    return [{"form": f, "date": (r.get("filingDate") or [""] * len(forms))[i],
             "adsh": (r.get("accessionNumber") or [""] * len(forms))[i],
             "items": (r.get("items") or [""] * len(forms))[i] or ""} for i, f in enumerate(forms)]


def classify(f: dict) -> tuple[str, str] | None:
    """('exit', why) for a hard event, ('alert', why) for a filing to look at, or None."""
    if f["form"] in HARD_FORMS:
        return "exit", f"sec_{HARD_FORMS[f['form']].replace(' ', '_')}"
    if f["form"].startswith("8-K"):
        items = {i.strip() for i in f["items"].split(",") if i.strip()}
        hard = sorted(items & set(HARD_ITEMS))
        if hard:
            return "exit", "sec_8k_" + "_".join(HARD_ITEMS[i].replace(" ", "_") for i in hard)
        return "alert", f"8-K items {f['items'] or 'none listed'}"
    if f["form"] in PERIODIC:
        return "alert", f"new {f['form']}: re-check the screen gates (gross profitability, FCF yield, leverage, buybacks)"
    return None


def watch_filings(held: dict[str, dict], subs: dict[str, dict], state: dict) -> tuple[dict, list[dict]]:
    """Scan each held name's filings since its entry day. `held` = {ticker: {cik, since}}; `subs` = {ticker:
    submissions JSON}. Returns (new state, new findings [{ticker, kind, why, form, date, adsh}]); each filing is
    reported once (state["seen"])."""
    seen = dict(state.get("seen") or {})
    exits = dict(state.get("exit") or {})
    out = []
    for tk, h in held.items():
        for f in recent_filings(subs.get(tk) or {}):
            if f["date"] < h["since"] or f["adsh"] in seen:
                continue
            seen[f["adsh"]] = tk
            c = classify(f)
            if not c:
                continue
            row = {"ticker": tk, "kind": c[0], "why": c[1], "form": f["form"], "date": f["date"], "adsh": f["adsh"],
                   "items": f["items"]}
            out.append(row)
            if c[0] == "exit" and tk not in exits:
                exits[tk] = {"why": c[1], "form": f["form"], "date": f["date"], "adsh": f["adsh"]}
    return {**state, "seen": seen, "exit": exits}, out


def price_alerts(held: dict[str, dict], quote_of, state: dict, drop: float) -> tuple[dict, list[dict]]:
    """An alert (once per name) when a held name is `drop` or more below its entry price; no trade."""
    done = dict(state.get("drop_alerted") or {})
    out = []
    for tk, h in held.items():
        q = quote_of(tk)
        if not q or tk in done or not h.get("entry_px"):
            continue
        r = q["price"] / h["entry_px"] - 1
        if r <= -drop:
            done[tk] = round(r, 4)
            out.append({"ticker": tk, "kind": "alert", "why": f"{r:+.1%} below entry ({h['entry_px']} -> {q['price']})"})
    return {**state, "drop_alerted": done}, out

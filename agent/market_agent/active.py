"""The active satellite sleeve (decision C6): short-term trades on a watchlist, each tagged with a named strategy
and the rule that fired, decided before entry.

Every entry carries its own hard stop, take-profit and time stop. Strategies are judged only on forward trades:
after `kill_after_trades` closed trades, a strategy whose average net return is at or below VWRP's over the same
holding periods is switched off automatically and the reason recorded. Nothing here sends an order; it returns
candidate orders for the agent, which puts each one through the risk gate.
"""
from __future__ import annotations

import math

from . import execution


def trades(records: list[dict]) -> list[dict]:
    """Pair filled entries with filled exits from the intent journal: [{entry, exit|None}] oldest first."""
    li = execution.latest_intents(records)
    entries = [r for r in li.values() if (r.get("signal") or {}).get("type") == "active_entry" and r["status"] == "filled"]
    exits = {(r.get("signal") or {}).get("entry_id"): r for r in li.values()
             if (r.get("signal") or {}).get("type") == "active_exit" and r["status"] == "filled"}
    return [{"entry": e, "exit": exits.get(e["id"])} for e in sorted(entries, key=lambda r: r.get("t", 0))]


def _fill(rec: dict) -> tuple[float, float]:
    """(net GBP, fees GBP) of a filled intent, from the broker's own fill record."""
    w = ((rec.get("broker") or {}).get("fill") or {}).get("walletImpact") or {}
    fees = -sum(float(t.get("quantity") or 0) for t in w.get("taxes") or [])
    return abs(float(w.get("netValue") or rec.get("value_gbp") or 0)), fees


def closed_result(t: dict) -> dict:
    """Net P&L after fees, and VWRP's return over the same holding period, for a closed trade."""
    e_net, e_fee = _fill(t["entry"])
    x_net, x_fee = _fill(t["exit"])
    pnl = x_net - e_net - e_fee - x_fee
    v0 = (t["entry"].get("signal") or {}).get("vwrp_px")
    v1 = (t["exit"].get("signal") or {}).get("vwrp_px")
    return {"pnl_gbp": pnl, "ret": pnl / e_net if e_net else 0.0,
            "vwrp_ret": (v1 / v0 - 1) if v0 and v1 else 0.0}


def strategy_scores(records: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for t in trades(records):
        if not t["exit"]:
            continue
        s = t["entry"]["signal"]["strategy"]
        r = closed_result(t)
        d = out.setdefault(s, {"n": 0, "ret": 0.0, "vwrp_ret": 0.0, "pnl_gbp": 0.0})
        d["n"] += 1
        d["ret"] += r["ret"]
        d["vwrp_ret"] += r["vwrp_ret"]
        d["pnl_gbp"] += r["pnl_gbp"]
    for d in out.values():
        d["avg_ret"], d["avg_vwrp_ret"] = d["ret"] / d["n"], d["vwrp_ret"] / d["n"]
    return out


def exit_orders(records, positions, quote_of, now, vwrp_px) -> list[tuple]:
    """Stop-loss, take-profit and time-stop exits for open trades whose price is validated."""
    out = []
    for t in trades(records):
        if t["exit"]:
            continue
        e = t["entry"]
        sig, tk = e["signal"], e["ticker"]
        p = positions.get(tk)
        if not p:
            continue
        avail = float(p.get("quantityAvailableForTrading") or 0)
        q = quote_of(tk)
        if avail <= 0 or not q:
            continue
        ret = q["price"] / sig["entry_px"] - 1
        why = ("stop" if ret <= -sig["stop"] else "take_profit" if ret >= sig["take_profit"]
               else "time" if now - e.get("t", now) >= sig["time_stop_s"] else None)
        if why:
            v = float((p.get("walletImpact") or {}).get("currentValue") or 0)
            out.append((tk, -avail, v, float(p.get("currentPrice") or 0), True,
                        f"active exit ({why}): {sig['strategy']} {ret:+.1%} since entry",
                        {"type": "active_exit", "entry_id": e["id"], "strategy": sig["strategy"], "why": why,
                         "ret": round(ret, 4), "quote": q, "vwrp_px": vwrp_px}))
    return out


def sleeve_pnl(records, positions, day: str) -> tuple[float, float]:
    """(today's active P&L, cumulative active P&L) in GBP: closed trades net of fees plus open trades marked to the
    broker's current value."""
    today = total = 0.0
    for t in trades(records):
        if t["exit"]:
            r = closed_result(t)["pnl_gbp"]
            total += r
            if t["exit"].get("ts", "").startswith(day):
                today += r
        else:
            p = positions.get(t["entry"]["ticker"]) or {}
            e_net, e_fee = _fill(t["entry"])
            u = float((p.get("walletImpact") or {}).get("currentValue") or e_net) - e_net - e_fee
            total += u
            today += u
    return today, total


def entry_orders(cfg, records, positions, quote_of, fx, total, cash, day, now, vwrp_px, disabled) -> tuple[list, list]:
    """Candidate entries, at most one per ticker per day, sized at `entry_weight` of the book. Returns
    (orders, notes)."""
    a = cfg["active"]
    notes: list[str] = []
    today_pnl, cum_pnl = sleeve_pnl(records, positions, day)
    if today_pnl <= -a["daily_loss_stop"] * total:
        return [], [f"active: no entries today, sleeve P&L £{today_pnl:.2f} hit the daily stop"]
    if cum_pnl <= -a["freeze_loss"] * a["sleeve_start_gbp"]:
        return [], [f"active: FROZEN, cumulative P&L £{cum_pnl:.2f} is {a['freeze_loss']:.0%} of the sleeve start"]
    open_tk = {t["entry"]["ticker"] for t in trades(records) if not t["exit"]}
    tried = {r["ticker"] for r in execution.latest_intents(records).values()
             if (r.get("signal") or {}).get("type") == "active_entry" and r.get("ts", "").startswith(day)}
    size = a["entry_weight"] * total
    reserve = 1 + cfg["core"].get("buy_reserve", 0)
    out = []
    for tk in a["watchlist"]:
        if tk in open_tk or tk in tried or tk in positions:
            continue
        q = quote_of(tk)
        if not q or not q.get("prev_close") or not fx:
            continue
        move = q["price"] / q["prev_close"] - 1
        for name, s in a["strategies"].items():
            if name in disabled:
                continue
            hit = move <= s["trigger_move"] if s["trigger_move"] < 0 else move >= s["trigger_move"]
            if not hit:
                continue
            if cash < size * reserve:
                notes.append(f"active: {name} fired on {tk} ({move:+.1%}) but cash £{cash:.2f} < £{size * reserve:.2f}")
                break
            px_gbp = q["price"] / fx
            qty = math.floor(size / px_gbp * 10 ** a["qty_decimals"]) / 10 ** a["qty_decimals"]
            if qty <= 0:
                break
            out.append((tk, qty, qty * px_gbp, q["price"], True,
                        f"active entry: {name} ({s['rule']}); day move {move:+.1%}",
                        {"type": "active_entry", "strategy": name, "rule": s["rule"], "move": round(move, 4),
                         "entry_px": q["price"], "stop": s["stop_loss"], "take_profit": s["take_profit"],
                         "time_stop_s": s["time_stop_days"] * 86400, "quote": q, "vwrp_px": vwrp_px}))
            break
    return out, notes


def kill_check(scores: dict, cfg: dict, disabled: dict, ts: str) -> dict:
    """Disable every strategy whose forward record, after enough trades, does not beat VWRP. Returns new entries."""
    new = {}
    n = cfg["active"]["kill_after_trades"]
    for name, d in scores.items():
        if name not in disabled and d["n"] >= n and d["avg_ret"] <= d["avg_vwrp_ret"]:
            new[name] = {"ts": ts, "why": f"{d['n']} trades: average {d['avg_ret']:+.2%} vs VWRP "
                                           f"{d['avg_vwrp_ret']:+.2%} over the same holding periods", "score": d}
    return new

"""agent-1.23 self-check: the standing promises about the book, tested on every broker pass.

Why this exists: on 11 Nov 2026 the owner, not the system, noticed that six holdings had no stop. Each feature had its
own tests, but nothing checked the book as a whole against what the system says about itself. This module does. It
never trades and never changes a strategy; it reads the broker's positions and order book and the agent's own journal,
and reports every promise that does not hold.

The promises (code: meaning):

  unprotected      every open trade with a stop rule has a stop RESTING AT THE BROKER for its whole position
                   (the broker's order book is the evidence, not stops.json)
  orphan_position  every holding is the VWRP core, a listed exit, or belongs to an open trade
  ghost_trade      every open trade has a position at the broker
  stray_order      every order resting at the broker is one the agent knows about
  overdue_exit     no trade is still open more than an hour of market time past its time limit
  no_exit_rule     every open trade has a rule that ends it: a stop, a time limit, or a named strategy exit
  overdue_refresh  no stock_screen name is held past its 12-month hold plus a month's grace
  weight_cap       no single name is more than 1.25x the single-name cap
  unpriced         every holding has a validated price while its market is open

Severity grows with how long a breach has lasted while something could have been done about it (market-open time for
the checks that need an open market, wall-clock time for the rest), so the few minutes between a fill and its stop
never raise an alarm, and a breach that persists always does:

  info      seen, inside its grace period (recorded, no alert)
  warn      past its grace period
  critical  an unprotected holding past its grace period, or any breach lasting over a day of its clock

`check` is pure: same inputs, same report. `seen` (from the last report) carries each breach's clock forward.
"""
from __future__ import annotations

import time

from . import active, execution

MAX_STEP_S = 900.0          # the most one pass may add to a breach's clock (agent downtime is not counted as breach time)
DAY_S = 86400.0
GRACE = {                   # code -> (clock, seconds before `warn`)
    "unprotected": ("open", 1800.0),
    "orphan_position": ("open", 3600.0),
    "ghost_trade": ("wall", 1800.0),
    "stray_order": ("wall", 900.0),
    "overdue_exit": ("open", 3600.0),
    "no_exit_rule": ("wall", 0.0),
    "overdue_refresh": ("wall", 0.0),
    "weight_cap": ("wall", 3600.0),
    "unpriced": ("open", 1800.0),
}
CRITICAL_AT_WARN = {"unprotected"}   # these are critical as soon as their grace has passed
# Strategies whose exit is a rule in code rather than a stop or a time limit on the trade itself.
RULE_EXIT = {"stock_screen": "replaced by the monthly refresh after its 12-month hold, or sold on a hard SEC event",
             "merger_arb": "exits when the deal closes or is terminated"}
SCREEN_HOLD_S = 365 * DAY_S
SCREEN_GRACE_S = 31 * DAY_S
MERGER_GONE_S = 2 * DAY_S    # merger_arb books a cash-out a day after the shares leave; allow two


def _ts(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _qty(p: dict | None) -> float:
    return float((p or {}).get("quantity") or 0)


def check(*, now: float, cfg: dict, positions: dict, pending: list, records: list, stops: dict, market_open,
          quote_ok, total: float, seen: dict | None = None, watch: set | None = None) -> dict:
    """The invariants report: {ts, t, ok, counts, checked, violations: [{code, severity, ticker, text, since,
    clock_s}], seen}. `market_open(ticker)` and `quote_ok(ticker)` are the agent's own; `seen` is the previous
    report's `seen`; `watch` is the set of tickers the active strategies may hold (a holding outside it, the core and
    the exits list is an orphan)."""
    seen = seen or {}
    a = cfg.get("active") or {}
    bench = cfg["benchmark"]["t212"]
    exits = set((cfg.get("exits") or {}).get("tickers") or [])
    disaster = a.get("disaster_stop")
    opens = active.open_trades(records)
    by_ticker: dict[str, list] = {}
    for e in opens:
        by_ticker.setdefault(e["ticker"], []).append(e)
    live = {execution._hid(p) for p in pending}
    found: list[dict] = []

    def add(code: str, ticker: str | None, text: str, **extra) -> None:
        found.append({"code": code, "ticker": ticker, "text": text, **extra})

    # unprotected: the broker's order book decides
    for u in active.unprotected(records, positions, stops, live, disaster):
        add("unprotected", u["ticker"], f"{u['ticker']} ({u['strategy']}) has no broker stop for its whole position: "
            f"{u['why']}", entry_id=u["entry_id"])

    # orphan positions and ghost trades
    for t, p in positions.items():
        if t == bench or t in exits or t in by_ticker or _qty(p) <= 0:
            continue
        pies = float(p.get("quantityInPies") or 0)
        where = "inside a pie, which the API cannot sell" if pies and pies >= _qty(p) - 1e-9 else \
            "not the core, not a listed exit and not part of any open trade"
        add("orphan_position", t, f"{t} is held but {where}")
    for e in opens:
        if _qty(positions.get(e["ticker"])) > 0:
            continue
        strat = e["signal"].get("strategy")
        add("ghost_trade", e["ticker"], f"{e['ticker']} ({strat}) is an open trade in the journal but the broker "
            "shows no position", entry_id=e["id"], grace=MERGER_GONE_S if strat == "merger_arb" else None)

    # stray orders
    known = {v.get("order_id") for v in stops.values() if v.get("order_id")}
    known |= {r.get("order_id") for r in execution.unresolved(records) if r.get("order_id")}
    for p in pending:
        oid = execution._hid(p)
        if oid not in known:
            t = execution._pending_ticker(p)
            add("stray_order", t, f"the broker shows order {oid} on {t} that is neither a known stop nor an order in "
                "progress")

    # exits: overdue, missing, or a screen name past its hold
    for e in opens:
        sig, t = e["signal"], e["ticker"]
        if _qty(positions.get(t)) <= 0:
            continue
        strat = str(sig.get("strategy") or "")
        age = now - float(e.get("t") or now)
        ts = sig.get("time_stop_s")
        if ts is not None and age > ts:
            add("overdue_exit", t, f"{t} ({strat}) is {(age - ts) / DAY_S:.1f} days past its time limit and still "
                "held", entry_id=e["id"])
        level, _ = active.stop_level(sig, disaster)
        if level is None and ts is None and strat not in RULE_EXIT:
            add("no_exit_rule", t, f"{t} ({strat}) has no stop, no time limit and no strategy exit: nothing would "
                "ever sell it", entry_id=e["id"])
        if strat == "stock_screen" and age > SCREEN_HOLD_S + SCREEN_GRACE_S:
            add("overdue_refresh", t, f"{t} (stock_screen) has been held {age / DAY_S:.0f} days: the monthly refresh "
                "that replaces names after 12 months has not run", entry_id=e["id"])

    # weights and prices
    cap = (cfg.get("limits") or {}).get("max_name_weight")
    exempt = set((cfg.get("limits") or {}).get("cap_exempt") or [])
    for t, p in positions.items():
        v = float((p.get("walletImpact") or {}).get("currentValue") or 0)
        if cap and total > 0 and t not in exempt and v / total > cap * 1.25:
            add("weight_cap", t, f"{t} is {v / total:.1%} of the book, over 1.25x the {cap:.0%} single-name cap")
        if _qty(p) > 0 and market_open(t) and not quote_ok(t):
            add("unpriced", t, f"{t} is held but has no validated price while its market is open: stops and exits "
                "that need a price cannot fire")

    # clocks and severity
    new_seen: dict[str, dict] = {}
    out = []
    for v in found:
        code, t = v["code"], v["ticker"]
        key = f"{code}:{t}:{v.get('entry_id') or ''}"
        clock, grace = GRACE[code]
        grace = v.pop("grace", None) or grace
        prev = seen.get(key)
        step = min(max(now - prev["last"], 0.0), MAX_STEP_S) if prev else 0.0
        ticking = clock == "wall" or (t is not None and market_open(t))
        used = (prev["clock_s"] if prev else 0.0) + (step if ticking else 0.0)
        first = prev["first"] if prev else now
        new_seen[key] = {"first": first, "last": now, "clock_s": round(used, 1)}
        sev = "info" if used < grace else "critical" if code in CRITICAL_AT_WARN or used >= grace + DAY_S else "warn"
        out.append({**v, "severity": sev, "since": _ts(first), "clock_s": round(used, 1)})
    order = {"critical": 0, "warn": 1, "info": 2}
    out.sort(key=lambda v: (order[v["severity"]], v["code"], v["ticker"] or ""))
    counts = {s: sum(1 for v in out if v["severity"] == s) for s in ("critical", "warn", "info")}
    need = [e for e in opens if _qty(positions.get(e["ticker"])) > 0 and active.stop_level(e["signal"], disaster)[0] is not None]
    return {"ts": _ts(now), "t": now, "ok": not counts["critical"] and not counts["warn"], "counts": counts,
            "checked": {"positions": len(positions), "open_trades": len(opens), "need_stop": len(need),
                        "stops_resting": len(need) - sum(1 for v in out if v["code"] == "unprotected"),
                        "pending_orders": len(pending)},
            "violations": out, "seen": new_seen}


def verdict(rep: dict | None, now: float, max_age_s: float = 1800.0) -> tuple[int, str]:
    """(exit code, one line) for a stored report: 0 all promises hold, 1 warnings, 2 critical, missing or stale."""
    if not rep:
        return 2, "no invariants report: the self-check has not run"
    age = now - float(rep.get("t") or 0)
    if age > max_age_s:
        return 2, f"invariants report is {age / 60:.0f} min old: the self-check is not running"
    c, k = rep.get("counts") or {}, rep.get("checked") or {}
    line = (f"{k.get('stops_resting')}/{k.get('need_stop')} holdings that need a stop have one resting at the broker; "
            f"{c.get('critical', 0)} critical, {c.get('warn', 0)} warnings, {c.get('info', 0)} settling")
    return (2 if c.get("critical") else 1 if c.get("warn") else 0), line

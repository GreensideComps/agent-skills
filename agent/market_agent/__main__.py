"""python3 -m market_agent run | status | audit | rules | uptime [--hours H] | halt REASON | resume REASON

run     start the loop (one instance per state directory, enforced by a lease)
status  print the heartbeat and a health verdict; exit 0 healthy, 1 degraded, 2 down
audit   print the last self-check (state/invariants.json): exit 0 every promise holds, 1 warnings, 2 critical or stale
rules   print every strategy's live buy and sell rules in plain English, built from config.json and the code
        (--write FILE saves it, --check FILE exits 1 if FILE is out of date)
uptime  measured from the event log: the share of minutes in the window with a heartbeat, and every gap over 3 min
halt    kill switch: stop all order sending at once (the loop keeps monitoring)
resume  allow order sending again
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_STATE = Path(os.environ.get("MARKET_AGENT_STATE", "/mnt/project-files/market-agent/state"))


def health(hb: dict | None, now: float) -> tuple[int, str]:
    if not hb:
        return 2, "down: no heartbeat file"
    age = now - float(hb.get("t", 0))
    if age > 300:
        return 2, f"down: last heartbeat {age:.0f} s ago"
    ages = hb.get("duty_age_s") or {}
    stale = [k for k, lim in (("prices", 600), ("broker", 1200)) if ages.get(k, 10 ** 9) > lim]
    inv = hb.get("invariants") or {}
    if stale or hb.get("duty_failures") or hb.get("consecutive_order_errors") or inv.get("critical"):
        return 1, (f"degraded: stale {stale}, failures {hb.get('duty_failures')}, "
                   f"self-check critical {inv.get('critical', 0)}")
    return 0, f"healthy: heartbeat {age:.0f} s ago, up {hb.get('up_s')} s, {hb.get('loops')} loops"


def uptime(store, now: float, hours: float) -> dict:
    start = now - hours * 3600
    days = sorted({time.strftime("%Y-%m-%d", time.gmtime(t)) for t in range(int(start), int(now) + 86400, 86400)})
    beats = sorted(e["t"] for d in days for e in store.events(d) if e["kind"] == "heartbeat" and start <= e["t"] <= now)
    if not beats:
        return {"window_h": hours, "heartbeats": 0, "uptime": 0.0, "gaps": []}
    first = beats[0]
    gaps, prev = [], first
    for t in beats[1:] + [now]:
        if t - prev > 180:
            gaps.append({"from": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(prev)), "minutes": round((t - prev) / 60, 1)})
        prev = t
    covered_from = max(start, first)
    down = sum(g["minutes"] * 60 for g in gaps)
    return {"window_h": hours, "measured_from": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(covered_from)),
            "heartbeats": len(beats), "uptime": round(1 - down / max(now - covered_from, 1), 4), "gaps": gaps}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="market_agent")
    ap.add_argument("--state", default=str(DEFAULT_STATE))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    sub.add_parser("status")
    sub.add_parser("audit").add_argument("--max-age", type=float, default=1800.0)
    ru = sub.add_parser("rules")
    ru.add_argument("--write")
    ru.add_argument("--check")
    sub.add_parser("uptime").add_argument("--hours", type=float, default=24.0)
    for c in ("halt", "resume"):
        sub.add_parser(c).add_argument("reason")
    sr = sub.add_parser("screen-refresh")  # Q214 1/12 refresh, run weekly: prints the swap
    sr.add_argument("scored_csv")
    sr.add_argument("--month", help="YYYY-MM: apply the one-scheduled-swap-a-month budget from screen_refresh.json")
    sr.add_argument("--record", action="store_true", help="record this month's swap as used (after the config edit)")
    a = ap.parse_args(argv)
    from .store import LeaseHeld, Store
    store = Store(Path(a.state))
    if a.cmd == "status":
        hb = store.read("heartbeat.json")
        code, text = health(hb, time.time())
        print(json.dumps({"verdict": text, "heartbeat": hb}, indent=1, default=str))
        return code
    if a.cmd == "audit":
        from . import invariants  # noqa: PLC0415
        rep = store.read("invariants.json")
        code, line = invariants.verdict(rep, time.time(), a.max_age)
        print(json.dumps({"verdict": line, "report": {k: v for k, v in (rep or {}).items() if k != "seen"}}, indent=1))
        return code
    if a.cmd == "rules":
        from . import rules  # noqa: PLC0415
        from .agent import load_config  # noqa: PLC0415
        cfg = load_config()
        text = rules.render(cfg)  # the saved page is built from config alone, so it is the same on every machine
        if a.check:
            ok = Path(a.check).exists() and Path(a.check).read_text() == text
            print("up to date" if ok else f"{a.check} is out of date: run python3 -m market_agent rules --write {a.check}")
            return 0 if ok else 1
        if a.write:
            Path(a.write).write_text(text)
        else:  # printed live: also shows what the kill rule or the office has switched off (state/strategies.json)
            print(rules.render(cfg, store.read("strategies.json")))
        return 0
    if a.cmd == "uptime":
        print(json.dumps(uptime(store, time.time(), a.hours), indent=1))
        return 0
    if a.cmd == "screen-refresh":
        import csv  # noqa: PLC0415
        from . import stock_screen  # noqa: PLC0415
        from .agent import load_config  # noqa: PLC0415
        sc = {**load_config()["active"]["stock_screen"], "_state": store.read("stock_screen.json") or {}}
        with open(a.scored_csv) as fh:
            scored = list(csv.DictReader(fh))
        log = store.read("screen_refresh.json") or {}
        used = bool(a.month and (log.get("swaps") or {}).get(a.month))
        out = stock_screen.monthly_refresh(sc, scored, store.intents(), sc.get("refresh_top_n", 15),
                                           sc.get("max_per_sic2", 3), swapped_this_month=used)
        if a.record and a.month and out["action"] == "swap" and out["sell"] and not used:
            store._replace("screen_refresh.json", {**log, "swaps": {**(log.get("swaps") or {}), a.month: {
                "sell": out["sell"], "buy": [r.get("ticker") or r.get("cik") for r in out["buy"]],
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}})
        print(json.dumps(out, indent=1))
        return 0
    if a.cmd in ("halt", "resume"):
        store.set_control(a.cmd == "resume", a.reason, by=os.environ.get("USER", "cli"))
        print(json.dumps(store.control()))
        return 0
    sys.path.insert(0, str(REPO / "trading"))
    from t212bot.client import AmbiguousOrderError, ApiError, T212Client  # noqa: PLC0415
    from t212bot.config import load_credentials  # noqa: PLC0415 - refuses anything but T212_ENV=demo
    from .agent import Agent, load_config
    agent = Agent(store, T212Client(load_credentials()), load_config(), ambiguous_exc=AmbiguousOrderError,
                  api_exc=ApiError)
    from . import datasrc  # noqa: PLC0415 - agent-1.21: Tiingo, CBOE and broker prices instead of Yahoo/Nasdaq
    agent.data = datasrc.Honest(store.root, agent.broker_quotes)
    agent.get = agent.data.get
    try:
        agent.run_forever()
    except LeaseHeld as e:
        print("LEASE HELD:", e, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""python3 -m market_agent run | status | uptime [--hours H] | halt REASON | resume REASON

run     start the loop (one instance per state directory, enforced by a lease)
status  print the heartbeat and a health verdict; exit 0 healthy, 1 degraded, 2 down
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
    if stale or hb.get("duty_failures") or hb.get("consecutive_order_errors"):
        return 1, f"degraded: stale {stale}, failures {hb.get('duty_failures')}"
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
    sub.add_parser("uptime").add_argument("--hours", type=float, default=24.0)
    for c in ("halt", "resume"):
        sub.add_parser(c).add_argument("reason")
    a = ap.parse_args(argv)
    from .store import LeaseHeld, Store
    store = Store(Path(a.state))
    if a.cmd == "status":
        hb = store.read("heartbeat.json")
        code, text = health(hb, time.time())
        print(json.dumps({"verdict": text, "heartbeat": hb}, indent=1, default=str))
        return code
    if a.cmd == "uptime":
        print(json.dumps(uptime(store, time.time(), a.hours), indent=1))
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
    try:
        agent.run_forever()
    except LeaseHeld as e:
        print("LEASE HELD:", e, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

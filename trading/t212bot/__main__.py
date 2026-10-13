"""Command line entry point.

    python -m t212bot status              account, positions, dry-run plan (no orders)
    python -m t212bot run                 snapshot + reconcile + plan (dry run, no orders)
    python -m t212bot run --execute       ... and place orders if a rebalance is due
    python -m t212bot run --execute --force   rebalance to target now
    python -m t212bot reconcile           match placed orders to fills
    python -m t212bot report              write PERFORMANCE.md (real vs shadow portfolios)

Run from the trading/ directory. Demo account only (see README.md).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from .client import T212Client
from .config import SafetyError, load_credentials, load_strategy
from .executor import Bot
from .journal import Journal


def _fmt_plan(plan) -> str:
    lines = [f"total £{plan.total_value_gbp:.2f}  cash £{plan.cash_gbp:.2f}  rebalance needed: {plan.needs_rebalance}"]
    for r in plan.reasons:
        lines.append(f"  reason: {r}")
    for t in sorted(plan.target_weights):
        lines.append(f"  {t:10s} now {plan.current_weights[t]:6.1%}  target {plan.target_weights[t]:6.1%}  drift {plan.drift[t]:+6.1%}")
    for o in plan.orders:
        lines.append(f"  ORDER {o.side:4s} {o.ticker:10s} qty {o.quantity:+.4f}  ≈£{o.est_value_gbp:.2f} @ £{o.price_gbp:.4f}  ({o.reason})")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="t212bot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    r = sub.add_parser("run")
    r.add_argument("--execute", action="store_true", help="place orders if a rebalance is due (demo only)")
    r.add_argument("--force", action="store_true", help="rebalance to target even if no trigger fired")
    sub.add_parser("reconcile")
    sub.add_parser("report")
    a = ap.parse_args(argv)

    cfg = load_strategy()
    j = Journal()
    if a.cmd == "report":
        from . import report
        data = report.build(j, cfg)
        print(report.write(data))
        return 0
    try:
        client = T212Client(load_credentials())
    except SafetyError as e:
        print(f"SAFETY: {e}", file=sys.stderr)
        return 2
    bot = Bot(client, cfg, j)
    if a.cmd == "reconcile":
        print(json.dumps(bot.reconcile(), indent=1, default=str))
        return 0
    try:
        res = bot.run(execute=False) if a.cmd == "status" else bot.run(execute=a.execute, force=a.force)
    except Exception as e:  # journal every failure, then fail loudly
        j.event("run_failed", error_type=type(e).__name__, error=str(e)[:800])
        print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(f"status: {res['status']}" + (f" ({res.get('reason')})" if res.get("reason") else ""))
    if "plan" in res:
        print(_fmt_plan(res["plan"]))
    for k in ("placed", "reconciled"):
        if res.get(k):
            print(k + ":", json.dumps(res[k], indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

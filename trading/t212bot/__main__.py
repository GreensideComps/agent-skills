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
    d = sub.add_parser("daily-report", help="generate the daily intelligence report (read-only)")
    d.add_argument("--send", action="store_true", help="email it (REPORT_EMAIL_* env vars)")
    d.add_argument("--force", action="store_true", help="send even if already delivered today")
    d.add_argument("--respect-schedule", action="store_true", help="only run if the UK-local report time has passed and today's report is not yet delivered")
    d.add_argument("--sample", action="store_true", help="render the EXAMPLE-DATA sample report (no API calls)")
    sub.add_parser("advise", help="print today's withdrawal recommendation (read-only)")
    sub.add_parser("email-check", help="validate email configuration without sending")
    vr = sub.add_parser("verify-report", help="re-fetch raw API data and independently check a stored report")
    vr.add_argument("--date", default=None)
    es = sub.add_parser("email-status", help="show the latest delivery and re-check it with the provider")
    es.add_argument("--kind", default="daily")
    a = ap.parse_args(argv)

    if a.cmd == "daily-report" and a.sample:
        return _sample()
    if a.cmd == "daily-report":
        from . import daily
        try:
            res = daily.run(send=a.send, force=a.force, respect_schedule=a.respect_schedule)
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        print(json.dumps({k: v for k, v in res.items() if k != "alerts"}, indent=1, default=str))
        for al in res.get("alerts", []):
            print(f"{al['level']}: {al['msg']}", file=sys.stderr)
        return res["exit"]
    if a.cmd == "advise":
        from . import daily
        res = daily.run(send=False)
        print(res["adviser"])
        return 0
    if a.cmd == "verify-report":
        from datetime import datetime, timezone
        from pathlib import Path
        from . import verify
        from .readonly import ReadOnlyClient
        root = Path(__file__).resolve().parent.parent
        mdir = root / "reports" / "metrics"
        date = a.date or max(p.stem for p in mdir.glob("20*.json"))
        M = json.loads((mdir / f"{date}.json").read_text())
        try:
            ro = ReadOnlyClient(T212Client(load_credentials()))
        except SafetyError as e:
            print(f"SAFETY: {e}", file=sys.stderr)
            return 2
        raw = {"summary": ro.account_summary(), "positions": ro.positions(), "pending": ro.pending_orders(),
               "orders": ro.history_orders(limit=50, max_pages=5), "transactions": ro.history_transactions(),
               "dividends": ro.history_dividends()}
        fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = verify.verify(M, raw, verify.load_snapshots(root / "journal" / "snapshots.csv"))
        safety = verify.adviser_safety(root / "cache" / "t212_openapi.yaml")
        out = root / "reports" / "verification" / f"{date}-report-vs-account.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(verify.render(date, M, rows, safety, fetched))
        fails = [r for r in rows + safety if r["status"] == "FAIL"]
        print(f"{out}\n{'ALL CHECKS PASS' if not fails else str(len(fails)) + ' DISCREPANCIES'}")
        for r in fails:
            print(f"FAIL {r['check']}: report {r['report']} vs {r['independent']} {r['note']}", file=sys.stderr)
        return 0 if not fails else 2
    if a.cmd == "email-status":
        from . import emailer
        last = emailer.last_delivery(kind=a.kind)
        if not last:
            print("no delivery recorded")
            return 3
        cfg = emailer.load_config()
        if last["status"] in ("sent", "unconfirmed") and last.get("provider_id") and cfg.provider == "resend" and not cfg.problems():
            res = emailer.DeliveryResult("sent", "resend", "", 0, last["key"], last["provider_id"])
            last = emailer.confirm_delivery(res, cfg, last["report_date"], a.kind, polls=1)
        print(json.dumps({k: last.get(k) for k in ("report_date", "status", "provider", "provider_id", "provider_event", "ts_utc", "detail")}, indent=1))
        return 0 if last["status"] == "confirmed_delivered" else 3
    if a.cmd == "email-check":
        from . import emailer
        cfg = emailer.load_config()
        probs = cfg.problems()
        print(repr(cfg))
        if cfg.provider == "outbox":
            print("NOT CONFIGURED FOR DELIVERY: provider is 'outbox' - reports are written to trading/reports/outbox/ and NOT emailed. "
                  "Set REPORT_EMAIL_PROVIDER=resend (or smtp) and its variables; see trading/REPORTING.md.")
            return 3
        print("OK - configuration complete (this does not prove delivery; run `daily-report --send --force` and check your inbox)"
              if not probs else "PROBLEMS: " + "; ".join(probs))
        return 0 if not probs else 3

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


def _sample() -> int:
    from datetime import datetime, timezone
    from . import intel, sample
    from .config import load_strategy
    import json as _j
    now = datetime.now(timezone.utc)
    S = sample.sample_inputs(now)
    acfg = _j.loads((intel.ROOT / "config" / "adviser.json").read_text())
    M, _ = intel.compute(S["acct"], S["snaps"], S["events"], load_strategy().name, acfg, {}, intel.research_bundle(),
                         S["market"], S["prev"], S["delivery"], now, example=True)
    M["meta"]["report_date"] = "SAMPLE"
    paths = intel.store(M, name="SAMPLE_daily_report")
    print(paths["md"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

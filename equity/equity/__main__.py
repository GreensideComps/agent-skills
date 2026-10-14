"""Company research database CLI. Run from the `equity/` directory: python3 -m equity <command>.

Broker access is read-only and used only by `sync-universe` (through the trading bot's
ReadOnlyClient, which cannot reach order methods). No other command needs broker credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

from . import index, pipeline
from .ingest import ingest_company, last_snapshot, latest_securities, resolve
from .jobs import JobSkipped, job, job_health
from .sec import SecClient, SecError
from .store import Store
from .universe import sync_security_master

TRADING_DIR = Path(__file__).resolve().parents[2] / "trading"
SECRET_ENV = ("T212_API_KEY", "T212_API_SECRET", "RESEND_API_KEY")


def _secrets() -> list[str]:
    return [os.environ.get(k, "") for k in SECRET_ENV]


def _t212_instruments() -> list[dict]:
    sys.path.insert(0, str(TRADING_DIR))
    from t212bot.client import T212Client  # noqa: PLC0415
    from t212bot.config import load_credentials  # noqa: PLC0415
    from t212bot.readonly import ReadOnlyClient  # noqa: PLC0415
    return ReadOnlyClient(T212Client(load_credentials())).instruments()


def cmd_sync_universe(store: Store, a) -> int:
    with job(store, "sync_universe", {"instruments_file": a.instruments}, redact=_secrets()) as j:
        instruments = json.loads(Path(a.instruments).read_text()) if a.instruments else _t212_instruments()
        scan = sync_security_master(store, instruments, SecClient().tickers())
        j["outputs"] = {k: scan[k] for k in ("stocks_in_master", "sec_linked_high", "added", "changed", "removed")}
    print(json.dumps({k: v for k, v in scan.items() if k != "rid"}, indent=1))
    return 0


def _targets(store: Store, a) -> list[dict]:
    if a.all_sec:
        seen, out = set(), []
        for s in latest_securities(store).values():
            if not s.get("absent") and s.get("sec_match") == "high" and s["company_id"] not in seen:
                seen.add(s["company_id"])
                out.append(s)
        out.sort(key=lambda s: s["symbol"])
        if a.random:
            import random  # noqa: PLC0415
            out = random.Random(a.seed).sample(out, min(a.random, len(out)))
        return out[: a.limit or None]
    out = []
    for sym in a.symbol or []:
        s = resolve(store, symbol=sym)
        if s is None:
            print(f"{sym}: not in the security master (run sync-universe)")
        else:
            out.append(s)
    return out


def cmd_ingest(store: Store, a) -> int:
    sec = SecClient()
    today = date.today().isoformat()
    written = unchanged = failed = skipped = 0
    for s in _targets(store, a):
        try:
            with job(store, "ingest_fundamentals", {"company_id": s["company_id"], "symbol": s["symbol"]},
                     idempotency_key=f"ingest:{s['company_id']}:{today}", force=a.force, redact=_secrets()) as j:
                snap, wrote = ingest_company(store, sec, s)
                j["outputs"] = {"written": wrote, "snapshot": snap["rid"], "confidence": snap["confidence"]}
        except JobSkipped:
            skipped += 1
            continue
        except (SecError, ValueError, KeyError) as e:
            failed += 1
            print(f"{s['symbol']}: FAILED {e}")
            continue
        written += wrote
        unchanged += not wrote
        sm = snap["summary"]
        print(f"{s['symbol']:<6} {snap['confidence']:<6} FY{sm.get('latest_fy_end')} "
              f"FCF/sh={_f(sm.get('fcf_per_share'))} ROIC={_p(sm.get('roic'))} "
              f"{'new snapshot' if wrote else 'unchanged'} flags={len(snap['flags'])}")
    print(f"written={written} unchanged={unchanged} skipped_already_done_today={skipped} failed={failed} "
          f"sec_requests={sec.requests_made}")
    return 1 if failed else 0


def _f(x):
    return "n/a" if x is None else f"{x:,.2f}"


def _p(x):
    return "n/a" if x is None else f"{x * 100:.1f}%"


def cmd_show(store: Store, a) -> int:
    s = resolve(store, symbol=a.symbol)
    if not s:
        print("not found")
        return 1
    print(json.dumps({k: s[k] for k in ("isin", "symbol", "t212_ticker", "name", "currency", "company_id",
                                         "cik", "sec_name", "sec_match")}, indent=1))
    print("status:", pipeline.current_status(store, s["company_id"]))
    for t in pipeline.history(store, s["company_id"]):
        print(f"  {t['ts_utc']} {t['from']} -> {t['to']}: {t['reason']} ({'; '.join(t['evidence'])})")
    snap = last_snapshot(store, s["company_id"])
    if not snap:
        print("no fundamentals snapshot")
        return 0
    print(f"snapshot {snap['rid']} retrieved {snap['retrieved_utc']} source {snap['source_url']}")
    print(f"confidence {snap['confidence']}; flags: {', '.join(snap['flags']) or 'none'}")
    for k, v in snap["summary"].items():
        print(f"  {k:<24} {v}")
    if a.provenance:
        last = snap["summary"].get("latest_fy_end")
        for m, v in snap["years"].get(last, {}).items():
            print(f"  {m:<18} {v['v']:>20,} {v['u']:<10} {v['c']} accn {v['a']} filed {v['f']} ({v['form']})")
    return 0


def cmd_discover(store: Store, a) -> int:
    s = resolve(store, symbol=a.symbol)
    if not s:
        print("not found")
        return 1
    rec = pipeline.discover(store, s["company_id"], s["name"], a.source, a.reason, a.evidence, a.actor,
                            {"isin": s["isin"], "symbol": s["symbol"]})
    print("already in pipeline" if rec is None else f"discovered {s['company_id']}")
    return 0


def cmd_status(store: Store, a) -> int:
    s = resolve(store, symbol=a.symbol)
    if not s:
        print("not found")
        return 1
    snap = last_snapshot(store, s["company_id"])
    gates = {"data_confidence": snap["confidence"] if snap else None,
             "bear_case_recorded": False}  # bear-case records arrive with the bear-case agent (milestone 3)
    try:
        t = pipeline.transition(store, s["company_id"], a.to, a.reason, a.evidence, a.actor, gates)
    except pipeline.TransitionError as e:
        print(f"REFUSED: {e}")
        return 2
    print(f"{t['company_id']}: {t['from']} -> {t['to']}")
    return 0


def cmd_search(store: Store, a) -> int:
    db = sqlite3.connect(index.build(store))
    db.row_factory = sqlite3.Row
    where, args = ["1=1"], []
    if a.status:
        where.append("c.status = ?"); args.append(a.status)  # noqa: E702
    if a.name:
        where.append("(c.name LIKE ? OR s.symbol = ?)"); args += [f"%{a.name}%", a.name.upper()]  # noqa: E702
    if a.min_roic is not None:
        where.append("c.roic >= ?"); args.append(a.min_roic)  # noqa: E702
    if a.min_fcf_margin is not None:
        where.append("c.fcf_margin >= ?"); args.append(a.min_fcf_margin)  # noqa: E702
    rows = db.execute(f"""SELECT c.* FROM companies c
                          LEFT JOIN securities s ON s.company_id = c.company_id AND s.absent = 0
                          WHERE {' AND '.join(where)} GROUP BY c.company_id
                          ORDER BY c.roic DESC NULLS LAST LIMIT ?""", args + [a.limit]).fetchall()
    for r in rows:
        print(f"{(r['symbol'] or ''):<6} {(r['name'] or '')[:30]:<30} {str(r['status']):<14} "
              f"{str(r['confidence']):<6} ROIC={_p(r['roic'])} FCFm={_p(r['fcf_margin'])} "
              f"FCF/sh 5y CAGR={_p(r['fcf_per_share_cagr_5y'])} FY{r['latest_fy_end']}")
    print(f"{len(rows)} rows")
    return 0


def cmd_crosscheck(store: Store, a) -> int:
    """Compare stored SEC figures with an independent provider; write a dated verification record."""
    import time  # noqa: PLC0415

    from .crosscheck import TOLERANCE, compare, fetch_yahoo  # noqa: PLC0415
    rows = []
    for sym in a.symbol:
        s = resolve(store, symbol=sym)
        snap = last_snapshot(store, s["company_id"]) if s else None
        if not snap:
            print(f"{sym}: no snapshot")
            continue
        try:
            y = fetch_yahoo(sym)
        except Exception as e:  # noqa: BLE001 - a check source failing is recorded, not fatal
            rows.append({"symbol": sym, "metric": "*", "status": f"yahoo_error: {type(e).__name__}"})
            continue
        rows += [{"symbol": sym, **r} for r in compare(snap, y)]
        time.sleep(0.5)
    from collections import Counter  # noqa: PLC0415
    counts = Counter(r["status"] for r in rows)
    out = Path(__file__).resolve().parent.parent / "reports" / "verification" / f"{date.today()}-sec-vs-yahoo.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# SEC-derived fundamentals vs Yahoo (independent check), {date.today()}", "",
             f"Latest fiscal year per company. Tolerance {TOLERANCE:.0%}. Neither source is assumed correct; "
             "a CONFLICT needs review. Yahoo is unofficial and used only as a check.", "",
             f"Result: {dict(counts)}", "",
             "| Symbol | Metric | FY end | SEC | Yahoo | Rel. diff | Status | SEC concept |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        diff = "" if r.get("rel_diff") is None else f"{r['rel_diff']:+.2%}"
        lines.append(f"| {r['symbol']} | {r['metric']} | {r.get('fy_end', '')} | {_n(r.get('sec'))} | "
                     f"{_n(r.get('yahoo'))} | {diff} | {r['status']} | {r.get('sec_concept') or ''} |")
    out.write_text("\n".join(lines) + "\n")
    print(dict(counts), "->", out)
    return 2 if counts.get("CONFLICT") else 0


def _n(x):
    return "" if x is None else f"{x:,.0f}"


def cmd_health(store: Store, a) -> int:
    h = job_health(store)
    scans = store.scans.read()
    print(json.dumps({"jobs": h, "last_universe_scan": scans[-1] if scans else None,
                      "fundamentals_snapshots": len(store.fundamentals.read()),
                      "companies_in_pipeline": len(pipeline.all_statuses(store))}, indent=1, default=str))
    return 2 if h["stuck"] or h["last_failed"] else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="equity")
    p.add_argument("--data", default=None, help="ledger directory (default equity/data)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync-universe"); s.add_argument("--instruments")  # noqa: E702
    s = sub.add_parser("ingest")
    s.add_argument("--symbol", action="append"); s.add_argument("--all-sec", action="store_true")  # noqa: E702
    s.add_argument("--limit", type=int, default=0); s.add_argument("--force", action="store_true")  # noqa: E702
    s.add_argument("--random", type=int, default=0, help="with --all-sec: a random sample of N companies")
    s.add_argument("--seed", type=int, default=0)
    s = sub.add_parser("show"); s.add_argument("symbol"); s.add_argument("--provenance", action="store_true")  # noqa: E702
    for name in ("discover", "status"):
        s = sub.add_parser(name)
        s.add_argument("symbol")
        if name == "status":
            s.add_argument("--to", required=True, choices=pipeline.STATUSES)
        else:
            s.add_argument("--source", required=True)
        s.add_argument("--reason", required=True)
        s.add_argument("--evidence", action="append", required=True)
        s.add_argument("--actor", default="owner")
    s = sub.add_parser("search")
    s.add_argument("--status"); s.add_argument("--name")  # noqa: E702
    s.add_argument("--min-roic", type=float); s.add_argument("--min-fcf-margin", type=float)  # noqa: E702
    s.add_argument("--limit", type=int, default=50)
    sub.add_parser("health")
    s = sub.add_parser("crosscheck"); s.add_argument("--symbol", action="append", required=True)  # noqa: E702
    a = p.parse_args(argv)
    store = Store(Path(a.data)) if a.data else Store()
    handler = {"sync-universe": cmd_sync_universe, "ingest": cmd_ingest, "show": cmd_show,
               "discover": cmd_discover, "status": cmd_status, "search": cmd_search, "health": cmd_health,
               "crosscheck": cmd_crosscheck}
    return handler[a.cmd](store, a)


if __name__ == "__main__":
    sys.exit(main())

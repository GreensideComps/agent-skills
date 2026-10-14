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

from . import index, pipeline, research
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
    print(f"taxonomy {snap.get('taxonomy', 'us-gaap')}, currency {snap.get('reporting_currency')}, "
          f"SIC {snap.get('sic')} {snap.get('sic_description') or ''} -> template "
          f"{snap.get('industry_template', 'unclassified (pre-M2 snapshot)')} "
          f"(screening supported: {snap.get('screen_supported')})")
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
             "industry_supported": snap.get("screen_supported") if snap else None,
             "bear_case_recorded": research.current_bear_case(store, s["company_id"], snap) is not None}
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
    if a.supported_only:
        where.append("c.screen_supported = 1")
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


def cmd_coverage(store: Store, a) -> int:
    """Data-coverage survey over the latest snapshot of every ingested company: confidence by
    taxonomy and industry template, and the most common causes of missing data."""
    from collections import Counter  # noqa: PLC0415

    from .ingest import unpacked  # noqa: PLC0415
    latest: dict[str, dict] = {}
    for s in store.fundamentals.read():
        if s["company_id"] not in latest or s["retrieved_utc"] > latest[s["company_id"]]["retrieved_utc"]:
            latest[s["company_id"]] = s
    snaps = [unpacked(s) for s in latest.values()
             if not a.method or s.get("method_version") == a.method]
    by = Counter((s.get("taxonomy", "us-gaap"), s.get("industry_template", "unclassified"), s["confidence"])
                 for s in snaps)
    flags = Counter(f.split(":")[0] + ":" + f.split(":")[1] if f.startswith(("missing", "not_meaningful"))
                    else f.split(":")[0] for s in snaps for f in s["flags"])
    concepts = Counter((m, v["c"]) for s in snaps for m, v in
                       s["years"].get(s["summary"].get("latest_fy_end"), {}).items())
    out = {"companies": len(snaps), "method_filter": a.method,
           "confidence": dict(Counter(s["confidence"] for s in snaps)),
           "screen_supported": sum(1 for s in snaps if s.get("screen_supported") is True),
           "unclassified_pre_m2": sum(1 for s in snaps if "screen_supported" not in s),
           "by_taxonomy_template_confidence": {" / ".join(k): n for k, n in sorted(by.items())},
           "flags": dict(flags.most_common(25)),
           "concepts_used_latest_year": {f"{m} <- {c}": n for (m, c), n in sorted(concepts.items())}}
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0


def _primary_priced(store: Store, ids: set[str]) -> list[dict]:
    """The SEC-verified US listing of each company (the only lines priced so far)."""
    out = {}
    for s in sorted(latest_securities(store).values(), key=lambda s: s["t212_ticker"]):
        if s["company_id"] in ids and not s.get("absent") and s.get("sec_match") == "high" \
                and s["company_id"] not in out:
            out[s["company_id"]] = s
    return list(out.values())


def cmd_prices(store: Store, a) -> int:
    from .prices import update_prices  # noqa: PLC0415
    ids = {s["company_id"] for s in store.fundamentals.read()}
    if a.symbol:
        ids &= {resolve(store, symbol=x)["company_id"] for x in a.symbol if resolve(store, symbol=x)}
    with job(store, "update_prices", {"companies": len(ids)}, redact=_secrets()) as j:
        res = update_prices(store, _primary_priced(store, ids))
        j["outputs"] = {k: (len(v) if isinstance(v, list) else v) for k, v in res.items()}
    print(json.dumps(res, indent=1))
    return 1 if res["failed"] and not res["written"] else 0


def cmd_screen(store: Store, a) -> int:
    from . import screener  # noqa: PLC0415
    from . import alerts, valuation  # noqa: PLC0415
    with job(store, "screen", {}, redact=_secrets()) as j:
        rec = screener.run(store)
        vals = valuation.run(store, rec)
        al = alerts.run(store, rec)
        j["outputs"] = {"rid": rec["rid"], "companies": rec["companies"], "eligible": rec["eligible"],
                        "valuations": len(vals), "alerts": len(al["alerts"]), "alert_baseline": al["baseline"]}
    md = screener.report(rec, a.top, {v["company_id"]: v for v in vals}, al)
    out = Path(__file__).resolve().parent.parent / "reports" / "screens" / f"{rec['as_of']}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    print(md)
    print("->", out)
    return 0


def cmd_explain(store: Store, a) -> int:
    """Every sub-score and gate of one company in the latest screen run."""
    from . import screener  # noqa: PLC0415
    s = resolve(store, symbol=a.symbol)
    out = screener.explain(store, s["company_id"]) if s else None
    if not out:
        print("not found, or not in the latest screen run")
        return 1
    r, full = out
    print(f"{r['entity_name']}  run {full['run_rid']}  total={r['total']}  rank={r.get('rank')}  eligible={r['eligible']}")
    if not full["config_matches_run"]:
        print("  WARNING: config/screener.json changed since this run; breakdown uses the current config")
    for name, c in full["components"].items():
        print(f"  {name:<14} score={c['score']} coverage={c['coverage']:.0%}")
        for p in c["parts"]:
            print(f"      {p['metric']:<28} value={p['value']} score={p['score']} scale={p['scale']} w={p['weight']}")
    for g in r["gates"]:
        print(f"  gate {g['gate']:<20} {g['result']:<7} {g['detail']}")
    print("  valuation", json.dumps(r["valuation"]))
    return 0


def cmd_valuate(store: Store, a) -> int:
    from . import valuation  # noqa: PLC0415
    s = resolve(store, symbol=a.symbol)
    v = [x for x in store.valuations.read() if s and x["company_id"] == s["company_id"]]
    if not v:
        print("no valuation (run `screen`; companies without a market value are not valued)")
        return 1
    v = max(v, key=lambda x: x["ts_utc"])
    print(f"{v['entity_name']} ({valuation.METHOD_VERSION}) price {v['price']} market cap {v['market_cap']:,.0f} "
          f"EV {v['enterprise_value']:,.0f}")
    print("  multiples:", {k: (None if x is None else round(x, 3)) for k, x in v["multiples"].items()})
    print(f"  base FCF {v.get('base_fcf')}, history growth {v.get('history_growth')}")
    for name, sc in (v.get("scenarios") or {}).items():
        print(f"  {name:<5} growth {sc['growth_5y']:+.1%}/yr -> {sc['value_per_share']:,.2f}/share ({sc['upside']:+.0%})")
    ig = v.get("implied_growth_5y")
    print("  price implies", "n/a" if ig is None else f"{ig:+.1%}/yr FCF growth for 5 years", "|", "; ".join(v["notes"]))
    print("  assumptions:", json.dumps(v["assumptions"]))
    return 0


def _pairs(items: list[str], evidence: list[str], watch: list[str] | None = None) -> list[dict]:
    if len(evidence) != len(items) or (watch is not None and len(watch) != len(items)):
        raise research.ResearchError("give one --evidence (and one --watch for objections) per point, in order")
    return [{("objection" if watch is not None else "claim"): t, "evidence": [e for e in ev.split("|") if e],
             **({"watch": watch[i]} if watch is not None else {})} for i, (t, ev) in enumerate(zip(items, evidence))]


def cmd_thesis(store: Store, a) -> int:
    s = resolve(store, symbol=a.symbol)
    try:
        r = research.add_thesis(store, s["company_id"], a.actor, a.summary, _pairs(a.point, a.evidence))
    except research.ResearchError as e:
        print("REFUSED:", e)
        return 2
    print("recorded", r["rid"])
    return 0


def cmd_bearcase(store: Store, a) -> int:
    s = resolve(store, symbol=a.symbol)
    try:
        r = research.add_bear_case(store, s["company_id"], a.actor, _pairs(a.objection, a.evidence, a.watch or []))
    except research.ResearchError as e:
        print("REFUSED:", e)
        return 2
    print("recorded", r["rid"])
    return 0


def cmd_alerts(store: Store, a) -> int:
    al = sorted(store.alerts.read(), key=lambda x: x["ts_utc"])[-a.limit:]
    for x in al:
        print(f"{x['as_of']} {x['kind']:<15} {x.get('entity_name') or x['company_id']}: {x['text']}")
    print(f"{len(al)} alerts")
    return 0


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
    s.add_argument("--supported-only", action="store_true", help="exclude industries the method does not support")
    s.add_argument("--limit", type=int, default=50)
    sub.add_parser("health")
    s = sub.add_parser("prices"); s.add_argument("--symbol", action="append")  # noqa: E702
    s = sub.add_parser("screen"); s.add_argument("--top", type=int, default=25)  # noqa: E702
    s = sub.add_parser("explain"); s.add_argument("symbol")  # noqa: E702
    s = sub.add_parser("valuate"); s.add_argument("symbol")  # noqa: E702
    s = sub.add_parser("alerts"); s.add_argument("--limit", type=int, default=50)  # noqa: E702
    s = sub.add_parser("thesis", help="record a thesis: --summary, then --point/--evidence pairs ('|' separates sources)")
    s.add_argument("symbol"); s.add_argument("--summary", required=True)  # noqa: E702
    s.add_argument("--point", action="append", required=True); s.add_argument("--evidence", action="append", required=True)  # noqa: E702
    s.add_argument("--actor", required=True)
    s = sub.add_parser("bearcase", help="record a bear case: --objection/--evidence/--watch triples")
    s.add_argument("symbol"); s.add_argument("--objection", action="append", required=True)  # noqa: E702
    s.add_argument("--evidence", action="append", required=True); s.add_argument("--watch", action="append", required=True)  # noqa: E702
    s.add_argument("--actor", required=True)
    s = sub.add_parser("coverage")
    s.add_argument("--method", help="only snapshots of this method version, e.g. fund-2.0")
    s.add_argument("--json", help="also write the survey to this file")
    s = sub.add_parser("crosscheck"); s.add_argument("--symbol", action="append", required=True)  # noqa: E702
    a = p.parse_args(argv)
    store = Store(Path(a.data)) if a.data else Store()
    handler = {"sync-universe": cmd_sync_universe, "ingest": cmd_ingest, "show": cmd_show,
               "discover": cmd_discover, "status": cmd_status, "search": cmd_search, "health": cmd_health,
               "coverage": cmd_coverage, "prices": cmd_prices, "screen": cmd_screen, "explain": cmd_explain,
               "valuate": cmd_valuate, "thesis": cmd_thesis, "bearcase": cmd_bearcase, "alerts": cmd_alerts,
               "crosscheck": cmd_crosscheck}
    return handler[a.cmd](store, a)


if __name__ == "__main__":
    sys.exit(main())
